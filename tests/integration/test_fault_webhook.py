"""Integration tests for Asset Registry and Sensor Fault Webhook API."""

import httpx
import pytest
from app.main import app
from app.engine.recovery_engine import RUNS, IDEMPOTENCY


@pytest.fixture(autouse=True)
def clean_state():
    RUNS.clear()
    IDEMPOTENCY.clear()
    yield
    RUNS.clear()
    IDEMPOTENCY.clear()


@pytest.mark.asyncio
async def test_api_list_and_get_assets():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # List
        res = await client.get("/api/assets")
        assert res.status_code == 200
        data = res.json()
        assert "machines" in data
        assert len(data["machines"]) >= 4

        # Get specific
        res_cnc = await client.get("/api/assets/cnc-line-4")
        assert res_cnc.status_code == 200
        cnc = res_cnc.json()
        assert cnc["name"] == "CNC Production Line 4"
        assert cnc["downtime_cost_per_hour"] == 5000.0

        # Get 404
        res_404 = await client.get("/api/assets/unknown-id")
        assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_api_fault_webhook_dry_run():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        payload = {
            "machine_id": "cnc-line-4",
            "auto_start": False,
            "mode": "demo",
        }
        res = await client.post("/api/events/fault", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "event" in data
        assert data["event"]["machine_name"] == "CNC Production Line 4"
        assert data["event"]["sensor_id"] == "VIB-ACCEL-04"
        assert "incident" in data
        assert data["incident"]["quantity"] == 20
        assert data.get("run_id") is None


@pytest.mark.asyncio
async def test_api_fault_webhook_auto_start_golden_scenario():
    """Verify webhook auto-start initiates a recovery run that resolves to the golden plan."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        payload = {
            "machine_id": "cnc-line-4",
            "auto_start": True,
            "mode": "demo",
        }
        res = await client.post("/api/events/fault", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "run_id" in data
        run_id = data["run_id"]
        assert data["event"]["run_id"] == run_id

        # Replan
        replan_res = await client.post(f"/api/recovery/{run_id}/replan")
        assert replan_res.status_code == 200
        replan_data = replan_res.json()
        rec_plan = replan_data["recommended_plan"]
        assert rec_plan is not None
        assert rec_plan["feasible"] is True
        assert rec_plan["recovery_time_hours"] == 2.0
        assert rec_plan["total_purchase_cost"] == 3720.0
        assert rec_plan["total_exposure"] == 13720.0

        # Verify event shows up in fault events list
        events_res = await client.get("/api/events/faults")
        assert events_res.status_code == 200
        events = events_res.json()["events"]
        assert any(e["event_id"] == data["event"]["event_id"] for e in events)
