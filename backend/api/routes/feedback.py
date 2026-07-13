"""Retention feedback telemetry — capture what a human did with a suggestion.

The honest half of the "agents need reward" idea: we *record* whether a manager
accepted / rejected / edited an agent's retention suggestion, and expose
human-facing aggregate stats. We deliberately do **not** feed this back into the
agents to steer future output — that would be an unauditable, bias-prone reward
loop in a regulated HR setting. Recommendations stay deterministic and grounded;
a human reads the "what's working" signal and decides.

Endpoints
---------
POST /feedback         Record one accept/reject/edit (manager+); append-only.
GET  /feedback/stats   Per-driver acceptance aggregates (manager+).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.responses import ok
from core.memory import memory
from core.security import require_role

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackInput(BaseModel):
    """One manager decision on an agent suggestion.

    ``action_taken`` is a closed enum, so an invalid value (e.g. ``"maybe"``) is
    rejected by FastAPI with a 422 *before* it ever reaches the data layer.
    """

    case_id: str = Field(..., min_length=1)
    suggestion_id: str = Field(..., min_length=1)
    risk_driver: str = Field(..., min_length=1)
    action_taken: Literal["accepted", "rejected", "edited"]
    manager_notes: str = ""


@router.post("")
async def submit_feedback(
    body: FeedbackInput,
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Record a manager's decision on a retention suggestion (append-only)."""
    record = await memory.record_feedback(
        case_id=body.case_id,
        suggestion_id=body.suggestion_id,
        risk_driver=body.risk_driver,
        action_taken=body.action_taken,
        manager_notes=body.manager_notes,
        decided_by_id=user.get("id", "unknown"),
    )
    # Immutable compliance trail (mirrors how every other agent action is audited).
    await memory.log_audit(
        "attrition_agent",
        "retention_feedback",
        {"case_id": body.case_id, "risk_driver": body.risk_driver},
        {
            "action": body.action_taken,
            "feedback_id": record["id"],
            "decided_by_id": user.get("id", "unknown"),
            "role": user.get("role"),
        },
        "success",
    )
    record.pop("manager_notes", None)  # don't echo (possibly redacted) notes back
    return ok(record)


@router.get("/stats")
async def feedback_stats(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Per-driver acceptance aggregates — the human-facing 'what's working' view."""
    return ok(await memory.feedback_stats())
