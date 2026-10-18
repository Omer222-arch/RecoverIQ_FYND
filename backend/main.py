
"""ReCoverIQ API: recovery engine, central inventory dataset, proposals and outcomes."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from recovery_advisor import router as recovery_advisor_router
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

# Support both:
#   uvicorn main:app --reload       (from backend/)
#   uvicorn backend.main:app --reload (from project root)
try:
    from routes_engine import router as engine_router
    from validation import validate_lots
    from proposals import (
        list_proposals,
        create_proposal,
        update_proposal_status,
        delete_proposal,
    )
    from outcomes import (
        list_outcomes,
        create_outcome,
        calculate_variance,
        delete_outcome,
    )
except ImportError:
    from backend.routes_engine import router as engine_router
    from backend.validation import validate_lots
    from backend.proposals import (
        list_proposals,
        create_proposal,
        update_proposal_status,
        delete_proposal,
    )
    from backend.outcomes import (
        list_outcomes,
        create_outcome,
        calculate_variance,
        delete_outcome,
    )


app = FastAPI(
    title="ReCoverIQ API",
    description=(
        "Central inventory dataset, recovery engine, proposals, "
        "and realized recovery outcomes."
    ),
    version="1.3.0",
)
# Keep origins exact and configurable for each frontend deployment.
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
] or DEFAULT_ALLOWED_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(engine_router)
app.include_router(recovery_advisor_router)

DATA_DIR = Path(__file__).resolve().parent / "data"
LOTS_FILE = DATA_DIR / "lots.json"
METADATA_FILE = DATA_DIR / "dataset_metadata.json"

# These locks protect file operations within this Python process.
LOTS_LOCK = Lock()
METADATA_LOCK = Lock()


class LotsInput(BaseModel):
    lots: list[dict[str, Any]]


class DatasetImportInput(BaseModel):
    filename: str = Field(default="Uploaded dataset", min_length=1, max_length=255)
    lots: list[dict[str, Any]]


class ProposalInput(BaseModel):
    lot_id: str
    proposed_route: Literal["refurbish", "resale", "scrap"]
    status: Literal["draft", "pending_review", "approved", "rejected"] = "draft"
    expected_recovery_inr: float | None = Field(default=None, ge=0)
    notes: str | None = None


class ProposalStatusInput(BaseModel):
    status: Literal["draft", "pending_review", "approved", "rejected"]


class OutcomeInput(BaseModel):
    proposal_id: str
    actual_recovery_inr: float | None = Field(default=None, ge=0)
    notes: str | None = None


def utc_now() -> str:
    """Return a timezone-aware ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, value: Any, lock: Lock) -> None:
    """Write JSON atomically so a partial write does not replace saved data."""
    ensure_data_dir()
    temp_path = path.with_suffix(path.suffix + ".tmp")

    try:
        with lock:
            temp_path.write_text(
                json.dumps(value, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temp_path, path)
    except OSError as exc:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Unable to save {path.name}.",
        ) from exc


def read_json_file(path: Path, default: Any, lock: Lock) -> Any:
    if not path.exists():
        return default

    try:
        with lock:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to read saved file {path.name}.",
        ) from exc


def read_metadata() -> dict[str, Any] | None:
    metadata = read_json_file(METADATA_FILE, None, METADATA_LOCK)
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        raise HTTPException(
            status_code=500,
            detail="Saved dataset metadata is invalid.",
        )
    return metadata


def validate_and_normalize_lots(lots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use the existing project validator as the source of truth."""
    try:
        result = validate_lots(lots)
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Dataset validation failed: {exc}",
        ) from exc

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail="The dataset validator returned an unexpected response.",
        )

    if not result.get("valid", False):
        raise HTTPException(status_code=422, detail=result.get("issues", []))

    normalized = result.get("lots")
    if not isinstance(normalized, list):
        raise HTTPException(
            status_code=500,
            detail="The validator did not return a normalized lots array.",
        )

    return normalized


def read_lots() -> list[dict[str, Any]]:
    """Read and validate the active inventory dataset."""
    raw_lots = read_json_file(LOTS_FILE, [], LOTS_LOCK)

    if not isinstance(raw_lots, list):
        raise HTTPException(
            status_code=500,
            detail="Stored lots must be a JSON array.",
        )

    if not raw_lots:
        return []

    return validate_and_normalize_lots(raw_lots)


def write_lots(
    lots: list[dict[str, Any]],
    *,
    filename: str = "API update",
    update_metadata: bool = True,
) -> list[dict[str, Any]]:
    """Validate and persist lots, replacing the currently active dataset."""
    normalized = validate_and_normalize_lots(lots)

    # Persist the new inventory first. If validation fails, the previous
    # dataset remains untouched.
    atomic_write_json(LOTS_FILE, normalized, LOTS_LOCK)

    if update_metadata:
        previous = read_metadata() or {}
        metadata = {
            "dataset_id": str(uuid4()),
            "filename": filename,
            "imported_at": utc_now(),
            "record_count": len(normalized),
            "version": int(previous.get("version", 0)) + 1,
        }
        atomic_write_json(METADATA_FILE, metadata, METADATA_LOCK)

    return normalized


def first_value(
    record: dict[str, Any],
    keys: tuple[str, ...],
) -> Any:
    """Return the first populated value from a set of possible field names."""
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def numeric_value(value: Any) -> float:
    """Parse a number from common JSON or formatted currency values."""
    if value is None or isinstance(value, bool):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        cleaned = (
            value.strip()
            .replace(",", "")
            .replace("₹", "")
            .replace("INR", "")
            .replace("inr", "")
            .replace("%", "")
            .strip()
        )
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    return 0.0


def calculate_dataset_summary(lots: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Calculate summary metrics from active imported records.

    Field aliases are deliberately tolerant. Unknown or missing values are
    not fabricated; they contribute zero or remain unclassified.
    """
    total_lots = len(lots)
    total_units = 0.0
    inspected_units = 0.0
    passed_units = 0.0
    failed_units = 0.0
    pending_units = 0.0
    inventory_value = 0.0
    has_inventory_value = False
    status_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}

    quantity_keys = (
        "units", "quantity", "qty", "unit_count",
        "total_units", "quantity_units",
    )
    status_keys = (
        "inspection_status", "inspection_result", "status",
        "condition_status", "inspection",
    )
    category_keys = (
        "category", "product_category", "type", "product_type",
    )
    total_value_keys = (
        "total_value_inr", "inventory_value_inr", "total_value",
        "inventory_value", "total_inventory_value", "value_inr",
    )
    unit_value_keys = (
        "unit_value_inr", "unit_price_inr", "unit_value",
        "unit_price", "price_per_unit", "price", "resale_price_inr",
    )

    for lot in lots:
        quantity = max(
            0.0,
            numeric_value(first_value(lot, quantity_keys)),
        )
        total_units += quantity

        raw_status = first_value(lot, status_keys)
        status = str(raw_status or "pending").strip().lower()
        status = status.replace("-", "_").replace(" ", "_")

        if any(word in status for word in ("pass", "passed", "approved", "good")):
            passed_units += quantity
            inspected_units += quantity
            normalized_status = "passed"
        elif any(word in status for word in ("fail", "failed", "reject", "defect")):
            failed_units += quantity
            inspected_units += quantity
            normalized_status = "failed"
        elif any(word in status for word in ("pending", "unknown", "not_inspected", "uninspected")):
            pending_units += quantity
            normalized_status = "pending"
        else:
            # Do not silently count an unknown status as passed or failed.
            pending_units += quantity
            normalized_status = "unclassified"

        status_counts[normalized_status] = (
            status_counts.get(normalized_status, 0) + 1
        )

        raw_category = first_value(lot, category_keys)
        category = str(raw_category or "Uncategorized").strip() or "Uncategorized"
        category_counts[category] = category_counts.get(category, 0) + 1

        explicit_total = first_value(lot, total_value_keys)
        unit_value = first_value(lot, unit_value_keys)

        if explicit_total is not None:
            inventory_value += max(0.0, numeric_value(explicit_total))
            has_inventory_value = True
        elif unit_value is not None:
            inventory_value += max(0.0, numeric_value(unit_value)) * quantity
            has_inventory_value = True

    coverage = (
        (inspected_units / total_units * 100.0)
        if total_units > 0
        else 0.0
    )
    pass_rate = (
        (passed_units / inspected_units * 100.0)
        if inspected_units > 0
        else 0.0
    )

    return {
        "dataset_available": total_lots > 0,
        "total_lots": total_lots,
        "total_units": round(total_units, 2),
        "inspected_units": round(inspected_units, 2),
        "passed_units": round(passed_units, 2),
        "failed_units": round(failed_units, 2),
        "pending_units": round(pending_units, 2),
        "inspection_coverage_percent": round(coverage, 2),
        "inspection_pass_rate_percent": round(pass_rate, 2),
        "inventory_value_inr": round(inventory_value, 2) if has_inventory_value else None,
        "status_counts": status_counts,
        "category_counts": category_counts,
    }


@app.get("/")
def root() -> dict[str, str]:
    return {"app": "ReCoverIQ", "status": "running"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    metadata = read_metadata()
    return {
        "success": True,
        "status": "online",
        "message": "ReCoverIQ API is running",
        "dataset_available": bool(metadata and metadata.get("record_count", 0)),
        "dataset_version": metadata.get("version") if metadata else None,
    }


@app.post("/api/validate")
def validate_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a dataset without saving or replacing the active dataset."""
    records: Any = payload.get("records", payload)

    if isinstance(records, dict):
        lots = records.get(
            "lots",
            records.get(
                "records",
                records.get("data", records.get("items", [])),
            ),
        )
    else:
        lots = records

    if not isinstance(lots, list):
        raise HTTPException(
            status_code=422,
            detail="Expected an array of lot records.",
        )

    result = validate_lots(lots)
    return result


@app.get("/api/lots")
def get_lots() -> list[dict[str, Any]]:
    """Backward-compatible endpoint returning the active lots array."""
    return read_lots()


@app.put("/api/lots")
def put_lots(payload: LotsInput) -> list[dict[str, Any]]:
    """
    Backward-compatible replacement endpoint.

    Existing pages can continue sending {"lots": [...]}.
    """
    return write_lots(payload.lots, filename="API update")


@app.post("/api/lots/import", status_code=201)
def import_lots(payload: DatasetImportInput) -> dict[str, Any]:
    """
    Import and replace the active dataset after validation.

    The old dataset remains active if validation fails.
    Proposals and outcomes are stored separately and are not deleted here.
    """
    filename = Path(payload.filename.strip()).name or "Uploaded dataset"
    saved_lots = write_lots(payload.lots, filename=filename)
    metadata = read_metadata()

    return {
        "success": True,
        "message": "Dataset imported successfully.",
        "dataset": metadata,
        "summary": calculate_dataset_summary(saved_lots),
        "lots": saved_lots,
    }


@app.get("/api/dataset")
def get_active_dataset() -> dict[str, Any]:
    """
    Return the active dataset, its metadata and its calculated summary.
    This is the preferred endpoint for pages that need shared dataset state.
    """
    lots = read_lots()
    metadata = read_metadata()

    return {
        "dataset": metadata,
        "lots": lots,
        "summary": calculate_dataset_summary(lots),
        "dataset_available": bool(metadata and lots),
    }


@app.get("/api/summary")
def get_dataset_summary() -> dict[str, Any]:
    """Return metrics calculated from the currently active dataset."""
    lots = read_lots()
    metadata = read_metadata()

    return {
        "dataset": metadata,
        "summary": calculate_dataset_summary(lots),
        "dataset_available": bool(metadata and lots),
    }


@app.get("/api/proposals")
def get_proposals() -> Any:
    return list_proposals()


@app.post("/api/proposals", status_code=201)
def post_proposal(payload: ProposalInput) -> Any:
    try:
        return create_proposal(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/proposals/{proposal_id}/status")
def patch_proposal_status(
    proposal_id: str,
    payload: ProposalStatusInput,
) -> Any:
    try:
        return update_proposal_status(proposal_id, payload.status)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Proposal not found.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/proposals/{proposal_id}")
def remove_proposal(proposal_id: str) -> dict[str, Any]:
    try:
        if not delete_proposal(proposal_id):
            raise HTTPException(status_code=404, detail="Proposal not found.")
        return {"deleted": True, "proposal_id": proposal_id}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/outcomes")
def get_outcomes() -> Any:
    return list_outcomes()


@app.post("/api/outcomes", status_code=201)
def post_outcome(payload: OutcomeInput) -> Any:
    try:
        return create_outcome(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/proposals/{proposal_id}/variance")
def get_variance(proposal_id: str) -> Any:
    try:
        return calculate_variance(proposal_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail="Proposal not found.",
        ) from exc


@app.delete("/api/outcomes/{outcome_id}")
def remove_outcome(outcome_id: str) -> dict[str, Any]:
    if not delete_outcome(outcome_id):
        raise HTTPException(status_code=404, detail="Outcome not found.")
    return {"deleted": True, "outcome_id": outcome_id}


@app.get("/api/variance")
def get_all_variance() -> dict[str, Any]:
    """
    Return the currently saved proposals and outcomes for the Pilot Tracker.

    This does not invent realized values. Only persisted outcomes are returned.
    """
    proposals = list_proposals()
    outcomes = list_outcomes()

    if not isinstance(proposals, list):
        proposals = []
    if not isinstance(outcomes, list):
        outcomes = []

    outcomes_by_proposal: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        proposal_id = str(outcome.get("proposal_id", ""))
        outcomes_by_proposal.setdefault(proposal_id, []).append(outcome)

    rows = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        proposal_id = str(proposal.get("proposal_id", ""))
        linked_outcomes = outcomes_by_proposal.get(proposal_id, [])

        actual_values = [
            numeric_value(item.get("actual_recovery_inr"))
            for item in linked_outcomes
            if item.get("actual_recovery_inr") is not None
        ]

        expected = proposal.get("expected_recovery_inr")
        actual = sum(actual_values) if actual_values else None

        rows.append({
            "proposal_id": proposal_id,
            "lot_id": proposal.get("lot_id"),
            "proposed_route": proposal.get("proposed_route"),
            "status": proposal.get("status"),
            "expected_recovery_inr": expected,
            "actual_recovery_inr": actual,
            "variance_inr": (
                round(actual - numeric_value(expected), 2)
                if actual is not None and expected is not None
                else None
            ),
            "outcome_count": len(linked_outcomes),
        })

    return {
        "dataset": read_metadata(),
        "count": len(rows),
        "rows": rows,
    }
