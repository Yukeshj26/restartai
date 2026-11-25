"""SQLite storage service replacing in-memory dictionaries."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..core.database import get_db, init_db

logger = logging.getLogger("restartai.storage")


class StorageService:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        init_db(self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_idempotency(self, key: str) -> Optional[str]:
        if not key:
            return None
        with get_db(self.db_path) as conn:
            row = conn.execute("SELECT run_id FROM idempotency WHERE key = ?", (key,)).fetchone()
            return row["run_id"] if row else None

    def set_idempotency(self, key: str, run_id: str) -> None:
        if not key:
            return
        with get_db(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO idempotency (key, run_id, created_at) VALUES (?, ?, ?)",
                (key, run_id, self._now())
            )

    def save_run(self, state: Dict[str, Any]) -> None:
        run_id = state["run_id"]
        now = self._now()
        decisions = {
            "best_expected_plan": state.get("best_expected_plan"),
            "safe_plan": state.get("safe_plan"),
            "fallback_plan": state.get("fallback_plan"),
            "sensitivity": state.get("sensitivity"),
            "cross_reference": state.get("cross_reference"),
            "technician_schedule": state.get("technician_schedule"),
        }
        with get_db(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, stage, mode, request_json, maintenance_json, next_supplier_index, approved, call_failures_json, decisions_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    stage = excluded.stage,
                    mode = excluded.mode,
                    request_json = excluded.request_json,
                    maintenance_json = excluded.maintenance_json,
                    next_supplier_index = excluded.next_supplier_index,
                    approved = excluded.approved,
                    call_failures_json = excluded.call_failures_json,
                    decisions_json = excluded.decisions_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    state.get("stage", "initial_calls"),
                    state.get("mode", "demo"),
                    json.dumps(state.get("request", {})),
                    json.dumps(state.get("maintenance", {})),
                    int(state.get("next_supplier_index", 0)),
                    1 if state.get("approved") else 0,
                    json.dumps(state.get("call_failures", [])),
                    json.dumps(decisions),
                    state.get("created_at", now),
                    now
                )
            )

            # Persist offers
            conn.execute("DELETE FROM offers WHERE run_id = ?", (run_id,))
            for o in state.get("offers", []):
                conn.execute(
                    """
                    INSERT INTO offers (
                        run_id, supplier, phone, quantity_available, unit_price,
                        currency, availability_hours, delivery_method, compatible,
                        compatibility_confidence, confirmed, status, source, call_id, notes,
                        transcript, extracted_fields_json, retry_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        o.get("supplier", ""),
                        o.get("phone", ""),
                        int(o.get("quantity_available", 0)),
                        float(o.get("unit_price", 0.0)),
                        o.get("currency", "INR"),
                        float(o.get("availability_hours", 999.0)),
                        o.get("delivery_method", "unknown"),
                        1 if o.get("compatible") else 0,
                        float(o.get("compatibility_confidence", 0.0)),
                        1 if o.get("confirmed") else 0,
                        o.get("status", "UNAVAILABLE"),
                        o.get("source", "demo"),
                        o.get("call_id"),
                        o.get("notes", ""),
                        o.get("transcript", ""),
                        json.dumps(o.get("extracted_fields", {})),
                        int(o.get("retry_count", 0)),
                        now
                    )
                )

            # Persist plans
            conn.execute("DELETE FROM plans WHERE run_id = ?", (run_id,))
            for rank, p in enumerate(state.get("plans", [])):
                conn.execute(
                    """
                    INSERT INTO plans (
                        run_id, rank, is_recommended, plan_json, total_exposure,
                        recovery_time_hours, feasible, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        rank,
                        1 if rank == 0 else 0,
                        json.dumps(p),
                        float(p.get("total_exposure", 0.0)),
                        float(p.get("recovery_time_hours", 0.0)),
                        1 if p.get("feasible") else 0,
                        now
                    )
                )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with get_db(self.db_path) as conn:
            run_row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not run_row:
                return None

            offer_rows = conn.execute(
                "SELECT * FROM offers WHERE run_id = ? ORDER BY id ASC", (run_id,)
            ).fetchall()
            offers = [
                {
                    "supplier": o["supplier"],
                    "phone": o["phone"],
                    "quantity_available": o["quantity_available"],
                    "unit_price": o["unit_price"],
                    "currency": o["currency"],
                    "availability_hours": o["availability_hours"],
                    "delivery_method": o["delivery_method"],
                    "compatible": bool(o["compatible"]),
                    "compatibility_confidence": o["compatibility_confidence"],
                    "confirmed": bool(o["confirmed"]),
                    "status": o["status"],
                    "source": o["source"],
                    "call_id": o["call_id"],
                    "notes": o["notes"] or "",
                    "transcript": o["transcript"] if "transcript" in o.keys() and o["transcript"] else "",
                    "extracted_fields": json.loads(o["extracted_fields_json"]) if "extracted_fields_json" in o.keys() and o["extracted_fields_json"] else {},
                    "retry_count": o["retry_count"] if "retry_count" in o.keys() else 0,
                }
                for o in offer_rows
            ]

            plan_rows = conn.execute(
                "SELECT plan_json FROM plans WHERE run_id = ? ORDER BY rank ASC", (run_id,)
            ).fetchall()
            plans = [json.loads(p["plan_json"]) for p in plan_rows]

            call_rows = conn.execute(
                "SELECT record_json FROM calls WHERE run_id = ? ORDER BY updated_at DESC", (run_id,)
            ).fetchall()
            calls = [json.loads(c["record_json"]) for c in call_rows]

            decisions = json.loads(run_row["decisions_json"]) if "decisions_json" in run_row.keys() and run_row["decisions_json"] else {}

            return {
                "run_id": run_row["run_id"],
                "stage": run_row["stage"],
                "mode": run_row["mode"],
                "request": json.loads(run_row["request_json"]),
                "maintenance": json.loads(run_row["maintenance_json"]),
                "next_supplier_index": run_row["next_supplier_index"],
                "approved": bool(run_row["approved"]),
                "call_failures": json.loads(run_row["call_failures_json"]) if "call_failures_json" in run_row.keys() and run_row["call_failures_json"] else [],
                "offers": offers,
                "plans": plans,
                "calls": calls,
                "best_expected_plan": decisions.get("best_expected_plan"),
                "safe_plan": decisions.get("safe_plan"),
                "fallback_plan": decisions.get("fallback_plan"),
                "sensitivity": decisions.get("sensitivity"),
                "cross_reference": decisions.get("cross_reference"),
                "technician_schedule": decisions.get("technician_schedule"),
                "created_at": run_row["created_at"],
                "updated_at": run_row["updated_at"],
            }

    def save_call(self, call_id: str, record: Dict[str, Any], run_id: Optional[str] = None) -> None:
        now = self._now()
        with get_db(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO calls (call_id, run_id, supplier, phone, status, record_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    run_id = COALESCE(excluded.run_id, calls.run_id),
                    supplier = excluded.supplier,
                    phone = excluded.phone,
                    status = excluded.status,
                    record_json = excluded.record_json,
                    updated_at = excluded.updated_at
                """,
                (
                    call_id,
                    run_id,
                    record.get("supplier", "Unknown"),
                    record.get("phone", ""),
                    record.get("status", "unknown"),
                    json.dumps(record),
                    record.get("created_at", now),
                    now
                )
            )

    def get_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        with get_db(self.db_path) as conn:
            row = conn.execute("SELECT record_json FROM calls WHERE call_id = ?", (call_id,)).fetchone()
            return json.loads(row["record_json"]) if row else None

    def list_calls(self) -> Dict[str, Dict[str, Any]]:
        with get_db(self.db_path) as conn:
            rows = conn.execute("SELECT call_id, record_json FROM calls").fetchall()
            return {row["call_id"]: json.loads(row["record_json"]) for row in rows}

    def add_audit_log(self, run_id: Optional[str], event_type: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        with get_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO audit_logs (run_id, event_type, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, event_type, message, json.dumps(payload or {}), self._now())
            )

    def get_audit_logs(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with get_db(self.db_path) as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM audit_logs WHERE run_id = ? ORDER BY id ASC", (run_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM audit_logs ORDER BY id ASC").fetchall()
            return [
                {
                    "id": r["id"],
                    "run_id": r["run_id"],
                    "event_type": r["event_type"],
                    "message": r["message"],
                    "payload": json.loads(r["payload_json"] or "{}"),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def save_fault_event(self, event: Dict[str, Any]) -> None:
        now = self._now()
        with get_db(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO fault_events (
                    event_id, machine_id, machine_name, sensor_id, fault_code, severity, payload_json, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event.get("machine_id", ""),
                    event.get("machine_name", ""),
                    event.get("sensor_id", ""),
                    event.get("fault_code", ""),
                    event.get("severity", "critical"),
                    json.dumps(event),
                    event.get("run_id"),
                    event.get("created_at", now),
                )
            )

    def list_fault_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM fault_events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [json.loads(r["payload_json"]) for r in rows]

    def clear(self) -> None:
        """Testing utility to clear state."""
        with get_db(self.db_path) as conn:
            conn.execute("DELETE FROM fault_events")
            conn.execute("DELETE FROM idempotency")
            conn.execute("DELETE FROM audit_logs")
            conn.execute("DELETE FROM calls")
            conn.execute("DELETE FROM plans")
            conn.execute("DELETE FROM offers")
            conn.execute("DELETE FROM runs")
