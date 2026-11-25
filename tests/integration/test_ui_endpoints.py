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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        html = resp.text

        # 4-Module Structure & Hash Navigation Stepper
        assert 'id="step-btn-1"' in html
        assert 'id="step-btn-2"' in html
        assert 'id="step-btn-3"' in html
        assert 'id="step-btn-4"' in html

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


@pytest.mark.asyncio
async def test_static_assets_served():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        css = await client.get("/static/styles.css")
        assert css.status_code == 200
        assert ".fleet-board-panel" in css.text
        assert ".btn-run-full-demo" in css.text

        js = await client.get("/static/app.js")
        assert js.status_code == 200
        assert "runFullDemoStory" in js.text
        assert "selectFleetAsset" in js.text
