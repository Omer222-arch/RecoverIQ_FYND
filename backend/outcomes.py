
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from threading import Lock

DATA_DIR = Path(__file__).resolve().parent / "data"
OUTCOMES_FILE = DATA_DIR / "outcomes.json"
PROPOSALS_FILE = DATA_DIR / "proposals.json"
OUTCOMES_LOCK = Lock()


def _read_json_list(file_path: Path) -> list[dict[str, Any]]:
    if not file_path.exists():
        return []

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise RuntimeError(
            f"Unable to read saved records from {file_path.name}."
        ) from None

    if not isinstance(data, list) or any(
        not isinstance(record, dict) for record in data
    ):
        raise RuntimeError(
            f"Saved records in {file_path.name} are invalid."
        )

    return data


def _write_json_list(
    file_path: Path,
    records: list[dict[str, Any]],
) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = file_path.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps(records, indent=2),
        encoding="utf-8",
    )
    temporary_file.replace(file_path)


def list_outcomes() -> list[dict[str, Any]]:
    return _read_json_list(OUTCOMES_FILE)


def create_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    proposal_id = payload.get("proposal_id")
    actual_recovery = payload.get("actual_recovery_inr")
    notes = payload.get("notes")

    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise ValueError("A non-empty proposal_id is required.")

    if actual_recovery is not None and (
        isinstance(actual_recovery, bool)
        or not isinstance(actual_recovery, (int, float))
        or actual_recovery < 0
    ):
        raise ValueError(
            "Actual recovery must be non-negative or null."
        )

    proposals = _read_json_list(PROPOSALS_FILE)
    proposal = next(
        (
            item
            for item in proposals
            if item.get("proposal_id") == proposal_id
        ),
        None,
    )

    if proposal is None:
        raise ValueError(
            f"No proposal found with ID: {proposal_id}"
        )

    outcome = {
        "outcome_id": f"OUT-{uuid4().hex[:10].upper()}",
        "proposal_id": proposal_id,
        "lot_id": proposal["lot_id"],
        "actual_recovery_inr": actual_recovery,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    }

    with OUTCOMES_LOCK:
        outcomes = list_outcomes()
        if any(item.get("proposal_id") == proposal_id for item in outcomes):
            raise ValueError(
                f"An outcome is already recorded for proposal '{proposal_id}'. "
                "Delete the existing outcome before recording a replacement."
            )
        outcomes.append(outcome)
        _write_json_list(OUTCOMES_FILE, outcomes)

    return outcome


def calculate_variance(
    proposal_id: str,
) -> dict[str, Any]:
    proposals = _read_json_list(PROPOSALS_FILE)
    outcomes = list_outcomes()

    proposal = next(
        (
            item
            for item in proposals
            if item.get("proposal_id") == proposal_id
        ),
        None,
    )

    if proposal is None:
        raise ValueError(
            f"No proposal found with ID: {proposal_id}"
        )

    linked_outcomes = [
        item for item in outcomes if item.get("proposal_id") == proposal_id
    ]
    actual_values = [
        item["actual_recovery_inr"]
        for item in linked_outcomes
        if item.get("actual_recovery_inr") is not None
    ]
    actual = sum(actual_values) if actual_values else None

    expected = proposal.get("expected_recovery_inr")

    variance = (
        actual - expected
        if actual is not None and expected is not None
        else None
    )

    return {
        "proposal_id": proposal_id,
        "lot_id": proposal["lot_id"],
        "expected_recovery_inr": expected,
        "actual_recovery_inr": actual,
        "variance_inr": variance,
    }


def delete_outcome(outcome_id: str) -> bool:
    with OUTCOMES_LOCK:
        outcomes = list_outcomes()
        remaining = [
            outcome
            for outcome in outcomes
            if outcome.get("outcome_id") != outcome_id
        ]

        if len(remaining) == len(outcomes):
            return False

        _write_json_list(OUTCOMES_FILE, remaining)
        return True
