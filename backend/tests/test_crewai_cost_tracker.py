"""CrewAI cost attribution stays deterministic when LangSmith is absent."""

from __future__ import annotations

import pytest

from agents.crewai_adapter import crewai_cost_attribution, run_certified_crewai_task
from agents.langsmith_cost_tracker import estimate_cost_usd


def test_cost_estimate_uses_tier_specific_rate():
    attribution = estimate_cost_usd("economy", tokens_in=1000, tokens_out=500)

    assert attribution.cost_usd == 0.0003
    assert attribution.cost_per_1k == 0.0002


@pytest.mark.asyncio
async def test_crewai_certified_task_adds_route_and_cost_metadata(monkeypatch):
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b,tenant/deep-70b")

    envelope = await run_certified_crewai_task(
        task_name="resume_screen",
        crew_input={"query": "Review vacation policy answer."},
        executor=lambda _payload: {"answer": "Use PTO policy.", "confidence_score": 0.8},
        objectives={
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence_score": {"type": "number"},
                },
                "required": ["answer", "confidence_score"],
                "additionalProperties": False,
            },
            "require_pii_free": True,
        },
        source_agent="crew_parser",
        target_agent="crew_scorer",
    )
    attribution = crewai_cost_attribution(
        "resume_screen",
        {"query": "Review vacation policy answer."},
        envelope,
    )

    assert envelope.metadata["cost_tier"] == "economy"
    assert envelope.metadata["estimated_cost_usd"] >= 0
    assert attribution.tier == "economy"
