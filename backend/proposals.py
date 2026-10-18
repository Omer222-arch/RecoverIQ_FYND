
import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"

PROPOSALS_FILE = DATA_DIR / "proposals.json"
LOTS_FILE = DATA_DIR / "lots.json"
OUTCOMES_FILE = DATA_DIR / "outcomes.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

VALID_ROUTES = {"refurbish", "resale", "scrap"}
VALID_STATUSES = {"draft", "pending_review", "approved", "rejected"}


def _read_json_list(file_path: Path) -> list[dict[str, Any]]:
    """Read a JSON list safely from disk."""
    if not file_path.exists():
        return []

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_json_list(
    file_path: Path,
    records: list[dict[str, Any]],
) -> None:
    """Write JSON using a temporary file to avoid partial writes."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = file_path.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps(records, indent=2),
        encoding="utf-8",
    )
    temporary_file.replace(file_path)


def _read_proposals() -> list[dict[str, Any]]:
    return _read_json_list(PROPOSALS_FILE)


def _write_proposals(proposals: list[dict[str, Any]]) -> None:
    _write_json_list(PROPOSALS_FILE, proposals)


def _get_existing_lot_ids() -> set[str]:
    """Return the IDs of lots currently saved in the backend."""
    lots = _read_json_list(LOTS_FILE)

    return {
        lot["lot_id"]
        for lot in lots
        if isinstance(lot.get("lot_id"), str)
    }


def list_proposals() -> list[dict[str, Any]]:
    return _read_proposals()


def create_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    lot_id = payload.get("lot_id")
    route = payload.get("proposed_route")
    status = payload.get("status", "draft")
    recovery = payload.get("expected_recovery_inr")
    notes = payload.get("notes")

    if not isinstance(lot_id, str) or not lot_id.strip():
        raise ValueError("A non-empty lot_id is required.")

    lot_id = lot_id.strip()

    # NEW: reject proposals referencing nonexistent lots.
    existing_lot_ids = _get_existing_lot_ids()

    if lot_id not in existing_lot_ids:
        raise ValueError(
            f"Lot '{lot_id}' does not exist in backend storage. "
            "Import or save the lot before creating a proposal."
        )

    if route not in VALID_ROUTES:
        raise ValueError(
            "proposed_route must be refurbish, resale, or scrap."
        )

    if status not in VALID_STATUSES:
        raise ValueError("Invalid proposal status.")

    if recovery is not None and (
        isinstance(recovery, bool)
        or not isinstance(recovery, (int, float))
        or recovery < 0
    ):
        raise ValueError(
            "Expected recovery must be non-negative or null."
        )

    if notes is not None and not isinstance(notes, str):
        raise ValueError("Notes must be text or null.")

    proposals = _read_proposals()

    now = datetime.now(timezone.utc).isoformat()

    proposal = {
        "proposal_id": f"PROP-{uuid4().hex[:10].upper()}",
        "lot_id": lot_id,
        "proposed_route": route,
        "status": status,
        "expected_recovery_inr": recovery,
        "created_at": now,
        "updated_at": now,
        "notes": notes,
    }

    proposals.append(proposal)
    _write_proposals(proposals)

    return proposal


def update_proposal_status(
    proposal_id: str,
    status: str,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError("Invalid proposal status.")

    proposals = _read_proposals()

    for proposal in proposals:
        if proposal.get("proposal_id") == proposal_id:
            proposal["status"] = status
            proposal["updated_at"] = datetime.now(
                timezone.utc
            ).isoformat()

            _write_proposals(proposals)
            return proposal

    raise KeyError(f"Proposal not found: {proposal_id}")


def delete_proposal(proposal_id: str) -> bool:
    proposals = _read_proposals()

    matching = [
        proposal
        for proposal in proposals
        if proposal.get("proposal_id") == proposal_id
    ]

    if not matching:
        return False

    # NEW: do not delete a proposal while outcomes reference it.
    outcomes = _read_json_list(OUTCOMES_FILE)

    linked_outcomes = [
        outcome
        for outcome in outcomes
        if outcome.get("proposal_id") == proposal_id
    ]

    if linked_outcomes:
        raise ValueError(
            "This proposal has recorded outcomes. "
            "Delete its outcomes before deleting the proposal."
        )

    remaining = [
        proposal
        for proposal in proposals
        if proposal.get("proposal_id") != proposal_id
    ]

    _write_proposals(remaining)
    return True
