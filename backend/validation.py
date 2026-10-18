
"""Validation and normalization for ReCoverIQ recovery inventory lots."""
from __future__ import annotations

import math
from typing import Any


REQUIRED_FIELDS = (
    "lot_id",
    "units",
    "inspection",
    "refurbishment_inr",
    "handling_inr",
    "resale_price_inr",
    "scrap_recovery_inr",
)

VALID_INSPECTIONS = {"approved", "pending", "rejected"}

MONEY_FIELDS = (
    "refurbishment_inr",
    "handling_inr",
    "resale_price_inr",
    "scrap_recovery_inr",
)


def _issue(
    row: int,
    field: str,
    severity: str,
    message: str,
) -> dict[str, Any]:
    """Build a consistent validation issue."""
    return {
        "row": row,
        "field": field,
        "severity": severity,
        "message": message,
    }


def _valid_money(value: Any) -> bool:
    """Accept finite, non-negative numbers but reject booleans."""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def validate_lots(data: Any) -> dict[str, Any]:
    """
    Validate and normalize recovery lots.

    Required fields must be present. Monetary fields may be null to represent
    unknown values, but cannot be negative, non-numeric, NaN, or infinite.

    Returns:
        {
            "valid": bool,
            "lots": list[dict],
            "issues": list[dict]
        }

    If any error exists, no lots are returned. Warnings do not invalidate
    the dataset. The input objects are not modified.
    """
    issues: list[dict[str, Any]] = []
    valid_lots: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if not isinstance(data, list):
        return {
            "valid": False,
            "lots": [],
            "issues": [
                _issue(
                    0,
                    "data",
                    "error",
                    "Expected a list of lots.",
                )
            ],
        }

    if not data:
        return {
            "valid": False,
            "lots": [],
            "issues": [
                _issue(
                    0,
                    "data",
                    "error",
                    "The dataset is empty. Import at least one lot.",
                )
            ],
        }

    for row_number, item in enumerate(data, start=1):
        row_errors: list[dict[str, Any]] = []

        if not isinstance(item, dict):
            issues.append(
                _issue(
                    row_number,
                    "row",
                    "error",
                    "Each lot must be a JSON object.",
                )
            )
            continue

        # Verify field presence separately from value validation.
        for field in REQUIRED_FIELDS:
            if field not in item:
                row_errors.append(
                    _issue(
                        row_number,
                        field,
                        "error",
                        f"Missing required field: {field}.",
                    )
                )

        # Lot ID
        lot_id = item.get("lot_id")

        if not isinstance(lot_id, str) or not lot_id.strip():
            row_errors.append(
                _issue(
                    row_number,
                    "lot_id",
                    "error",
                    "Lot ID must be a non-empty string.",
                )
            )
        else:
            lot_id = lot_id.strip()

            if lot_id in seen_ids:
                row_errors.append(
                    _issue(
                        row_number,
                        "lot_id",
                        "error",
                        f"Duplicate lot ID: {lot_id}.",
                    )
                )
            else:
                seen_ids.add(lot_id)

        # Units must be a positive integer. Boolean values are rejected
        # explicitly because bool is a subclass of int in Python.
        units = item.get("units")

        if (
            isinstance(units, bool)
            or not isinstance(units, int)
            or units <= 0
        ):
            row_errors.append(
                _issue(
                    row_number,
                    "units",
                    "error",
                    "Units must be a positive integer.",
                )
            )

        # Normalize inspection casing and surrounding whitespace.
        inspection = item.get("inspection")

        if not isinstance(inspection, str):
            row_errors.append(
                _issue(
                    row_number,
                    "inspection",
                    "error",
                    "Inspection must be approved, pending, or rejected.",
                )
            )
        else:
            inspection = inspection.strip().lower()

            if inspection not in VALID_INSPECTIONS:
                row_errors.append(
                    _issue(
                        row_number,
                        "inspection",
                        "error",
                        "Inspection must be approved, pending, or rejected.",
                    )
                )

        # Monetary values may be null, but null must remain null.
        for field in MONEY_FIELDS:
            value = item.get(field)

            if value is None:
                issues.append(
                    _issue(
                        row_number,
                        field,
                        "warning",
                        f"{field} is unknown; it will not be treated as zero.",
                    )
                )
            elif not _valid_money(value):
                row_errors.append(
                    _issue(
                        row_number,
                        field,
                        "error",
                        f"{field} must be a finite, non-negative number or null.",
                    )
                )

        issues.extend(row_errors)

        if not row_errors:
            normalized = dict(item)
            normalized["lot_id"] = lot_id
            normalized["inspection"] = inspection
            valid_lots.append(normalized)

    has_errors = any(
        issue["severity"] == "error"
        for issue in issues
    )

    return {
        "valid": not has_errors,
        "lots": valid_lots if not has_errors else [],
        "issues": issues,
    }
