"""Unit tests for SQLite persistence in StorageService."""

import tempfile
from pathlib import Path
import pytest

from app.core.database import init_db
from app.services.storage_service import StorageService
from app.engine.recovery_engine import RecoveryEngine
from app.services.call_e_service import CalleService
from app.models import RecoveryRequest, Supplier


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_restartai.db"
    return db_file


def test_db_initialization(temp_db):
    init_db(temp_db)
    assert temp_db.exists()
    assert temp_db.stat().st_size > 0


def test_storage_run_crud(temp_db):
    storage = StorageService(temp_db)
    state = {
        "run_id": "run-101",
        "stage": "initial_calls",
        "mode": "demo",
        "request": {
            "machine": "CNC 1",
            "part_number": "6205",
            "part_description": "Bearing",
            "quantity": 10,
            "max_hours": 3.0,
            "downtime_cost_per_hour": 5000.0,
            "suppliers": [],
        },
        "maintenance": {"task": "bearing_replacement", "required_technicians": 2},
        "next_supplier_index": 2,
        "approved": False,
        "offers": [
            {
                "supplier": "Supplier A",
                "phone": "+919876543211",
                "quantity_available": 5,
                "unit_price": 100.0,
                "currency": "INR",
                "availability_hours": 1.0,
                "delivery_method": "courier",
                "compatible": True,
                "compatibility_confidence": 1.0,
                "confirmed": True,
                "status": "PARTIAL",
                "source": "demo",
                "notes": "Good stock",
            }
        ],
        "plans": [
            {
                "legs": [],
                "total_purchase_cost": 500.0,
                "material_arrival_hours": 1.0,
                "installation_minutes": 30,
                "recovery_time_hours": 1.5,
                "downtime_exposure": 7500.0,
                "total_exposure": 8000.0,
                "compatibility_confidence": 1.0,
                "required_technicians": 2,
                "available_technicians": 3,
                "feasible": True,
                "infeasibility_reasons": [],
            }
        ],
    }

    storage.save_run(state)

    loaded = storage.get_run("run-101")
    assert loaded is not None
    assert loaded["run_id"] == "run-101"
    assert loaded["mode"] == "demo"
    assert loaded["next_supplier_index"] == 2
    assert len(loaded["offers"]) == 1
    assert loaded["offers"][0]["supplier"] == "Supplier A"
    assert loaded["offers"][0]["quantity_available"] == 5
    assert len(loaded["plans"]) == 1
    assert loaded["plans"][0]["total_exposure"] == 8000.0


def test_persistence_across_restart(temp_db):
    """Simulate a server restart: write with engine 1, shutdown, read with engine 2."""
    calle = CalleService()
    calle.mode = "demo"

    # Process run in engine 1
    storage1 = StorageService(temp_db)
    engine1 = RecoveryEngine(calle, storage=storage1)

    req = RecoveryRequest(
        mode="demo",
        machine="CNC Production Line 4",
        part_number="SKF 6205-2RS",
        part_description="Deep-groove ball bearing",
        quantity=20,
        max_hours=3.0,
        downtime_cost_per_hour=5000.0,
        available_technicians=3,
        suppliers=[
            Supplier(name="Supplier A", phone="+919876543211"),
            Supplier(name="Supplier B", phone="+919876543212"),
            Supplier(name="Supplier C", phone="+919876543213"),
            Supplier(name="Supplier D", phone="+919876543214"),
        ],
    )
    result1 = engine1.start(req)
    run_id = result1["run_id"]
    engine1.replan(run_id)

    # Server restarts: engine1 and storage1 go out of scope.
    # New engine2 starts with new StorageService pointing to the same DB file.
    storage2 = StorageService(temp_db)
    engine2 = RecoveryEngine(calle, storage=storage2)

    loaded = engine2.get(run_id)
    assert loaded is not None
    assert loaded["run_id"] == run_id
    assert loaded["stage"] == "replanned"
    assert len(loaded["offers"]) == 4
    assert loaded["recommended_plan"] is not None
    assert loaded["recommended_plan"]["total_exposure"] == 13720.0


def test_audit_logs(temp_db):
    storage = StorageService(temp_db)
    storage.add_audit_log("run-test", "event_1", "First audit event", {"key": "val1"})
    storage.add_audit_log("run-test", "event_2", "Second audit event", {"key": "val2"})

    logs = storage.get_audit_logs("run-test")
    assert len(logs) == 2
    assert logs[0]["event_type"] == "event_1"
    assert logs[0]["payload"]["key"] == "val1"
    assert logs[1]["event_type"] == "event_2"


def test_idempotency_persistence(temp_db):
    storage = StorageService(temp_db)
    storage.set_idempotency("key-123", "run-456")
    assert storage.get_idempotency("key-123") == "run-456"
    assert storage.get_idempotency("non-existent") is None


def test_postgres_url_detection():
    from app.core.database import is_postgres_url

    assert is_postgres_url("postgresql://user:pass@localhost:5432/restartai") is True
    assert is_postgres_url("postgres://user:pass@localhost:5432/restartai") is True
    assert is_postgres_url("POSTGRESQL://localhost/db") is True
    assert is_postgres_url("sqlite:///data/restartai.db") is False
    assert is_postgres_url("") is False
    assert is_postgres_url(None) is False


def test_database_connection_wrapper_placeholder_translation():
    from app.core.database import DatabaseConnection

    class DummyRawConn:
        def __init__(self):
            self.last_query = None
            self.last_params = None

        def cursor(self):
            return self

        def execute(self, q, p=()):
            self.last_query = q
            self.last_params = p
            return self

    raw = DummyRawConn()
    pg_conn = DatabaseConnection(raw, is_postgres=True)
    pg_conn.execute(
        "SELECT * FROM runs WHERE run_id = ? AND stage = ?", ("r-1", "done")
    )
    assert raw.last_query == "SELECT * FROM runs WHERE run_id = %s AND stage = %s"
    assert raw.last_params == ("r-1", "done")
