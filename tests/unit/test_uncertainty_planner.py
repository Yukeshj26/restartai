"""Unit tests for Phase 4: DECIDE (Uncertainty-Aware Planner, Fallback Plan B, Sensitivity, and Scheduling)."""
import httpx
import pytest
from app.main import app
from app.models.models import RecoveryRequest, Supplier, Offer
from app.engine.recovery_engine import RecoveryEngine, RUNS, IDEMPOTENCY
from app.services.call_e_service import CalleService
from app.services.supplier_registry_service import SupplierRegistryService


@pytest.fixture(autouse=True)
def clean_state():
    RUNS.clear()
    IDEMPOTENCY.clear()
    yield
    RUNS.clear()
    IDEMPOTENCY.clear()


def make_request(suppliers=None, downtime_cost=5000.0, max_hours=3.0, qty=20):
    if suppliers is None:
        suppliers = [
            Supplier(name="Supplier A", phone="+919876543211"),
            Supplier(name="Supplier B", phone="+919876543212"),
            Supplier(name="Supplier C", phone="+919876543213"),
            Supplier(name="Supplier D", phone="+919876543214"),
        ]
    return RecoveryRequest(
        mode="demo",
        machine="CNC Production Line 4",
        part_number="SKF 6205-2RS",
        part_description="Deep-groove ball bearing",
        quantity=qty,
        max_hours=max_hours,
        downtime_cost_per_hour=downtime_cost,
        available_technicians=3,
        suppliers=suppliers,
        live_confirmed=False,
    )


def test_deterministic_risk_adjustment_haircuts():
    """Verify haircuts are deterministically applied to tentative or low-reliability offers."""
    engine = RecoveryEngine(CalleService())
    
    offers = [
        # 1. High-reliability confirmed offer -> NO haircut
        {
            "supplier": "Supplier B",
            "quantity_available": 20,
            "availability_hours": 2.0,
            "status": "CONFIRMED",
            "confirmed": True,
            "compatible": True,
            "compatibility_confidence": 1.0,
        },
        # 2. Tentative offer -> 25% qty discount, +0.5h time buffer
        {
            "supplier": "Supplier C",
            "quantity_available": 8,
            "availability_hours": 0.5,
            "status": "TENTATIVE",
            "confirmed": True,
            "compatible": True,
            "compatibility_confidence": 1.0,
        },
        # 3. Custom low-reliability supplier (< 0.85) -> receives haircut even if CONFIRMED
        {
            "supplier": "Low Reliability Vendor",
            "quantity_available": 10,
            "availability_hours": 1.0,
            "status": "CONFIRMED",
            "confirmed": True,
            "compatible": True,
            "compatibility_confidence": 1.0,
        }
    ]
    
    engine.supplier_registry.update_supplier_reliability("Low Reliability Vendor", 0.70)
    
    adjusted = engine._apply_haircuts(offers)
    
    # Supplier B: untouched
    b = next(o for o in adjusted if o["supplier"] == "Supplier B")
    assert b["haircut_applied"] is False
    assert b["quantity_available"] == 20
    assert b["availability_hours"] == 2.0
    
    # Supplier C (TENTATIVE): haircut applied
    c = next(o for o in adjusted if o["supplier"] == "Supplier C")
    assert c["haircut_applied"] is True
    assert c["quantity_available"] == 6  # int(8 * 0.75) = 6
    assert c["availability_hours"] == 1.0  # 0.5 + 0.5 = 1.0
    assert "Uncertainty haircut" in c["haircut_reason"]
    
    # Low Reliability Vendor (rel 0.70): haircut applied
    low = next(o for o in adjusted if o["supplier"] == "Low Reliability Vendor")
    assert low["haircut_applied"] is True
    assert low["quantity_available"] == 7  # int(10 * 0.75) = 7
    assert low["availability_hours"] == 1.5  # 1.0 + 0.5 = 1.5


def test_safe_plan_and_best_expected_plan_triad():
    """Verify that both Best Expected Plan and Safe Plan are generated in the Decision Triad."""
    engine = RecoveryEngine(CalleService())
    req = make_request()
    
    # Run start and replan
    res = engine.start(req)
    res = engine.replan(res["run_id"])
    
    # Best expected plan
    best = res["best_expected_plan"]
    assert best is not None
    assert best["feasible"] is True
    assert [l["supplier"] for l in best["legs"]] == ["Supplier C", "Supplier D"]
    assert best["total_exposure"] == 13720.0
    
    # Safe plan (in golden scenario, C and D are both confirmed and >= 0.95 confidence)
    safe = res["safe_plan"]
    assert safe is not None
    assert safe["feasible"] is True
    assert safe["plan_type"] == "safe"
    assert safe["total_exposure"] == 13720.0


def test_precomputed_fallback_plan_b():
    """Verify that Plan B is precomputed as contingency if the primary leg fails."""
    engine = RecoveryEngine(CalleService())
    req = make_request()
    
    res = engine.start(req)
    res = engine.replan(res["run_id"])
    
    fallback = res["fallback_plan"]
    assert fallback is not None
    assert fallback["primary_critical_leg"] == "Supplier C"
    assert "If Supplier C" in fallback["trigger_condition"]
    assert fallback["feasible"] is True
    
    # If Supplier C fails, the next best plan combines Supplier D (12) + Supplier B (8)
    p_b = fallback["plan"]
    assert p_b is not None
    assert [l["supplier"] for l in p_b["legs"]] == ["Supplier D", "Supplier B"]
    assert p_b["recovery_time_hours"] == 2.5
    assert fallback["delta_exposure"] == 2820.0  # 16540 - 13720 = 2820
    assert fallback["delta_recovery_hours"] == 0.5  # 2.5h - 2.0h = 0.5h


def test_sensitivity_and_breakeven_analysis():
    """Verify sensitivity points across downtime loss rates and delay tolerance."""
    engine = RecoveryEngine(CalleService())
    req = make_request()
    
    res = engine.start(req)
    res = engine.replan(res["run_id"])
    
    sens = res["sensitivity"]
    assert sens is not None
    assert len(sens["points"]) == 6
    
    rates = [p["downtime_rate"] for p in sens["points"]]
    assert rates == [1000.0, 2500.0, 5000.0, 7500.0, 10000.0, 15000.0]
    
    # At rate 5000/hr, net savings of C+D over installed Supplier B (16,900) is 3,180
    pt_5k = next(p for p in sens["points"] if p["downtime_rate"] == 5000.0)
    assert pt_5k["recommended_plan_exposure"] == 13720.0
    assert pt_5k["single_source_b_exposure"] == 16900.0
    assert pt_5k["net_savings"] == 3180.0
    
    # Breakeven delay tolerance for Supplier D before reaching arrival baseline 14,400
    assert sens["breakeven_delay_minutes"] == 8.2
    assert "8.2-minute slip tolerance" in sens["breakeven_explanation"]


def test_part_cross_reference_interchange():
    """Verify interchangeable part equivalents with confirmation flag."""
    engine = RecoveryEngine(CalleService())
    equivalents = engine._get_cross_reference("SKF 6205-2RS")
    
    assert len(equivalents) >= 3
    brands = {eq["brand"] for eq in equivalents}
    assert {"FAG", "NSK", "NTN"}.issubset(brands)
    
    for eq in equivalents:
        assert eq["requires_confirmation"] is True
        assert eq["compatibility_confidence"] >= 0.95
        assert eq["status"] == "REQUIRES CONFIRMATION"


def test_technician_shift_and_milestone_schedule():
    """Verify maintenance shift assignment and 5-step precision recovery milestones."""
    engine = RecoveryEngine(CalleService())
    req = make_request()
    res = engine.start(req)
    res = engine.replan(res["run_id"])
    
    sched = res["technician_schedule"]
    assert sched is not None
    shift = sched["shift"]
    assert shift["shift_id"] == "SHIFT-A"
    assert shift["capacity_status"] == "SUFFICIENT"
    assert len(shift["assigned_crew"]) >= 2
    
    milestones = sched["milestones"]
    assert len(milestones) >= 4
    phases = [m["phase"] for m in milestones]
    assert "ISOLATION" in phases
    assert "INSTALLATION" in phases
    assert "RESTART" in phases


@pytest.mark.asyncio
async def test_supplier_registry_and_sensitivity_endpoints():
    """Verify REST API endpoints for supplier registry, sensitivity, and cross-reference."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Get supplier registry
        r_reg = await client.get("/api/suppliers/registry")
        assert r_reg.status_code == 200
        suppliers = r_reg.json()["suppliers"]
        assert any(s["name"] == "Supplier B" for s in suppliers)
        
        # 2. Update supplier reliability score
        r_update = await client.post(
            "/api/suppliers/registry/Supplier B",
            json={"reliability_score": 0.98}
        )
        assert r_update.status_code == 200
        assert r_update.json()["supplier"]["reliability_score"] == 0.98
        
        # Reset score back to 0.96 for consistency
        await client.post("/api/suppliers/registry/Supplier B", json={"reliability_score": 0.96})
        
        # 3. Start run and test sensitivity endpoint
        req_payload = {
            "mode": "demo",
            "machine": "CNC Production Line 4",
            "part_number": "SKF 6205-2RS",
            "part_description": "Deep-groove ball bearing",
            "quantity": 20,
            "max_hours": 3.0,
            "downtime_cost_per_hour": 5000.0,
            "suppliers": [
                {"name": "Supplier A", "phone": "+919876543211"},
                {"name": "Supplier B", "phone": "+919876543212"},
                {"name": "Supplier C", "phone": "+919876543213"},
                {"name": "Supplier D", "phone": "+919876543214"},
            ],
            "live_confirmed": False,
        }
        r_start = await client.post("/api/recovery/start", json=req_payload)
        run_id = r_start.json()["run_id"]
        
        await client.post(f"/api/recovery/{run_id}/replan")
        
        r_sens = await client.get(f"/api/recovery/{run_id}/sensitivity")
        assert r_sens.status_code == 200
        sens_data = r_sens.json()
        assert len(sens_data["points"]) == 6
        assert sens_data["breakeven_delay_minutes"] == 8.2
        
        # 4. Cross reference endpoint
        r_xref = await client.get("/api/parts/cross-reference?part_number=SKF 6205-2RS")
        assert r_xref.status_code == 200
        equivs = r_xref.json()["equivalents"]
        assert len(equivs) >= 3
