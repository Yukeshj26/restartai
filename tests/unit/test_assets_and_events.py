"""Unit tests for Asset Registry and IoT Fault Event ingestion."""
import pytest
from app.services.asset_service import AssetService
from app.models.models import RecoveryRequest


def test_asset_service_lists_machines():
    service = AssetService()
    machines = service.list_machines()
    assert len(machines) >= 4
    ids = {m["id"] for m in machines}
    assert "cnc-line-4" in ids
    assert "inj-mold-02" in ids
    assert "press-p-12" in ids
    assert "pack-conv-1" in ids


def test_asset_service_get_machine_by_id_and_name():
    service = AssetService()
    # By exact ID
    m1 = service.get_machine("cnc-line-4")
    assert m1 is not None
    assert m1["name"] == "CNC Production Line 4"
    assert m1["downtime_cost_per_hour"] == 5000.0

    # By partial / case-insensitive name
    m2 = service.get_machine("cnc production line 4")
    assert m2 is not None
    assert m2["id"] == "cnc-line-4"

    # Non-existent
    assert service.get_machine("non-existent-machine") is None


def test_asset_service_golden_scenario_request_generation():
    """Verify that the asset registry defaults strictly match the golden scenario invariants."""
    service = AssetService()
    req = service.build_recovery_request("cnc-line-4")

    assert isinstance(req, RecoveryRequest)
    assert req.machine == "CNC Production Line 4"
    assert req.part_number == "SKF 6205-2RS"
    assert req.quantity == 20
    assert req.max_hours == 3.0
    assert req.downtime_cost_per_hour == 5000.0
    assert req.available_technicians == 3
    assert len(req.suppliers) == 4
    assert req.mode == "demo"
    assert req.live_confirmed is False


def test_asset_service_equivalents():
    service = AssetService()
    eqs = service.get_part_equivalents("SKF 6205-2RS")
    assert len(eqs) >= 2
    brands = {e["brand"] for e in eqs}
    assert "FAG" in brands or "NSK" in brands
    # High compatibility confidence
    for e in eqs:
        assert e["compatibility_confidence"] >= 0.90


def test_asset_service_overrides():
    service = AssetService()
    req = service.build_recovery_request("cnc-line-4", overrides={"quantity": 50, "max_hours": 1.5})
    assert req.quantity == 50
    assert req.max_hours == 1.5
    assert req.machine == "CNC Production Line 4"
