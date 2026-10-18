"""API test for POST /api/evaluate and /api/allocate (needs fastapi + httpx; skipped if missing)."""
import os
import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes_engine  # noqa: E402

app = FastAPI()
app.include_router(routes_engine.router)
client = TestClient(app)

ASSUMP = {"routes": {
    "resale": {"unit_price": 100, "handling_cost_per_unit": 5},
    "refurbish": {"resale_price_after_refurb": 100, "refurbish_cost_per_unit": 20,
                  "handling_cost_per_unit": 5, "success_rate": 1.0},
    "scrap": {"scrap_value_per_unit": 10, "handling_cost_per_unit": 0}}}
LOT = {"lot_id": "L1", "quantity": 10, "category": "electronics", "condition": "good",
       "safety_hold": False, "inspection_confidence": 1.0}


def test_evaluate_reference_values():
    r = client.post("/api/evaluate", json={"lot": LOT, "assumptions": ASSUMP})
    assert r.status_code == 200
    nets = {x["route"]: x["expected_net_recovery"] for x in r.json()["results"]}
    assert nets == {"resale": 950, "refurbish": 750, "scrap": 100}


def test_evaluate_safety_hold_never_recommended():
    r = client.post("/api/evaluate", json={"lot": {**LOT, "safety_hold": True}, "assumptions": ASSUMP})
    assert r.json()["recommended_route"] == "scrap"


def test_allocate_unallocated():
    r = client.post("/api/allocate", json={"lots": [LOT], "assumptions": ASSUMP,
                                           "capacities": {"resale": 0, "refurbish": 0, "scrap": 0}})
    assert r.status_code == 200 and r.json()["unallocated"]
