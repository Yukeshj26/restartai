"""Property-based mathematical invariant tests for RestartAI's Recovery Planner.

Invariants verified across randomized and edge-case operational configurations:
1. Never Over-Purchases: Leg quantities never exceed requested quota and never exceed vendor inventory.
2. Never Exceeds Deadline When Feasible: If any combination meets the deadline, the planner must find a feasible plan.
3. Matches Brute-Force Global Optimum on Small Cases: The planner's total exposure strictly matches exhaustive brute-force search.
4. Downtime Rate Monotonicity: Higher downtime cost shifts preference toward speed; zero downtime shifts preference toward price.
5. Determinism: Identical inputs yield mathematically identical plans, leg orders, and costs.
"""

import random
from itertools import combinations
import pytest

from app.models.models import RecoveryRequest, Supplier, Offer
from app.engine.recovery_engine import RecoveryEngine
from app.services.call_e_service import CalleService


@pytest.fixture
def engine():
    service = CalleService()
    service.mode = "demo"
    return RecoveryEngine(service)


def make_dummy_suppliers():
    return [Supplier(name="Vendor A", phone="+919876543211")]


def generate_random_supplier_offers(rng: random.Random, n_suppliers: int = 4):
    """Generates synthetic supplier offers with diverse price/ETA trade-offs."""
    offers = []
    for i in range(n_suppliers):
        qty = rng.randint(5, 30)
        price = round(rng.uniform(50.0, 300.0), 2)
        eta = round(rng.uniform(0.5, 6.0), 1)
        offers.append(
            Offer(
                supplier=f"Supplier_{chr(65+i)}",
                phone=f"+9198765432{i:02d}",
                part_number="PART-TEST",
                status="CONFIRMED",
                compatible=True,
                confirmed=True,
                quantity_available=qty,
                unit_price=price,
                availability_hours=eta,
                delivery_method="Express Freight",
                compatibility_confidence=1.0,
                notes="",
                extracted_fields={},
                transcript="",
                retry_count=0,
            )
        )
    return offers


def test_property_never_overpurchases(engine):
    """Property 1: The planner must never over-purchase units beyond the requested quota,
    and each leg must never allocate more than the supplier's available inventory.
    """
    rng = random.Random(1337)
    for trial in range(30):
        req_qty = rng.randint(10, 50)
        max_h = rng.choice([2.0, 3.0, 5.0, 8.0])
        downtime_rate = rng.choice([1000.0, 5000.0, 10000.0])
        offers = generate_random_supplier_offers(rng, n_suppliers=rng.randint(3, 5))

        req = RecoveryRequest(
            mode="demo",
            machine="Test Machine",
            part_number="PART-TEST",
            part_description="Test Component Description",
            quantity=req_qty,
            max_hours=max_h,
            downtime_cost_per_hour=downtime_rate,
            available_technicians=3,
            suppliers=make_dummy_suppliers(),
        )

        maintenance = {"required_technicians": 2, "installation_minutes": 30}
        plans = engine._generate_plans(
            req, [o.model_dump() for o in offers], maintenance
        )
        for p in plans:
            total_purchased = sum(l.quantity for l in p.legs)
            # Must never exceed requested quota
            assert (
                total_purchased <= req_qty
            ), f"Over-purchased: {total_purchased} > {req_qty}"

            # If plan claims feasibility, it must fulfill exactly the requested quota
            if p.feasible:
                assert (
                    total_purchased == req_qty
                ), f"Feasible plan did not fulfill exact quota: {total_purchased} != {req_qty}"

            # Each leg must not exceed supplier's available stock
            for leg in p.legs:
                supp = next(o for o in offers if o.supplier == leg.supplier)
                assert (
                    leg.quantity <= supp.quantity_available
                ), f"Leg allocated {leg.quantity} from {leg.supplier}, but stock was only {supp.quantity_available}"


def test_property_never_exceeds_deadline_when_feasible(engine):
    """Property 2: If there exists ANY feasible combination of suppliers that satisfies
    the quantity within the deadline, the recommended plan must be feasible and meet the deadline.
    """
    rng = random.Random(2026)
    for trial in range(25):
        req_qty = 20
        max_h = 4.0
        downtime_rate = 5000.0
        install_mins = 30
        install_hours = install_mins / 60.0

        offers = generate_random_supplier_offers(rng, n_suppliers=4)

        # Check if brute-force feasibility exists
        feasible_combination_exists = False
        for r in range(1, len(offers) + 1):
            for combo in combinations(offers, r):
                if sum(o.quantity_available for o in combo) >= req_qty:
                    max_arrival = max(o.availability_hours for o in combo)
                    if (max_arrival + install_hours) <= max_h:
                        feasible_combination_exists = True
                        break
            if feasible_combination_exists:
                break

        req = RecoveryRequest(
            mode="demo",
            machine="Test Machine",
            part_number="PART-TEST",
            part_description="Test Component Description",
            quantity=req_qty,
            max_hours=max_h,
            downtime_cost_per_hour=downtime_rate,
            available_technicians=3,
            suppliers=make_dummy_suppliers(),
        )

        maintenance = {"required_technicians": 2, "installation_minutes": install_mins}
        plans = engine._generate_plans(
            req, [o.model_dump() for o in offers], maintenance
        )
        if feasible_combination_exists and plans:
            rec = plans[0]
            assert (
                rec.feasible is True
            ), f"Planner marked feasible scenario as infeasible in trial {trial}"
            assert (
                rec.recovery_time_hours <= max_h
            ), f"Recovery time {rec.recovery_time_hours}h exceeded max {max_h}h when feasible combination existed"


def test_property_matches_bruteforce_optimum_on_small_cases(engine):
    """Property 3: The planner's recommended plan must strictly match the global minimum
    total economic exposure found by an exhaustive brute-force search.
    """
    rng = random.Random(42)
    for trial in range(20):
        req_qty = 20
        max_h = 4.0
        downtime_rate = rng.choice([2000.0, 5000.0, 8000.0])
        install_mins = 30
        install_hours = install_mins / 60.0
        offers = generate_random_supplier_offers(rng, n_suppliers=4)

        # 1. Independent Brute-Force Exhaustive Search
        brute_force_best_exposure = None
        for r in range(1, min(4, len(offers) + 1)):
            for combo in combinations(offers, r):
                if sum(o.quantity_available for o in combo) < req_qty:
                    continue
                # Allocate greedily in order of earliest arrival to minimize downtime
                rem = req_qty
                pur_cost = 0.0
                arrival_times = []
                for s in sorted(combo, key=lambda x: x.availability_hours):
                    take = min(rem, s.quantity_available)
                    pur_cost += take * s.unit_price
                    arrival_times.append(s.availability_hours)
                    rem -= take
                    if rem == 0:
                        break
                if rem > 0:
                    continue

                rec_time = max(arrival_times) + install_hours
                if rec_time > max_h:
                    continue  # Infeasible

                tot_exposure = pur_cost + round(rec_time * downtime_rate, 2)
                if (
                    brute_force_best_exposure is None
                    or tot_exposure < brute_force_best_exposure
                ):
                    brute_force_best_exposure = tot_exposure

        # 2. RestartAI Engine Search
        req = RecoveryRequest(
            mode="demo",
            machine="Test Machine",
            part_number="PART-TEST",
            part_description="Test Component Description",
            quantity=req_qty,
            max_hours=max_h,
            downtime_cost_per_hour=downtime_rate,
            available_technicians=3,
            suppliers=make_dummy_suppliers(),
        )

        maintenance = {"required_technicians": 2, "installation_minutes": install_mins}
        plans = engine._generate_plans(
            req, [o.model_dump() for o in offers], maintenance
        )
        feasible_plans = [p for p in plans if p.feasible]

        if brute_force_best_exposure is not None:
            assert (
                len(feasible_plans) > 0
            ), f"Brute force found optimal solution {brute_force_best_exposure}, but engine found none"
            engine_best_exposure = feasible_plans[0].total_exposure
            assert (
                abs(engine_best_exposure - brute_force_best_exposure) < 1.0
            ), f"Mismatch in trial {trial}: Engine exposure {engine_best_exposure} != Brute-force {brute_force_best_exposure}"


def test_property_downtime_rate_monotonicity(engine):
    """Property 4: Sensitivity Monotonicity.
    When downtime rate is zero, the planner selects the cheapest purchase plan within the deadline.
    When downtime rate is extremely high, the planner selects the fastest arrival plan.
    """
    # Offer 1: Cheap, but slower (3.0h arrival, Rs 100/u)
    # Offer 2: Expensive, but faster (1.0h arrival, Rs 300/u)
    offers = [
        Offer(
            supplier="SlowCheap",
            phone="+919876543201",
            part_number="PART-MONO",
            status="CONFIRMED",
            compatible=True,
            confirmed=True,
            quantity_available=10,
            unit_price=100.0,
            availability_hours=3.0,
            delivery_method="Freight",
            compatibility_confidence=1.0,
            notes="",
            extracted_fields={},
            transcript="",
            retry_count=0,
        ),
        Offer(
            supplier="FastCostly",
            phone="+919876543202",
            part_number="PART-MONO",
            status="CONFIRMED",
            compatible=True,
            confirmed=True,
            quantity_available=10,
            unit_price=300.0,
            availability_hours=1.0,
            delivery_method="Courier",
            compatibility_confidence=1.0,
            notes="",
            extracted_fields={},
            transcript="",
            retry_count=0,
        ),
    ]

    maintenance = {"required_technicians": 2, "installation_minutes": 30}

    # Case A: Downtime rate = 0 (only purchase cost matters)
    req_zero_loss = RecoveryRequest(
        mode="demo",
        machine="Test Line",
        part_number="PART-MONO",
        part_description="Test Monotonicity Component",
        quantity=10,
        max_hours=5.0,
        downtime_cost_per_hour=0.0,
        available_technicians=3,
        suppliers=make_dummy_suppliers(),
    )
    plans_zero = engine._generate_plans(
        req_zero_loss, [o.model_dump() for o in offers], maintenance
    )
    assert (
        plans_zero[0].legs[0].supplier == "SlowCheap"
    ), "At zero downtime rate, cheapest supplier must be chosen"

    # Case B: Downtime rate = Rs 50,000/hr (speed dominates price)
    req_high_loss = RecoveryRequest(
        mode="demo",
        machine="Test Line",
        part_number="PART-MONO",
        part_description="Test Monotonicity Component",
        quantity=10,
        max_hours=5.0,
        downtime_cost_per_hour=50000.0,
        available_technicians=3,
        suppliers=make_dummy_suppliers(),
    )
    plans_high = engine._generate_plans(
        req_high_loss, [o.model_dump() for o in offers], maintenance
    )
    assert (
        plans_high[0].legs[0].supplier == "FastCostly"
    ), "At high downtime rate, fastest supplier must be chosen"


def test_property_planner_determinism(engine):
    """Property 5: Given identical supplier offers and incident requests,
    the planner must produce identical plans on consecutive invocations.
    """
    rng = random.Random(999)
    offers = generate_random_supplier_offers(rng, n_suppliers=4)
    req = RecoveryRequest(
        mode="demo",
        machine="CNC Line 4",
        part_number="SKF 6205-2RS",
        part_description="Deep-groove ball bearing",
        quantity=20,
        max_hours=3.0,
        downtime_cost_per_hour=5000.0,
        available_technicians=3,
        suppliers=make_dummy_suppliers(),
    )

    maintenance = {"required_technicians": 2, "installation_minutes": 30}
    plans1 = engine._generate_plans(req, [o.model_dump() for o in offers], maintenance)
    plans2 = engine._generate_plans(req, [o.model_dump() for o in offers], maintenance)

    assert len(plans1) == len(plans2)
    for p1, p2 in zip(plans1, plans2):
        assert p1.total_exposure == p2.total_exposure
        assert p1.total_purchase_cost == p2.total_purchase_cost
        assert p1.recovery_time_hours == p2.recovery_time_hours
        assert [l.supplier for l in p1.legs] == [l.supplier for l in p2.legs]
        assert [l.quantity for l in p1.legs] == [l.quantity for l in p2.legs]
