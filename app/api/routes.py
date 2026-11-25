"""API routes for RestartAI."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..models import RecoveryRequest, TestCallRequest, ChatRequest, FaultEventRequest
from ..engine.recovery_engine import RecoveryEngine
from ..services.call_e_service import CalleService, CallEError
from ..services.llm_service import LlmService, LlmError
from ..services.storage_service import StorageService
from ..services.asset_service import AssetService

router = APIRouter(prefix="/api")

calle_service = CalleService()
engine = RecoveryEngine(calle_service)
llm_service = LlmService()
storage_service = StorageService()
asset_service = AssetService()


@router.get("/health")
def health():
    return {"status": "ok", "service": "RestartAI", "mode": calle_service.mode}


@router.get("/assets")
def list_assets():
    return {"machines": asset_service.list_machines()}


@router.get("/assets/{machine_id}")
def get_asset(machine_id: str):
    machine = asset_service.get_machine(machine_id)
    if not machine:
        return JSONResponse({"error": f"Machine '{machine_id}' not found."}, status_code=404)
    return JSONResponse(machine)


@router.get("/events/faults")
def list_fault_events(limit: int = Query(default=20, ge=1, le=100)):
    events = storage_service.list_fault_events(limit=limit)
    return JSONResponse({"events": events})


@router.post("/events/fault")
async def trigger_fault_event(payload: FaultEventRequest):
    machine = asset_service.get_machine(payload.machine_id)
    if not machine:
        return JSONResponse({"error": f"Machine '{payload.machine_id}' not found in asset registry."}, status_code=404)

    sensor = machine.get("sensor", {})
    event_id = f"evt-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    telemetry = payload.telemetry_value or sensor.get("simulated_fault_value", 8.4)
    fault_code = payload.fault_code or sensor.get("default_fault_code", "ERR-FAULT-DETECTED")
    message = payload.message or sensor.get("default_fault_message", f"Abnormal condition on {machine['name']}")

    event = {
        "event_id": event_id,
        "machine_id": machine["id"],
        "machine_name": machine["name"],
        "sensor_id": payload.sensor_id or sensor.get("sensor_id", "SENSOR-UNKNOWN"),
        "sensor_type": sensor.get("type", "Telemetry"),
        "telemetry_metric": sensor.get("metric", "signal"),
        "telemetry_value": telemetry,
        "normal_threshold": sensor.get("normal_value"),
        "fault_threshold": sensor.get("fault_threshold"),
        "fault_code": fault_code,
        "severity": payload.severity,
        "message": message,
        "created_at": now,
        "run_id": None,
    }

    overrides = {
        "mode": payload.mode,
    }
    if payload.quantity is not None:
        overrides["quantity"] = payload.quantity
    if payload.max_hours is not None:
        overrides["max_hours"] = payload.max_hours
    if payload.downtime_cost_per_hour is not None:
        overrides["downtime_cost_per_hour"] = payload.downtime_cost_per_hour
    if payload.available_technicians is not None:
        overrides["available_technicians"] = payload.available_technicians

    req = asset_service.build_recovery_request(machine["id"], overrides)

    if payload.auto_start:
        use_live = (payload.mode == "live") if payload.mode else (calle_service.mode == "live")
        result = await engine.start_async(req) if use_live else engine.start(req)
        event["run_id"] = result["run_id"]
        storage_service.save_fault_event(event)
        storage_service.add_audit_log(
            result["run_id"],
            "sensor_fault_event",
            f"Automated trigger from sensor {event['sensor_id']} on {machine['name']}: {fault_code}",
            event,
        )
        return JSONResponse({
            "success": True,
            "event": event,
            "incident": req.model_dump(),
            "run_id": result["run_id"],
            "recovery": result,
        })
    else:
        storage_service.save_fault_event(event)
        return JSONResponse({
            "success": True,
            "event": event,
            "incident": req.model_dump(),
        })


@router.get("/config")
def config():
    return {"mode": calle_service.mode, "live": calle_service.mode == "live"}


@router.get("/maintenance/intelligence")
def maintenance_intelligence(
    part_number: str = "",
    part_description: str = "",
    available_technicians: int = Query(default=3, ge=0),
    required_technicians_override: int | None = Query(default=None, ge=0),
    installation_minutes_override: int | None = Query(default=None, ge=0),
):
    return engine.maintenance_intelligence(
        part_number,
        part_description,
        available_technicians,
        required_technicians_override,
        installation_minutes_override,
    )


@router.post("/recovery/start")
async def start_recovery(payload: RecoveryRequest):
    use_live = (payload.mode == "live") if payload.mode else (calle_service.mode == "live")
    result = await engine.start_async(payload) if use_live else engine.start(payload)
    return JSONResponse(result)


@router.post("/recovery/{run_id}/replan")
async def replan(run_id: str):
    try:
        run_mode = engine.get_mode(run_id)
        result = await engine.replan_async(run_id) if run_mode == "live" else engine.replan(run_id)
        return JSONResponse(result)
    except KeyError:
        return JSONResponse({"error": "Recovery run not found."}, status_code=404)


@router.post("/recovery/{run_id}/approve")
def approve(run_id: str):
    try:
        return JSONResponse(engine.approve(run_id))
    except KeyError:
        return JSONResponse({"error": "Recovery run not found."}, status_code=404)


@router.get("/recovery/{run_id}")
def get_recovery(run_id: str):
    result = engine.get(run_id)
    if not result:
        return JSONResponse({"error": "Recovery run not found."}, status_code=404)
    return JSONResponse(result)


@router.get("/recovery/{run_id}/calls")
def recovery_calls(run_id: str):
    result = engine.get(run_id)
    if not result:
        return JSONResponse({"error": "Recovery run not found."}, status_code=404)
    return JSONResponse({"calls": result.get("calls", [])})


@router.get("/recovery/{run_id}/audit")
def recovery_audit_logs(run_id: str):
    logs = storage_service.get_audit_logs(run_id)
    return JSONResponse({"run_id": run_id, "logs": logs})


@router.get("/recovery/{run_id}/sensitivity")
def get_recovery_sensitivity(run_id: str):
    result = engine.get(run_id)
    if not result:
        return JSONResponse({"error": "Recovery run not found."}, status_code=404)
    return JSONResponse(result.get("sensitivity", {}))


@router.get("/suppliers/registry")
def list_suppliers_registry():
    return JSONResponse({"suppliers": engine.supplier_registry.list_suppliers()})


@router.post("/suppliers/registry/{supplier_name}")
async def update_supplier_reliability(supplier_name: str, request: Request):
    try:
        body = await request.json()
        score = float(body.get("reliability_score", 0.90))
    except Exception:
        return JSONResponse({"error": "Invalid request body. Expected JSON with 'reliability_score'."}, status_code=400)

    updated = engine.supplier_registry.update_supplier_reliability(supplier_name, score)
    if not updated:
        return JSONResponse({"error": f"Failed to update supplier '{supplier_name}'."}, status_code=400)
    return JSONResponse({"success": True, "supplier": updated})


@router.get("/parts/cross-reference")
def get_parts_cross_reference(part_number: str = Query(default="SKF 6205-2RS")):
    equivalents = engine._get_cross_reference(part_number)
    return JSONResponse({"part_number": part_number, "equivalents": equivalents})


@router.get("/config/llm")
def llm_config():
    return {"enabled": llm_service.enabled}


@router.post("/recovery/{run_id}/recommendation")
async def recovery_recommendation(run_id: str):
    result = engine.get(run_id)
    if not result:
        return JSONResponse({"error": "Recovery run not found."}, status_code=404)
    if not result.get("plans"):
        return JSONResponse({"success": False, "error": "No recovery plan is available yet."}, status_code=400)
    try:
        return JSONResponse(await llm_service.recommend(result))
    except LlmError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=502)


@router.post("/recovery/{run_id}/chat")
async def recovery_chat(run_id: str, payload: ChatRequest):
    result = engine.get(run_id)
    if not result:
        return JSONResponse({"error": "Recovery run not found."}, status_code=404)
    try:
        history = [m.model_dump() for m in payload.history]
        return JSONResponse(await llm_service.chat(result, payload.message, history))
    except LlmError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=502)


@router.post("/calle/test-call")
async def test_call(payload: TestCallRequest):
    # The generic connectivity call was the source of repeated "test" calls.
    # Keep the endpoint for backwards compatibility, but never place a call here.
    return JSONResponse(
        {"success": False, "error": "Generic CALL-E test calls are disabled. Use /api/recovery/start for a real supplier recovery call."},
        status_code=410,
    )


@router.get("/calle/call/{call_id}")
async def test_call_status(call_id: str):
    if call_id not in calle_service.calls:
        return JSONResponse({"success": False, "error": "CALL-E call not found."}, status_code=404)
    try:
        return JSONResponse(await calle_service.get_call_status(call_id))
    except CallEError as exc:
        return JSONResponse(
            {"success": False, "error": str(exc), "code": exc.code, "details": {"call_id": call_id}},
            status_code=502,
        )
