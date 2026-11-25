"""API routes for RestartAI."""
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..models import RecoveryRequest, TestCallRequest, ChatRequest
from ..engine.recovery_engine import RecoveryEngine
from ..services.call_e_service import CalleService, CallEError
from ..services.llm_service import LlmService, LlmError
from ..services.storage_service import StorageService

router = APIRouter(prefix="/api")

calle_service = CalleService()
engine = RecoveryEngine(calle_service)
llm_service = LlmService()
storage_service = StorageService()


@router.get("/health")
def health():
    return {"status": "ok", "service": "RestartAI", "mode": calle_service.mode}


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
