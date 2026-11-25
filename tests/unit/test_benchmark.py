"""Unit and integration tests for Phase 6: PROOF (Synthetic Benchmark & Counterfactual Explainer).

Invariants verified:
1. Synthetic benchmark is deterministically reproducible from seed 42 across 35 incidents.
2. All benchmark outputs are explicitly labeled 'SYNTHETIC BENCHMARK'.
3. RestartAI adaptive split-sourcing mathematically outperforms naive cheapest-first and fastest-single heuristics.
4. Counterfactual explainer on the Golden Scenario produces exact financial exposure numbers.
5. All public API endpoints return 200 with structured contract schemas.
"""

import httpx
import pytest

from app.main import app
from app.services.benchmark_service import BenchmarkService
from app.api.routes import benchmark_service
from app.engine.recovery_engine import RUNS, IDEMPOTENCY


@pytest.fixture(autouse=True)
def clean_state():
    RUNS.clear()
    IDEMPOTENCY.clear()
    yield
    RUNS.clear()
    IDEMPOTENCY.clear()


def test_synthetic_incident_generation():
    service = BenchmarkService(seed=42)
    incidents = service._synthetic_incidents
    assert (
        len(incidents) == 35
    ), "Must generate exactly 35 synthetic benchmark incidents"

    first = incidents[0]
    assert first["incident_id"] == "INC-SYNTH-001"
    assert first["machine"] == "CNC Production Line 4"
    assert "part_number" in first
    assert "quantity" in first
    assert "max_hours" in first
    assert "downtime_cost_per_hour" in first
    assert len(first["suppliers"]) == 4


def test_benchmark_kpis_and_strategies():
    service = BenchmarkService(seed=42)
    results = service.run_benchmark()

    # Invariant: Labeling must be explicit
    assert "SYNTHETIC BENCHMARK" in results["benchmark_meta"]["label"]
    assert results["benchmark_meta"]["incident_count"] == 35

    kpis = results["aggregate_kpis"]
    restartai = kpis["restartai"]
    fastest = kpis["fastest_single"]
    cheapest = kpis["cheapest_first"]

    # Invariant: RestartAI beats both heuristics on exposure and on-time reliability
    assert (
        restartai["on_time_recovery_rate"] > fastest["on_time_recovery_rate"]
    ), "RestartAI must achieve higher on-time rate than single-source"
    assert (
        fastest["on_time_recovery_rate"] > cheapest["on_time_recovery_rate"]
    ), "Fastest single must achieve higher on-time rate than cheapest"

    assert (
        restartai["avg_total_exposure"] < fastest["avg_total_exposure"]
    ), "RestartAI must have lower average exposure than fastest-single"
    assert (
        fastest["avg_total_exposure"] < cheapest["avg_total_exposure"]
    ), "Fastest single must have lower average exposure than naive cheapest"

    # Specific deterministic values for seed 42
    assert restartai["on_time_recovery_rate"] == 80.0
    assert fastest["on_time_recovery_rate"] == 60.0
    assert cheapest["on_time_recovery_rate"] == 0.0

    assert restartai["avg_total_exposure"] == 19467.25
    assert fastest["avg_total_exposure"] == 34047.06
    assert cheapest["avg_total_exposure"] == 144158.91


def test_counterfactual_explainer_golden_scenario():
    # Golden scenario run state
    mock_run_state = {
        "run_id": "test-golden-cf",
        "request": {
            "machine": "CNC Production Line 4",
            "part_number": "SKF 6205-2RS",
            "quantity": 20,
            "max_hours": 3.0,
            "downtime_cost_per_hour": 5000.0,
        },
        "recommended_plan": {
            "recovery_time_hours": 2.0,
            "total_purchase_cost": 3720.0,
            "total_exposure": 13720.0,
        },
    }

    cf = benchmark_service.get_counterfactual(mock_run_state)
    assert cf["run_id"] == "test-golden-cf"
    assert cf["target_machine"] == "CNC Production Line 4"

    # RestartAI Plan: 2.0h, purchase Rs 3,720, total Rs 13,720
    assert cf["restartai_plan"]["recovery_time_hours"] == 2.0
    assert cf["restartai_plan"]["purchase_cost"] == 3720.0
    assert cf["restartai_plan"]["total_exposure"] == 13720.0
    assert cf["restartai_plan"]["deadline_satisfied"] is True

    # Counterfactual 1: Cheapest-First (Supplier A)
    # Saves Rs 720 on purchase (Rs 3,000), but 24.5h shutdown = Rs 122,500 downtime -> Rs 125,500 total exposure
    c1 = cf["counterfactual_cheapest_first"]
    assert c1["purchase_cost"] == 3000.0
    assert c1["recovery_time_hours"] == 24.5
    assert c1["total_exposure"] == 125500.0
    assert c1["deadline_satisfied"] is False
    assert c1["deadline_breach_hours"] == 21.5
    assert c1["financial_penalty_vs_restartai"] == 111780.0  # Rs 125,500 - Rs 13,720
    assert "DISASTROUS OUTCOME" in c1["verdict"]

    # Counterfactual 2: Fastest-Single (Supplier B)
    # Purchase Rs 4,400, 2.5h recovery = Rs 12,500 downtime -> Rs 16,900 total exposure
    c2 = cf["counterfactual_fastest_single"]
    assert c2["purchase_cost"] == 4400.0
    assert c2["recovery_time_hours"] == 2.5
    assert c2["total_exposure"] == 16900.0
    assert c2["deadline_satisfied"] is True
    assert c2["financial_penalty_vs_restartai"] == 3180.0  # Rs 16,900 - Rs 13,720
    assert "SUBOPTIMAL SINGLE-SOURCE" in c2["verdict"]


@pytest.mark.asyncio
async def test_api_benchmark_summary_endpoint():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/benchmark/summary")
        assert response.status_code == 200
        data = response.json()
        assert "meta" in data
        assert "kpis" in data
        assert "SYNTHETIC BENCHMARK" in data["meta"]["label"]
        assert data["kpis"]["restartai"]["on_time_recovery_rate"] == 80.0


@pytest.mark.asyncio
async def test_api_benchmark_incidents_endpoint():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/benchmark/incidents")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 35
        assert data[0]["incident_id"] == "INC-SYNTH-001"


@pytest.mark.asyncio
async def test_api_recovery_counterfactual_endpoint():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Start golden scenario run
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
            "idempotency_key": "cf-api-test-0",
        }
        start_resp = await client.post("/api/recovery/start", json=payload)
        assert start_resp.status_code == 200
        run_id = start_resp.json()["run_id"]

        # Fetch counterfactual
        cf_resp = await client.get(f"/api/recovery/{run_id}/counterfactual")
        assert cf_resp.status_code == 200
        cf_data = cf_resp.json()
        assert cf_data["run_id"] == run_id
        assert cf_data["restartai_plan"]["total_exposure"] == 13720.0
        assert cf_data["counterfactual_cheapest_first"]["total_exposure"] == 125500.0
        assert cf_data["counterfactual_fastest_single"]["total_exposure"] == 16900.0
