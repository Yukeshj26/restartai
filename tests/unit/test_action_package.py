"""Unit tests for Phase 5: ACT (Human-gated action package, mobile approver, print dossier)."""
import httpx
import pytest
from app.main import app
from app.models.models import RecoveryRequest, Supplier
from app.engine.recovery_engine import RecoveryEngine, RUNS, IDEMPOTENCY
from app.services.call_e_service import CalleService
from app.services.action_service import ActionService


@pytest.fixture(autouse=True)
def clean_state():
    RUNS.clear()
    IDEMPOTENCY.clear()
    yield
    RUNS.clear()
    IDEMPOTENCY.clear()


def make_golden_request():
    return RecoveryRequest(
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


def test_action_package_generation_golden_scenario():
    """Verify generated PO drafts, dispatch messages, stakeholder briefs, and CMMS ticket."""
    engine = RecoveryEngine(CalleService())
    action_service = ActionService()
    req = make_golden_request()

    res = engine.start(req)
    res = engine.replan(res["run_id"])

    pkg = action_service.generate_action_package(res)

    # 1. PO Drafts verification
    assert len(pkg.purchase_orders) == 2
    po_c = next(po for po in pkg.purchase_orders if po.supplier_name == "Supplier C")
    assert po_c.quantity == 8
    assert po_c.unit_price == 180.0
    assert po_c.subtotal == 1440.0
    assert "PO-REC-" in po_c.po_number
    assert po_c.is_dispatched is False
    assert "DRAFT" in po_c.status

    po_d = next(po for po in pkg.purchase_orders if po.supplier_name == "Supplier D")
    assert po_d.quantity == 12
    assert po_d.unit_price == 190.0
    assert po_d.subtotal == 2280.0
    assert po_d.is_dispatched is False

    assert sum(po.subtotal for po in pkg.purchase_orders) == 3720.0

    # 2. Safety & Governance Non-negotiable: Dispatch is disabled by default
    assert pkg.dispatch_enabled is False
    assert pkg.dispatch_policy == "HUMAN_APPROVAL_MANDATORY"
    assert pkg.is_approved is False

    # 3. Technician Dispatch SMS
    sms = pkg.technician_dispatch_message
    assert "CNC PRODUCTION LINE 4" in sms
    assert "SKF 6205-2RS" in sms
    assert "Supplier C" in sms and "8u" in sms
    assert "Supplier D" in sms and "12u" in sms
    assert "Lockout/Tagout" in sms
    assert "Shift A" in sms

    # 4. Stakeholder Status Brief
    brief = pkg.stakeholder_status_note
    assert "CNC Production Line 4" in brief
    assert "₹13,720" in brief
    assert "₹3,720" in brief
    assert "2.0 hours" in brief
    assert "Zero automated" in brief

    # 5. CMMS Ticket JSON
    cmms = pkg.cmms_ticket
    assert cmms["cmms_header"]["priority"] == "P1-CRITICAL"
    assert "WO-2026-REC-" in cmms["cmms_header"]["ticket_id"]
    assert len(cmms["parts_allocation"]) == 2
    assert cmms["economic_impact"]["total_economic_exposure_inr"] == 13720.0
    assert cmms["governance_audit"]["human_approval_required"] is True


def test_action_package_approval_transition():
    """Verify that action package reflects authorized state after operator approval."""
    engine = RecoveryEngine(CalleService())
    action_service = ActionService()
    req = make_golden_request()

    res = engine.start(req)
    res = engine.replan(res["run_id"])
    pkg_before = action_service.generate_action_package(res)
    assert pkg_before.is_approved is False
    assert "PENDING" in pkg_before.purchase_orders[0].status

    # Approve
    res_approved = engine.approve(res["run_id"])
    pkg_after = action_service.generate_action_package(res_approved)
    assert pkg_after.is_approved is True
    assert "AUTHORIZED" in pkg_after.purchase_orders[0].status
    assert "✓ AUTHORIZED" in pkg_after.technician_dispatch_message


@pytest.mark.asyncio
async def test_action_package_api_endpoints():
    """Verify REST endpoints for action package, mobile approver view, and print dossier."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
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

        # 1. Action Package API
        r_actions = await client.get(f"/api/recovery/{run_id}/actions")
        assert r_actions.status_code == 200
        pkg_data = r_actions.json()
        assert len(pkg_data["purchase_orders"]) == 2
        assert pkg_data["dispatch_enabled"] is False

        # 2. Mobile Approver HTML View (both /approver/{run_id} and /api/approver/{run_id})
        r_mob = await client.get(f"/approver/{run_id}")
        assert r_mob.status_code == 200
        assert "text/html" in r_mob.headers["content-type"]
        assert "CNC Production Line 4" in r_mob.text
        assert "AUTHORIZE RECOVERY PLAN" in r_mob.text
        assert "Human-in-the-Loop Governance" in r_mob.text

        r_mob_api = await client.get(f"/api/approver/{run_id}")
        assert r_mob_api.status_code == 200

        # 3. Print-Ready Industrial Recovery Dossier HTML
        r_report = await client.get(f"/api/recovery/{run_id}/report.html")
        assert r_report.status_code == 200
        assert "text/html" in r_report.headers["content-type"]
        assert "RESTARTAI EMERGENCY PRODUCTION RECOVERY DOSSIER" in r_report.text
        assert "PO NUMBER:" in r_report.text
        assert "Print / Save as PDF" in r_report.text
        assert "Precomputed Plan B Contingency" in r_report.text
