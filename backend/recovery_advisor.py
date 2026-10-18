"""AI explanations for deterministic ReCoverIQ recovery scenarios."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from google import genai
from pydantic import BaseModel, Field
from pydantic import ValidationError

router = APIRouter(prefix="/api/ai", tags=["AI Recovery Advisor"])


class RecoveryAdviceRequest(BaseModel):
    lot: dict[str, Any]
    scenarios: list[dict[str, Any]] = Field(min_length=1)
    context: str | None = None


class RecoveryAdviceResponse(BaseModel):
    recommendation: str
    rationale: str
    trade_offs: list[str]
    risks: list[str]
    missing_information: list[str]


@router.post(
    "/recovery-advice",
    response_model=RecoveryAdviceResponse,
)
async def get_recovery_advice(
    payload: RecoveryAdviceRequest,
) -> RecoveryAdviceResponse:

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI is not configured. Set GEMINI_API_KEY on the backend.",
        )

    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

    prompt = f"""
You are ReCoverIQ's recovery decision-support advisor.

Explain the recovery options for this ReCoverIQ lot.

LOT:
{json.dumps(payload.lot, ensure_ascii=False, default=str)}

DETERMINISTIC ENGINE SCENARIOS:
{json.dumps(payload.scenarios, ensure_ascii=False, default=str)}

ADDITIONAL CONTEXT:
{payload.context or "None provided"}

RULES:
- The supplied scenarios are the source of truth for financial figures.
- Never invent, estimate, recalculate, or change monetary amounts,
  costs, margins, ranges, quantities, or break-even values.
- Do not claim a route is eligible if the supplied scenario says it is not.
- Explain recommendations using supplied results and eligibility.
- If results are incomplete or ambiguous, say so.
- Distinguish facts from risks and assumptions.
- Return one valid JSON object with exactly these fields:
  recommendation (string),
  rationale (string),
  trade_offs (array of strings),
  risks (array of strings),
  missing_information (array of strings).
- Do not include Markdown fences.
- Do not add any fields.
"""

    client = None

    try:
        client = genai.Client(api_key=api_key)

        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": RecoveryAdviceResponse,
                "temperature": 0.2,
            },
        )

        content = response.text

        if not content:
            raise HTTPException(
                status_code=502,
                detail="The AI returned an empty response. Please retry.",
            )

        advice = json.loads(content)

        return RecoveryAdviceResponse.model_validate(advice)

    except HTTPException:
        raise

    except json.JSONDecodeError as exc:
        print(f"Recovery Advisor returned invalid JSON: {exc}")
        raise HTTPException(
            status_code=502,
            detail="The AI returned an invalid response. Please retry.",
        ) from exc

    except ValidationError as exc:
        print(f"Recovery Advisor response validation failed: {exc}")
        raise HTTPException(
            status_code=502,
            detail="The AI returned an unexpected response format. Please retry.",
        ) from exc

    except Exception as exc:
        print(
            f"Recovery Advisor request failed: "
            f"{type(exc).__name__}: {exc}"
        )
        raise HTTPException(
            status_code=502,
            detail="The AI advisor is temporarily unavailable. Please retry.",
        ) from exc

    finally:
        if client is not None:
            await client.aio.aclose()