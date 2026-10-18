"""Engine tests (M1). Reference values 950 / 750 / 100 are fixed by the case; never edit them to pass."""
import copy
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import engine as e  # noqa: E402

ASSUMP = {
    "routes": {
        "resale": {"unit_price": 100, "handling_cost_per_unit": 5, "min_inspection_confidence": 0.0,
                   "allowed_conditions": ["new", "like_new", "good"], "blocked_categories": ["opened_beauty"]},
        "refurbish": {"resale_price_after_refurb": 100, "refurbish_cost_per_unit": 20, "handling_cost_per_unit": 5,
                      "success_rate": 1.0, "min_inspection_confidence": 0.5,
                      "allowed_conditions": ["good", "fair", "damaged"], "blocked_categories": ["opened_beauty"]},
        "scrap": {"scrap_value_per_unit": 10, "handling_cost_per_unit": 0},
    }
}


def lot(**kw):
    base = {"lot_id": "L1", "quantity": 10, "category": "electronics", "condition": "good",
            "safety_hold": False, "inspection_confidence": 1.0}
    base.update(kw)
    return base


def res(lot_, route, cap=None, **kw):
    return e.evaluate_route(lot_, route, ASSUMP, cap, **kw)


# ---- reference cases (10 pts)
def test_resale_950():
    assert res(lot(), "resale").expected_net_recovery == 950


def test_refurbish_750():
    assert res(lot(), "refurbish").expected_net_recovery == 750


def test_scrap_100():
    assert res(lot(), "scrap").expected_net_recovery == 100


def test_components_kept_separate():
    r = res(lot(), "refurbish")
    assert (r.gross_recovery, r.processing_cost, r.handling_cost) == (1000, 200, 50)


def test_original_cost_not_recovered():
    r = res(lot(original_unit_cost=500), "resale")
    assert r.expected_net_recovery == 950


# ---- rejection regardless of profit (10 pts)
def test_safety_hold_blocks_resale_and_refurbish():
    l = lot(safety_hold=True)
    assert not res(l, "resale").eligible and not res(l, "refurbish").eligible
    assert "safety hold" in res(l, "refurbish").reason


def test_unsafe_never_recommended_even_if_most_profitable():
    best = e.best_permitted_route(e.evaluate_all(lot(safety_hold=True), ASSUMP))
    assert best.route == "scrap"


def test_unknown_condition_blocked():
    r = res(lot(condition="unknown"), "resale")
    assert not r.eligible and "unknown" in r.reason


def test_opened_beauty_blocked():
    l = lot(category="opened_beauty")
    assert not res(l, "resale").eligible and not res(l, "refurbish").eligible


def test_capacity_exceeded_rejected_regardless_of_profit():
    r = res(lot(), "resale", cap=9)
    assert not r.eligible and "capacity" in r.reason and r.expected_net_recovery is None


def test_capacity_exact_fit_allowed():
    assert res(lot(), "resale", cap=10).eligible


def test_partial_inspection_unknown_confidence_blocks_refurbish():
    r = res(lot(inspection_confidence=None), "refurbish")
    assert not r.eligible and "incomplete" in r.reason


def test_low_confidence_below_minimum_blocks():
    assert not res(lot(inspection_confidence=0.4), "refurbish").eligible


def test_handling_exceeds_recovery_is_permitted_but_flagged():
    a = copy.deepcopy(ASSUMP)
    a["routes"]["resale"]["handling_cost_per_unit"] = 150
    r = e.evaluate_route(lot(), "resale", a, None)
    assert r.eligible and r.expected_net_recovery < 0 and "loses money" in r.reason


def test_nothing_permitted_returns_none():
    l = lot(category="opened_beauty", safety_hold=True)
    a = copy.deepcopy(ASSUMP)
    a["routes"]["scrap"]["blocked_categories"] = ["opened_beauty"]
    assert e.best_permitted_route(e.evaluate_all(l, a)) is None


# ---- scenarios (5 pts)
def test_confidence_override_changes_net_not_guaranteed():
    r = res(lot(), "resale", confidence_override=0.8)
    assert r.expected_net_recovery == 750 and "not guaranteed" in r.reason


def test_price_multiplier_changes_net():
    assert res(lot(), "resale", price_multiplier=1.2).expected_net_recovery == 1150


def test_scenario_range_brackets_base():
    r = res(lot(inspection_confidence=0.8), "refurbish")
    assert r.scenario_low < r.expected_net_recovery < r.scenario_high


def test_scenario_confidence_clipped_to_one():
    r = res(lot(), "resale")  # conf 1.0: high band cannot exceed 1.0, only price rises
    assert math.isclose(r.scenario_high, 100 * 1.1 * 10 - 50)


def test_scrap_range_collapses():
    r = res(lot(), "scrap")
    assert r.scenario_low == r.scenario_high == 100


# ---- validation
def test_validate_ok():
    assert e.validate_lot(lot()) == []


def test_validate_bad_quantities():
    for q in (0, -3, 2.5, "10", None, True):
        assert e.validate_lot(lot(quantity=q)), q


def test_validate_confidence_range():
    assert e.validate_lot(lot(inspection_confidence=1.2))
    assert e.validate_lot(lot(inspection_confidence=float("nan")))


def test_validate_not_dict():
    assert e.validate_lot(None)


def test_unknown_route_handled_consistently():
    r = res(lot(), "donate")
    assert not r.eligible and "Unknown route" in r.reason


def test_bad_overrides_rejected():
    assert not res(lot(), "resale", confidence_override=1.5).eligible
    assert not res(lot(), "resale", price_multiplier=-1).eligible
    assert not res(lot(), "resale", price_multiplier=float("inf")).eligible


def test_invalid_lot_blocks_all_routes():
    assert all(not r.eligible for r in e.evaluate_all(lot(quantity=-1), ASSUMP))


# ---- best route, tie-break, incremental value
def test_best_is_resale_950():
    assert e.best_permitted_route(e.evaluate_all(lot(), ASSUMP)).route == "resale"


def test_tie_break_deterministic():
    a = [e.RouteResult("scrap", True, "", expected_net_recovery=100.0),
         e.RouteResult("resale", True, "", expected_net_recovery=100.0)]
    assert e.best_permitted_route(a).route == "resale"
    assert e.best_permitted_route(list(reversed(a))).route == "resale"


def test_incremental_value():
    assert e.incremental_value_vs_next_best(e.evaluate_all(lot(), ASSUMP)) == 200


def test_incremental_value_none_when_single_route():
    assert e.incremental_value_vs_next_best(e.evaluate_all(lot(safety_hold=True), ASSUMP)) is None


# ---- JSON safety
def test_to_json_safe_converts_nan_inf():
    r = e.RouteResult("resale", True, "", gross_recovery=float("nan"), expected_net_recovery=float("inf"))
    d = e.to_json_safe(r)
    assert d["gross_recovery"] is None and d["expected_net_recovery"] is None


def test_blocked_result_numbers_are_null_not_zero():
    r = e.to_json_safe(res(lot(safety_hold=True), "resale"))
    assert r["expected_net_recovery"] is None and r["gross_recovery"] is None


# ---- allocator
def test_allocator_basic():
    out = e.allocate_lots([lot()], ASSUMP, {"resale": 100, "refurbish": 100, "scrap": 100})
    assert out["allocations"][0]["route"] == "resale" and out["total_expected_net_recovery"] == 950


def test_allocator_cascades_overflow_to_next_route():
    lots = [lot(lot_id="A"), lot(lot_id="B")]
    out = e.allocate_lots(lots, ASSUMP, {"resale": 10, "refurbish": 100, "scrap": 100})
    routes = {a["lot_id"]: a["route"] for a in out["allocations"]}
    assert sorted(routes.values()) == ["refurbish", "resale"]


def test_allocator_marks_unallocated():
    lots = [lot(lot_id="A"), lot(lot_id="B")]
    out = e.allocate_lots(lots, ASSUMP, {"resale": 10, "refurbish": 0, "scrap": 0})
    assert len(out["allocations"]) == 1 and out["unallocated"][0]["units"] == 10


def test_allocator_does_not_mutate_inputs():
    lots, caps = [lot()], {"resale": 10, "refurbish": 10, "scrap": 10}
    l0, c0 = copy.deepcopy(lots), copy.deepcopy(caps)
    e.allocate_lots(lots, ASSUMP, caps)
    assert lots == l0 and caps == c0


def test_allocator_capacity_not_shared_between_calls():
    caps = {"resale": 10, "refurbish": 0, "scrap": 0}
    first = e.allocate_lots([lot()], ASSUMP, caps)
    second = e.allocate_lots([lot()], ASSUMP, caps)
    assert first["allocations"] and second["allocations"]


def test_allocator_order_is_deterministic():
    lots = [lot(lot_id="B"), lot(lot_id="A")]
    caps = {"resale": 10, "refurbish": 100, "scrap": 100}
    o1 = e.allocate_lots(lots, ASSUMP, caps)
    o2 = e.allocate_lots(list(reversed(lots)), ASSUMP, caps)
    assert [a["lot_id"] for a in o1["allocations"]] == [a["lot_id"] for a in o2["allocations"]]


def test_allocator_invalid_lot_unallocated_not_crash():
    out = e.allocate_lots([lot(quantity=-5)], ASSUMP, {"resale": 10})
    assert out["unallocated"] and not out["allocations"]


def test_allocator_safety_hold_goes_to_scrap():
    out = e.allocate_lots([lot(safety_hold=True)], ASSUMP, {"resale": 99, "refurbish": 99, "scrap": 99})
    assert out["allocations"][0]["route"] == "scrap"


def test_allocator_output_json_safe():
    out = e.to_json_safe(e.allocate_lots([lot()], ASSUMP, {"resale": 10}))
    assert out["capacity_remaining"]["refurbish"] is None  # unknown capacity stays null


# ---- break-even
def test_break_even_refurbish_beats_scrap():
    p = e.break_even_resale_price(lot(), ASSUMP)
    assert p == 35  # (20 refurbish + 5 handling + 10 scrap net) / (success 1.0 x confidence 1.0)
    a = copy.deepcopy(ASSUMP)
    a["routes"]["refurbish"]["resale_price_after_refurb"] = p
    assert math.isclose(e.evaluate_route(lot(), "refurbish", a, None).expected_net_recovery, 100)
