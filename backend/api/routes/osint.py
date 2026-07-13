"""Opt-in professional-source intelligence boundary.

The route exposes policy validation and a graph shape for a future adapter; it
does not scrape the web.  With ``OSINT_ENABLED`` unset (the default), requests
return ``unavailable`` rather than making an unreviewed employment decision.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.responses import fail, ok, unavailable
from core.security import require_role
from services.osint_guardrails import (
    OSINTPolicyError,
    build_graph,
    build_observations,
    osint_enabled,
    validate_request,
)

router = APIRouter(prefix="/osint", tags=["osint"])


class OSINTQuery(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    purpose: str
    consent: bool = False
    sources: list[str] = Field(min_length=1, max_length=10)
    claims: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


@router.post("/search")
async def search_osint(
    query: OSINTQuery,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Validate consent and return operator-supplied observations only."""
    try:
        request = validate_request(
            subject=query.subject,
            purpose=query.purpose,
            consent=query.consent,
            sources=query.sources,
        )
    except OSINTPolicyError as exc:
        return fail(str(exc))
    if not osint_enabled():
        return unavailable(
            "OSINT adapter is disabled; no external profile or employment risk score was created",
            {"capability": "osint_adapter", "request": request.__dict__},
        )
    observations = []
    for source in request.sources:
        observations.extend(
            build_observations(
                subject=request.subject,
                source=source,
                claims=query.claims,
                confidence=query.confidence,
            )
        )
    return ok(
        {
            "subject": request.subject,
            "observations": [observation.as_dict() for observation in observations],
            "graph": build_graph(observations),
        }
    )


@router.get("/graph/{entity_id}")
async def get_network_graph(
    entity_id: str,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Explain why graph retrieval is unavailable until a governed adapter exists."""
    if not osint_enabled():
        return unavailable(
            "OSINT graph storage is disabled; enable it only after consent, retention, and legal review",
            {"entity_id": entity_id, "capability": "osint_graph"},
        )
    return unavailable(
        "No external OSINT graph adapter is configured; submit reviewed observations through /osint/search",
        {"entity_id": entity_id, "capability": "osint_graph"},
    )
