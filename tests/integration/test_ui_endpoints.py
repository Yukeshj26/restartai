"""Integration tests for Phase 7: Demo-Grade UI & 4-Module Flow.

Verifies:
1. Main entrypoint GET / serves the 4-module single-page application.
2. All critical UI elements for the 3-minute hackathon demo exist in HTML:
   - Live Incident Board & Fleet Monitor (#liveIncidentBoard)
   - 3-Minute Walkthrough Banner & Trigger Button (#walkthroughBanner, #btnRunFullDemo)
   - Reset Demo button (#btnTopResetDemo)
   - Shortfall Moment highlight card & visual split bar (#shortfallBanner)
   - Counterfactual Explainer Panel (#counterfactualPanel)
   - Empirical Synthetic Benchmark Dashboard (#syntheticBenchmarkPanel)
   - Human-Gated Action Package (#actionPackagePanel)
   - Keyboard Accessibility Shortcuts Modal (#keyboardModal)
3. Static assets /static/styles.css and /static/app.js are reachable.
"""

import httpx
import pytest
from app.main import app


@pytest.mark.asyncio
async def test_ui_index_contains_all_phase7_elements():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        html = resp.text

        # 4-Module Structure & Hash Navigation Stepper
        assert 'id="step-btn-1"' in html
        assert 'id="step-btn-2"' in html
        assert 'id="step-btn-3"' in html
        assert 'id="step-btn-4"' in html
        assert 'id="continueToPlanBtn"' in html

        # Top Bar Demo Controls
        assert 'id="btnRunFullDemo"' in html
        assert 'id="btnTopResetDemo"' in html
        assert 'id="btnHelpShortcuts"' in html
        assert 'id="walkthroughBanner"' in html

        # Live Incident Board & Fleet Status
        assert 'id="liveIncidentBoard"' in html
        assert "CNC Production Line 4" in html
        assert "Stamping Press P-12" in html
        assert "Injection Molding Unit 02" in html

        # Shortfall Moment Highlight & Visual Allocation Bar
        assert 'id="shortfallBanner"' in html
        assert "shortfall-breakdown-bar" in html

        # Counterfactual Explainer
        assert 'id="counterfactualPanel"' in html
        assert "What If We Picked The Cheapest Supplier?" in html

        # Synthetic Benchmark Dashboard
        assert 'id="syntheticBenchmarkPanel"' in html
        assert "SYNTHETIC BENCHMARK · SEED 42" in html

        # Action Package & Keyboard Modal
        assert 'id="actionPackagePanel"' in html
        assert 'id="keyboardModal"' in html

        # Logs Module Elements
        assert 'id="step-btn-logs"' in html
        assert 'id="module-logs"' in html
        assert 'id="logsContainer"' in html
        assert 'id="tabLogsAll"' in html
        assert 'id="tabLogsAudit"' in html
        assert 'id="tabLogsSystem"' in html
        assert 'id="tabLogsErrors"' in html

        # New Incident Registration Modal & Controls
        assert 'id="btnRailNewIncident"' in html
        assert 'id="registerIncidentModal"' in html
        assert 'id="regMachine"' in html
        assert 'id="regPart"' in html
        assert 'id="regQty"' in html
        assert 'id="btnSubmitRegisterIncident"' in html


@pytest.mark.asyncio
async def test_logs_page_redirect_and_api():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Verify /logs redirects to /#/logs
        redir = await client.get("/logs", follow_redirects=False)
        assert redir.status_code in (302, 307)
        assert redir.headers["location"] == "/#/logs"

        # Verify /api/logs/system
        sys_res = await client.get("/api/logs/system")
        assert sys_res.status_code == 200
        sys_data = sys_res.json()
        assert "logs" in sys_data
        assert isinstance(sys_data["logs"], list)

        # Verify /api/logs/audit
        audit_res = await client.get("/api/logs/audit")
        assert audit_res.status_code == 200
        audit_data = audit_res.json()
        assert "logs" in audit_data
        assert isinstance(audit_data["logs"], list)

        # Verify consolidated /api/logs
        all_res = await client.get("/api/logs")
        assert all_res.status_code == 200
        all_data = all_res.json()
        assert all_data["success"] is True
        assert "audit_logs" in all_data
        assert "system_logs" in all_data

        # Verify delete system logs buffer
        del_res = await client.delete("/api/logs/system")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True


@pytest.mark.asyncio
async def test_static_assets_served():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        css = await client.get("/static/styles.css")
        assert css.status_code == 200
        assert ".fleet-board-panel" in css.text
        assert ".btn-run-full-demo" in css.text

        js = await client.get("/static/app.js")
        assert js.status_code == 200
        assert "runFullDemoStory" in js.text
        assert "selectFleetAsset" in js.text
        assert "openRegisterIncidentModal" in js.text
        assert "handleNewIncidentSubmit" in js.text
        assert "proceedToRecoveryPlan" in js.text


@pytest.mark.asyncio
async def test_register_custom_stamping_press_incident_e2e():
    """Verify that registering a custom incident (e.g. Stamping Press P-12) starts recovery,

    interrogates suppliers, computes optimal plan, and continues through the regular workflow.
    """
    payload = {
        "machine": "Stamping Press P-12",
        "part_number": "SEAL-KIT-HYD-80",
        "part_description": "High-pressure hydraulic cylinder seal kit",
        "quantity": 15,
        "max_hours": 3.5,
        "downtime_cost_per_hour": 8000.0,
        "compatibility_notes": "80mm piston, nitrile rubber or viton",
        "available_technicians": 2,
        "suppliers": [
            {"name": "Supplier A", "phone": "+919876543211"},
            {"name": "Supplier B", "phone": "+919876543212"},
            {"name": "Supplier C", "phone": "+919876543213"},
            {"name": "Supplier D", "phone": "+919876543214"},
        ],
        "mode": "demo",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post("/api/recovery/start", json=payload)
        assert res.status_code == 200
        data = res.json()

        # Verify run was initialized
        assert "run_id" in data
        run_id = data["run_id"]

        # Initial wave calls first 3 suppliers
        assert len(data["offers"]) == 3
        suppliers_called = [o["supplier"] for o in data["offers"]]
        assert "Supplier A" in suppliers_called
        assert "Supplier B" in suppliers_called
        assert "Supplier C" in suppliers_called

        # Adaptive wave 2 / replan triggered by shortfall dials Supplier D
        replan_res = await client.post(f"/api/recovery/{run_id}/replan")
        assert replan_res.status_code == 200
        replan_data = replan_res.json()
        assert len(replan_data["offers"]) == 4
        assert any(o["supplier"] == "Supplier D" for o in replan_data["offers"])

        # Verify recovery plans generated
        assert len(replan_data["plans"]) >= 1
        best_plan = replan_data.get("best_expected_plan") or replan_data["plans"][0]
        assert best_plan is not None
        assert sum(l["quantity"] for l in best_plan.get("legs", [])) == 15

        # Verify regular process continuation: get run status
        get_res = await client.get(f"/api/recovery/{run_id}")
        assert get_res.status_code == 200
        run_state = get_res.json()
        assert run_state["run_id"] == run_id

        # Verify regular process continuation: approve recovery plan
        appr_res = await client.post(f"/api/recovery/{run_id}/approve")
        assert appr_res.status_code == 200
        appr_data = appr_res.json()
        assert appr_data.get("approved") is True
