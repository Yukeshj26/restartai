import asyncio
import httpx
import pytest
from app.main import app
from app.call_e_service import CalleService
from app.models import RecoveryRequest, Supplier
from app.recovery_engine import RecoveryEngine, RUNS, IDEMPOTENCY


@pytest.fixture(autouse=True)
def clean_state():
    RUNS.clear()
    IDEMPOTENCY.clear()
    yield
    RUNS.clear()
    IDEMPOTENCY.clear()


def test_golden_scenario_deterministic_engine():
    """Lock down the non-negotiable golden scenario in the deterministic Python engine:
    - Recommended plan: Supplier C (8 units @ Rs 180) + Supplier D (12 units @ Rs 190)
    - Recovery time: 2.0h (1.5h arrival + 30m install)
    - Total purchase cost: Rs 3,720
    - Downtime exposure: Rs 10,000 (2.0h * Rs 5,000/h)
    - Total economic exposure: Rs 13,720
    - Feasible: True
    - Alternative: Supplier B alone is Rs 14,400 arrival baseline exposure (Purchase Rs 4,400 + 2h downtime Rs 10,000)
    """
    service = CalleService()
    service.mode = "demo"
    engine = RecoveryEngine(service)

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
        live_confirmed=False,
    )

    start_res = engine.start(req)
    run_id = start_res["run_id"]
    replan_res = engine.replan(run_id)

    # 1. Recommended plan checks
    p = replan_res["recommended_plan"]
    assert p is not None, "Golden scenario must produce a recommended plan"
    assert p["feasible"] is True, "Golden scenario plan must be feasible"

    legs = [(l["supplier"], l["quantity"], l["unit_price"]) for l in p["legs"]]
    assert legs == [("Supplier C", 8, 180.0), ("Supplier D", 12, 190.0)], (
        f"Expected C(8)+D(12), got {legs}"
    )

    assert p["recovery_time_hours"] == 2.0, f"Expected 2.0h recovery, got {p['recovery_time_hours']}"
    assert p["total_purchase_cost"] == 3720.0, f"Expected Rs 3720 purchase, got {p['total_purchase_cost']}"
    assert p["downtime_exposure"] == 10000.0, f"Expected Rs 10000 downtime, got {p['downtime_exposure']}"
    assert p["total_exposure"] == 13720.0, f"Expected Rs 13720 total exposure, got {p['total_exposure']}"

    # 2. Alternative Supplier B check
    offers_by_name = {o["supplier"]: o for o in replan_res["offers"]}
    assert "Supplier B" in offers_by_name
    b_offer = offers_by_name["Supplier B"]
    assert b_offer["quantity_available"] == 20
    assert b_offer["unit_price"] == 220.0
    b_purchase = 20 * 220.0
    b_arrival_exposure = b_purchase + (b_offer["availability_hours"] * req.downtime_cost_per_hour)
    assert b_arrival_exposure == 14400.0, f"Expected Supplier B baseline Rs 14400, got {b_arrival_exposure}"


@pytest.mark.asyncio
async def test_golden_scenario_api_endpoint():
    """Verify golden scenario execution end-to-end via FastAPI HTTP endpoints."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "mode": "demo",
            "machine": "CNC Production Line 4",
            "part_number": "SKF 6205-2RS",
            "part_description": "Deep-groove ball bearing",
            "quantity": 20,
            "max_hours": 3.0,
            "downtime_cost_per_hour": 5000.0,
            "compatibility_notes": "6205-2RS",
            "available_technicians": 3,
            "suppliers": [
                {"name": "Supplier A", "phone": "+919876543211"},
                {"name": "Supplier B", "phone": "+919876543212"},
                {"name": "Supplier C", "phone": "+919876543213"},
                {"name": "Supplier D", "phone": "+919876543214"},
            ],
            "live_confirmed": False,
            "idempotency_key": "golden-api-test-0",
        }

        # 1. Start recovery
        r_start = await client.post("/api/recovery/start", json=payload)
        assert r_start.status_code == 200
        start_data = r_start.json()
        run_id = start_data["run_id"]

        # 2. Replan
        r_replan = await client.post(f"/api/recovery/{run_id}/replan")
        assert r_replan.status_code == 200
        replan_data = r_replan.json()
        rec = replan_data["recommended_plan"]

        assert rec["feasible"] is True
        assert rec["recovery_time_hours"] == 2.0
        assert rec["total_purchase_cost"] == 3720.0
        assert rec["downtime_exposure"] == 10000.0
        assert rec["total_exposure"] == 13720.0
