"""ReCoverIQ recovery engine (M1).

Pure Python: no FastAPI, no UI imports. All money is INR per the fixture.
Rules, in order, for every route:
  1. Validate inputs.  2. Eligibility and safety.  3. Capacity.  4. Only then, money.
An ineligible route is never recommended, whatever its profit.
None means UNKNOWN, never zero. No NaN/Infinity leaves this module via to_json_safe.
"""
from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

ROUTES = ("resale", "refurbish", "scrap")
# Deterministic tie-break: when nets are equal, earlier in this tuple wins.
ROUTE_PRIORITY = {"resale": 0, "refurbish": 1, "scrap": 2}

PRICE_BAND = 0.10        # scenario price +/-10%
CONFIDENCE_BAND = 0.15   # scenario confidence +/-0.15, clipped to [0, 1]
UNALLOCATED = "Unallocated"


@dataclass
class RouteResult:
    route: str
    eligible: bool
    reason: str
    gross_recovery: Optional[float] = None
    processing_cost: Optional[float] = None
    handling_cost: Optional[float] = None
    expected_net_recovery: Optional[float] = None
    scenario_low: Optional[float] = None
    scenario_high: Optional[float] = None


# ---------------------------------------------------------------- validation
def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_lot(lot: Any) -> list[str]:
    """Return a list of plain-language problems; empty list means usable."""
    if not isinstance(lot, dict):
        return ["Lot must be an object."]
    problems: list[str] = []
    if not lot.get("lot_id"):
        problems.append("lot_id is required.")
    q = lot.get("quantity")
    if not (isinstance(q, int) and not isinstance(q, bool)) or q <= 0:
        if isinstance(q, float) and math.isfinite(q) and q > 0 and q == int(q):
            pass  # 10.0 from JSON/CSV is a whole number
        else:
            problems.append("quantity must be a positive whole number.")
    for field_name in ("category", "condition"):
        v = lot.get(field_name)
        if not isinstance(v, str) or not v.strip():
            problems.append(f"{field_name} is required.")
    if not isinstance(lot.get("safety_hold", False), bool):
        problems.append("safety_hold must be true or false.")
    c = lot.get("inspection_confidence")
    if c is not None and (not _is_num(c) or not 0 <= c <= 1):
        problems.append("inspection_confidence must be between 0 and 1, or null if unknown.")
    return problems


def _validate_route_inputs(route: str, assumptions: dict, confidence_override, price_multiplier):
    if route not in ROUTES:
        return f"Unknown route '{route}'. Use resale, refurbish or scrap."
    if confidence_override is not None and (not _is_num(confidence_override) or not 0 <= confidence_override <= 1):
        return "confidence_override must be between 0 and 1."
    if not _is_num(price_multiplier) or price_multiplier < 0:
        return "price_multiplier must be a finite number that is not negative."
    return None


def _blocked(route: str, reason: str) -> RouteResult:
    return RouteResult(route=route, eligible=False, reason=reason)


# ------------------------------------------------------------------ economics
def _route_money(lot: dict, route: str, a: dict, confidence: float, price_mult: float):
    """Return (gross, processing, handling, net) per whole lot. Original cost is sunk: never added back."""
    qty = int(lot["quantity"])
    cfg = a["routes"][route]
    handling = cfg["handling_cost_per_unit"] * qty
    if route == "resale":
        gross = cfg["unit_price"] * price_mult * qty * confidence
        processing = 0.0
    elif route == "refurbish":
        success = cfg.get("success_rate", 1.0)
        gross = cfg["resale_price_after_refurb"] * price_mult * qty * success * confidence
        processing = cfg["refurbish_cost_per_unit"] * qty
    else:  # scrap
        gross = cfg["scrap_value_per_unit"] * qty
        processing = 0.0
    return gross, processing, handling, gross - processing - handling


def _effective_confidence(lot: dict, override):
    if override is not None:
        return override
    c = lot.get("inspection_confidence")
    return 1.0 if c is None else c  # None only reaches here for routes that do not require it


def evaluate_route(
    lot: dict,
    route: str,
    assumptions: dict,
    capacity_remaining: Optional[float],
    confidence_override: Optional[float] = None,
    price_multiplier: float = 1.0,
) -> RouteResult:
    """Evaluate one route for one lot. capacity_remaining=None means capacity unknown/unchecked."""
    err = _validate_route_inputs(route, assumptions, confidence_override, price_multiplier)
    if err:
        return _blocked(route, err)
    problems = validate_lot(lot)
    if problems:
        return _blocked(route, "Lot data invalid: " + " ".join(problems))

    cfg = assumptions.get("routes", {}).get(route)
    if cfg is None:
        return _blocked(route, f"No assumptions defined for {route}.")
    label = route.capitalize()
    qty = int(lot["quantity"])

    # --- eligibility and safety, before any profit maths ---
    if lot.get("safety_hold") and route != "scrap":
        return _blocked(route, f"{label} blocked: safety hold on this lot.")
    if str(lot["condition"]).lower() == "unknown" and route != "scrap":
        return _blocked(route, f"{label} blocked: condition is unknown, inspect before choosing this route.")
    if str(lot["category"]).lower() in {c.lower() for c in cfg.get("blocked_categories", [])}:
        return _blocked(route, f"{label} blocked: category '{lot['category']}' is not permitted for this route.")
    allowed = cfg.get("allowed_conditions")
    if allowed is not None and str(lot["condition"]).lower() not in {c.lower() for c in allowed}:
        return _blocked(route, f"{label} blocked: condition '{lot['condition']}' is not permitted for this route.")
    # Unknown confidence is never silently treated as 100%: routes whose recovery depends on
    # confidence (resale, refurbish) are blocked until inspection is complete or a what-if is supplied.
    if route != "scrap" and lot.get("inspection_confidence") is None and confidence_override is None:
        return _blocked(
            route,
            f"{label} blocked: inspection is incomplete (confidence unknown). "
            "Complete the inspection, or set a what-if confidence to explore it.",
        )
    min_conf = cfg.get("min_inspection_confidence", 0.0)
    if min_conf > 0:
        conf_check = _effective_confidence(lot, confidence_override)
        if conf_check < min_conf:
            return _blocked(route, f"{label} blocked: inspection confidence {conf_check:.2f} is below the required {min_conf:.2f}.")
    if capacity_remaining is not None and qty > capacity_remaining:
        return _blocked(route, f"{label} blocked: {qty} units exceed remaining capacity of {capacity_remaining:g}.")

    # --- money ---
    conf = _effective_confidence(lot, confidence_override)
    gross, proc, hand, net = _route_money(lot, route, assumptions, conf, price_multiplier)
    lo_conf = max(0.0, conf - CONFIDENCE_BAND)
    hi_conf = min(1.0, conf + CONFIDENCE_BAND)
    low = _route_money(lot, route, assumptions, lo_conf, price_multiplier * (1 - PRICE_BAND))[3]
    high = _route_money(lot, route, assumptions, hi_conf, price_multiplier * (1 + PRICE_BAND))[3]
    if route == "scrap":  # scrap value does not depend on price or confidence
        low = high = net
    if net < 0:
        reason = f"{label} permitted but loses money: handling and processing exceed recovery."
    else:
        reason = f"{label} permitted: expected net recovery is a scenario, not guaranteed."
    return RouteResult(route, True, reason, gross, proc, hand, net, min(low, high), max(low, high))


def evaluate_all(lot, assumptions, capacities=None, confidence_override=None, price_multiplier=1.0) -> list[RouteResult]:
    capacities = capacities or {}
    return [
        evaluate_route(lot, r, assumptions, capacities.get(r), confidence_override, price_multiplier)
        for r in ROUTES
    ]


def best_permitted_route(results: list[RouteResult]) -> Optional[RouteResult]:
    """Highest expected net among eligible routes with a known net and non-negative value; None if nothing permitted.

    A permitted route that loses money is still permitted; it is only returned if every permitted route loses,
    in which case the least-bad one is returned so the manager sees the real choice.
    """
    ok = [r for r in results if r.eligible and r.expected_net_recovery is not None]
    if not ok:
        return None
    return sorted(ok, key=lambda r: (-r.expected_net_recovery, ROUTE_PRIORITY.get(r.route, 99)))[0]


def incremental_value_vs_next_best(results: list[RouteResult]) -> Optional[float]:
    """Net of the best permitted route minus the next best permitted route. None if fewer than two permitted."""
    ok = sorted(
        (r for r in results if r.eligible and r.expected_net_recovery is not None),
        key=lambda r: (-r.expected_net_recovery, ROUTE_PRIORITY.get(r.route, 99)),
    )
    if len(ok) < 2:
        return None
    return ok[0].expected_net_recovery - ok[1].expected_net_recovery


# ------------------------------------------------------------------ allocator
def allocate_lots(lots: list[dict], assumptions: dict, capacities: dict[str, float]) -> dict:
    """Capacity-aware allocation. Order: lots sorted by best net per unit (desc), then lot_id.

    Each lot goes whole to its best permitted route with capacity left; if that route is full,
    it cascades to the next permitted route; if none fits it is marked Unallocated.
    Inputs are never mutated and capacity state is local to this call.
    """
    cap = {r: capacities.get(r) for r in ROUTES}  # local copy
    lots = copy.deepcopy(lots)

    def per_unit(lot):
        if validate_lot(lot):
            return float("-inf")
        best = best_permitted_route(evaluate_all(lot, assumptions, {}))  # ignore capacity for ordering
        if best is None or best.expected_net_recovery is None:
            return float("-inf")
        return best.expected_net_recovery / int(lot["quantity"])

    ordered = sorted(lots, key=lambda l: (-per_unit(l), str(l.get("lot_id", ""))))
    allocations, unallocated, total = [], [], 0.0
    for lot in ordered:
        problems = validate_lot(lot)
        if problems:
            unallocated.append({"lot_id": lot.get("lot_id"), "units": lot.get("quantity"),
                                "reason": "Lot data invalid: " + " ".join(problems)})
            continue
        results = evaluate_all(lot, assumptions, cap)
        best = best_permitted_route(results)
        if best is None:
            unallocated.append({"lot_id": lot["lot_id"], "units": int(lot["quantity"]),
                                "reason": "No permitted route with available capacity.",
                                "results": [asdict(r) for r in results]})
            continue
        if cap[best.route] is not None:
            cap[best.route] -= int(lot["quantity"])
        total += best.expected_net_recovery
        allocations.append({"lot_id": lot["lot_id"], "units": int(lot["quantity"]),
                            "route": best.route, "result": asdict(best),
                            "all_results": [asdict(r) for r in results]})
    return {"allocations": allocations, "unallocated": unallocated,
            "total_expected_net_recovery": total,
            "capacity_remaining": cap, "label": "Scenario, not guaranteed"}


# ------------------------------------------------------------------ JSON safety
def _clean(x: Any) -> Any:
    if isinstance(x, RouteResult):  # also when nested inside dicts or lists
        x = asdict(x)
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def to_json_safe(obj: Any) -> Any:
    """Convert a RouteResult (or any nested structure) to plain JSON data; NaN/inf become None."""
    if isinstance(obj, RouteResult):
        obj = asdict(obj)
    return _clean(obj)


def break_even_resale_price(lot: dict, assumptions: dict, confidence_override=None) -> Optional[float]:
    """Post-refurbishment resale unit price at which refurbish net equals scrap net (Scenario Lab chart).

    Above this price refurbish beats scrap. Returns None if it cannot be computed.
    """
    r = assumptions.get("routes", {}).get("refurbish")
    s = assumptions.get("routes", {}).get("scrap")
    if not r or not s or validate_lot(lot):
        return None
    if lot.get("inspection_confidence") is None and confidence_override is None:
        return None  # confidence unknown: no break-even rather than assuming 100%
    conf = _effective_confidence(lot, confidence_override)
    success = r.get("success_rate", 1.0)
    denom = success * conf
    if denom <= 0:
        return None
    qty_unit_cost = r["refurbish_cost_per_unit"] + r["handling_cost_per_unit"]
    scrap_net = s["scrap_value_per_unit"] - s["handling_cost_per_unit"]
    return (qty_unit_cost + scrap_net) / denom
