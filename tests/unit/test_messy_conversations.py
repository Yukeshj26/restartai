"""Unit tests for Phase 3: Messy supplier conversations, extraction quotes, and chaos scenarios."""

import pytest
from app.services.call_e_service import CalleService
from app.engine.recovery_engine import RecoveryEngine, RUNS, IDEMPOTENCY
from app.models.models import RecoveryRequest, Supplier, OfferStatus


@pytest.fixture(autouse=True)
def clean_state():
    RUNS.clear()
    IDEMPOTENCY.clear()
    yield
    RUNS.clear()
    IDEMPOTENCY.clear()


def make_request(chaos_scenario="standard", **kwargs):
    base = dict(
        mode="demo",
        chaos_scenario=chaos_scenario,
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
    base.update(kwargs)
    return RecoveryRequest(**base)


def test_standard_scenario_offers_contain_transcripts_and_source_quotes():
    """Verify that all standard demo offers contain transcripts and extracted source quotes."""
    calle = CalleService()
    engine = RecoveryEngine(calle)
    req = make_request("standard")

    snap = engine.start(req)
    snap = engine.replan(snap["run_id"])

    assert len(snap["offers"]) == 4
    for o in snap["offers"]:
        assert o["status"] == "CONFIRMED"
        assert o["confirmed"] is True
        assert len(o["transcript"]) > 20, f"Offer {o['supplier']} missing transcript"
        assert (
            len(o["extracted_fields"]) > 0
        ), f"Offer {o['supplier']} missing extracted_fields"
        for field_name, extraction in o["extracted_fields"].items():
            assert (
                "source_quote" in extraction
            ), f"Field {field_name} missing source_quote"
            assert "confidence" in extraction, f"Field {field_name} missing confidence"
            assert (
                extraction["confidence"] >= 0.90
            ), f"Field {field_name} low confidence"


def test_chaos_scenario_supplier_unsure_marks_tentative():
    """Chaos: Supplier A is tentative ('maybe tomorrow, let me check'). Must not be confirmed."""
    calle = CalleService()
    engine = RecoveryEngine(calle)
    req = make_request("supplier_unsure")

    snap = engine.start(req)
    snap = engine.replan(snap["run_id"])

    offers_by_name = {o["supplier"]: o for o in snap["offers"]}
    a = offers_by_name["Supplier A"]
    assert a["status"] == OfferStatus.TENTATIVE.value
    assert a["confirmed"] is False
    assert "warehouse supervisor" in a["transcript"].lower()
    assert a["extracted_fields"]["status"]["value"] == "TENTATIVE"

    # Plan should still find feasible C + D because A was unconfirmed
    assert snap["recommended_plan"] is not None
    assert snap["recommended_plan"]["feasible"] is True


def test_chaos_scenario_midcall_quantity_shift():
    """Chaos: Supplier C starts with 16 then discovers only 8 are available."""
    calle = CalleService()
    engine = RecoveryEngine(calle)
    req = make_request("midcall_quantity_shift")

    snap = engine.start(req)
    snap = engine.replan(snap["run_id"])

    offers_by_name = {o["supplier"]: o for o in snap["offers"]}
    c = offers_by_name["Supplier C"]
    assert c["quantity_available"] == 8
    assert "8 are on hold" in c["transcript"]
    assert "mid-call" in c["notes"].lower()


def test_chaos_scenario_no_answer_retries_and_escalates():
    """Chaos: Supplier A does not answer. Python auto-retries and escalates."""
    calle = CalleService()
    engine = RecoveryEngine(calle)
    req = make_request("no_answer")

    snap = engine.start(req)
    snap = engine.replan(snap["run_id"])

    offers_by_name = {o["supplier"]: o for o in snap["offers"]}
    a = offers_by_name["Supplier A"]
    assert a["status"] == OfferStatus.NO_ANSWER.value
    assert a["confirmed"] is False
    assert a["retry_count"] == 1
    assert "timeout" in a["transcript"].lower()

    # Engine escalated and still resolved recovery through B or C+D
    assert snap["recommended_plan"] is not None
    assert snap["recommended_plan"]["feasible"] is True


def test_chaos_scenario_price_revised_upward():
    """Chaos: Supplier B raises price from 220 to 340 mid-call."""
    calle = CalleService()
    engine = RecoveryEngine(calle)
    req = make_request("price_revised_upward")

    snap = engine.start(req)
    snap = engine.replan(snap["run_id"])

    offers_by_name = {o["supplier"]: o for o in snap["offers"]}
    b = offers_by_name["Supplier B"]
    assert b["unit_price"] == 340.0
    assert "surcharge" in b["notes"].lower()
    assert b["extracted_fields"]["unit_price"]["value"] == 340.0


def test_chaos_scenario_callback_promised():
    """Chaos: Supplier A promises callback in 45m; unconfirmed."""
    calle = CalleService()
    engine = RecoveryEngine(calle)
    req = make_request("callback_promised")

    snap = engine.start(req)
    snap = engine.replan(snap["run_id"])

    offers_by_name = {o["supplier"]: o for o in snap["offers"]}
    a = offers_by_name["Supplier A"]
    assert a["status"] == OfferStatus.CALLBACK_PROMISED.value
    assert a["confirmed"] is False
    assert "lunch" in a["transcript"].lower()


def test_tentative_and_unconfirmed_offers_never_enter_plans():
    """Invariant: An offer that is tentative or unconfirmed is never allocated to a recovery plan."""
    calle = CalleService()
    engine = RecoveryEngine(calle)
    # Only supply an unconfirmed tentative supplier
    req = make_request(
        "supplier_unsure",
        suppliers=[Supplier(name="Supplier A", phone="+919876543211")],
    )

    snap = engine.start(req)
    snap = engine.replan(snap["run_id"])

    assert snap["recommended_plan"] is None
