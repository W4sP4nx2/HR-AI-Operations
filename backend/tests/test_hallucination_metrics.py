"""Runtime hallucination metrics endpoint and circuit-breaker tests."""

from __future__ import annotations

import pytest

from core.a2a_envelope import certified_handoff
from core.cost_attribution import record_cost_event, reset_cost_attribution
from core.cost_router import CostRouter
from core.hallucination import hallucination_metrics_snapshot
from services.semantic_cache import HRSemanticCache, context_hash


@pytest.mark.asyncio
async def test_hallucination_metrics_derive_from_envelopes_and_audit_counts() -> None:
    await certified_handoff(
        "chat",
        "ui",
        lambda _payload: {
            "answer": "Use leave_policy.",
            "confidence": 0.9,
            "needs_human_review": False,
            "source_policy_ids": ["leave_policy"],
            "tone": "professional",
        },
        {},
        {
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence": {"type": "number"},
                    "needs_human_review": {"type": "boolean"},
                    "source_policy_ids": {"type": "array", "items": {"type": "string"}},
                    "tone": {"type": "string"},
                },
                "required": [
                    "answer",
                    "confidence",
                    "needs_human_review",
                    "source_policy_ids",
                    "tone",
                ],
                "additionalProperties": False,
            }
        },
        metadata={"source_policy_count": 1},
        persist=False,
    )

    snapshot = hallucination_metrics_snapshot(
        audit_counts={"triage": 10, "triage_override": 2, "human_rejected": 1},
        window=100,
    )

    assert "chat" in snapshot["certification_failure_rate_by_agent"]
    assert snapshot["human_override_rate"] == pytest.approx(3 / 13, abs=0.0001)
    assert snapshot["citation_completeness_score"] is not None
    assert snapshot["pii_leak_incidents"] >= 0
    assert snapshot["triple_lock"]["schema_enforcement"]


def test_budget_circuit_breaker_forces_economy_and_extends_cache_ttl(
    monkeypatch,
) -> None:
    reset_cost_attribution()
    monkeypatch.setattr("core.cost_attribution.settings.daily_inference_budget_usd", 0.0001)
    monkeypatch.setattr("core.cost_attribution.settings.semantic_cache_ttl", 10)
    monkeypatch.setattr("core.cost_attribution.settings.circuit_breaker_cache_ttl_seconds", 3600)
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b,tenant/deep-70b")

    record_cost_event(tier="premium", input_tokens=1000, output_tokens=1000)
    route = CostRouter.classify("Explain a legal termination case.")
    cache = HRSemanticCache(maxsize=4, ttl_seconds=10)
    cache.set("question", context_hash("policy"), {"answer": "cached"})

    assert route.tier == "economy"
    assert route.reason == "budget_circuit_breaker"
    assert cache.active_ttl_seconds() == 3600


def test_hallucination_metrics_endpoint_returns_dashboard_json() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    response = TestClient(app).get("/lifecycle/hallucination_metrics")
    payload = response.json()["data"]

    assert response.status_code == 200
    assert "certification_failure_rate_by_agent" in payload
    assert "human_override_rate" in payload
    assert "citation_completeness_score" in payload
    assert "pii_leak_incidents" in payload
