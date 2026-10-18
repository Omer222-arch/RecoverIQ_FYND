"""FastAPI adapter for Member 1's recovery engine. Engine logic remains in engine.py."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import engine as e

router = APIRouter()

DEFAULT_ASSUMPTIONS = {
    "routes": {
        "resale": {"unit_price": 100, "handling_cost_per_unit": 5, "min_inspection_confidence": 0.0,
                   "allowed_conditions": ["new", "like_new", "good"], "blocked_categories": ["opened_beauty"]},
        "refurbish": {"resale_price_after_refurb": 100, "refurbish_cost_per_unit": 20,
                      "handling_cost_per_unit": 5, "success_rate": 1.0, "min_inspection_confidence": 0.5,
                      "allowed_conditions": ["good", "fair", "damaged"], "blocked_categories": ["opened_beauty"]},
        "scrap": {"scrap_value_per_unit": 10, "handling_cost_per_unit": 0},
    }
}

class EvaluateRequest(BaseModel):
    lot: dict[str, Any]
    assumptions: dict[str, Any] | None = None
    capacities: dict[str, float] | None = None
    confidence_override: float | None = Field(default=None, ge=0, le=1)
    price_multiplier: float = Field(default=1.0, ge=0, le=1000)

class AllocateRequest(BaseModel):
    lots: list[dict[str, Any]]
    assumptions: dict[str, Any] | None = None
    capacities: dict[str, float | None] = Field(default_factory=dict)

@router.post("/api/evaluate")
def evaluate(req: EvaluateRequest):
    assumptions = req.assumptions or DEFAULT_ASSUMPTIONS
    problems = e.validate_lot(req.lot)
    results = e.evaluate_all(req.lot, assumptions, req.capacities,
                             req.confidence_override, req.price_multiplier)
    best = e.best_permitted_route(results)
    return e.to_json_safe({
        "lot_id": req.lot.get("lot_id"),
        "lot_problems": problems,
        "results": results,
        "recommended_route": best.route if best else None,
        "incremental_value_vs_next_best": e.incremental_value_vs_next_best(results),
        "break_even_refurbish_vs_scrap_unit_price": e.break_even_resale_price(
            req.lot, assumptions, req.confidence_override),
        "label": "Synthetic teaching scenario — not a guaranteed outcome",
    })

@router.post("/api/allocate")
def allocate(req: AllocateRequest):
    assumptions = req.assumptions or DEFAULT_ASSUMPTIONS
    capacities = {k: v for k, v in req.capacities.items() if v is not None}
    return e.to_json_safe(e.allocate_lots(req.lots, assumptions, capacities))
