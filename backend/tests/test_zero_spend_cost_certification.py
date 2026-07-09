"""Zero-spend certification gates for governed inference cost controls."""

from __future__ import annotations

import sys
import types

import pytest


def test_oversized_prompt_rejected_before_any_provider_client(monkeypatch) -> None:
    from core.fireworks import build_chat_body

    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b")
    provider_calls = {"count": 0}

    class FakeAsyncOpenAI:
        def __init__(self, *_args, **_kwargs):
            provider_calls["count"] += 1

    monkeypatch.setitem(
        sys.modules,
        "openai",
        types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )

    with pytest.raises(ValueError, match="Prompt exceeds budget"):
        build_chat_body(
            model_id="tenant/fast-8b",
            messages=[{"role": "user", "content": "token " * 20_000}],
            max_tokens=64,
        )

    assert provider_calls["count"] == 0


def test_prohibited_model_rejected_by_allowlist(monkeypatch) -> None:
    from core.fireworks import build_chat_body

    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b")

    with pytest.raises(ValueError, match="ALLOWED_MODELS"):
        build_chat_body(
            model_id="tenant/unapproved-70b",
            messages=[{"role": "user", "content": "hello"}],
        )


def test_pii_certifier_catches_synthetic_ssn_without_tokenization(monkeypatch) -> None:
    from core.fireworks_certifier import FireworksOutputCertifier

    tokenization = {"called": False}

    def fake_estimator(*_args, **_kwargs):
        tokenization["called"] = True
        return 1

    monkeypatch.setattr(
        "core.cost_guard.TokenBudgetGuard.estimate_text_tokens",
        fake_estimator,
        raising=False,
    )

    result = FireworksOutputCertifier().certify(
        '{"answer":"Employee SSN 123-45-6789","confidence":0.9}',
        {
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["answer", "confidence"],
                "additionalProperties": False,
            },
            "require_pii_free": True,
        },
    )

    assert result.is_valid is False
    assert "pii_detected" in result.violations
    assert result.redaction_count > 0
    assert tokenization["called"] is False


def test_cost_router_keywords_are_data_driven_and_env_flexible(monkeypatch) -> None:
    from core.cost_router import CostRouter

    monkeypatch.setattr(CostRouter, "ECONOMY_KEYWORDS", frozenset({"cafeteria"}))

    route = CostRouter.classify(
        "What is the cafeteria schedule?",
        allowed_models=["tenant/only-70b"],
    )

    assert route.tier == "economy"
    assert route.selected_model == "tenant/only-70b"
    assert route.matched_keyword == "cafeteria"

    premium = CostRouter.classify(
        "Explain termination process for protected class",
        allowed_models=["tenant/fast-8b", "tenant/reasoning-70b"],
    )
    assert premium.tier == "premium"
    assert premium.selected_model == "tenant/reasoning-70b"


def test_semantic_cache_key_determinism_context_miss_and_ttl(monkeypatch) -> None:
    from services.semantic_cache import HRSemanticCache, context_hash

    cache = HRSemanticCache(maxsize=4, ttl_seconds=1)
    query = "What are OFFICE hours?"
    context_v1 = context_hash("policy", "v1")
    context_v2 = context_hash("policy", "v2")

    assert cache.key_for(query, context_v1) == cache.key_for("what are office hours", context_v1)
    assert context_v1 in cache.key_for(query, context_v1)

    now = {"value": 100.0}
    monkeypatch.setattr(cache._local, "_now", lambda: now["value"])
    cache.set(query, context_v1, {"answer": "9-5"})
    assert cache.get("what are office hours", context_v1) == {"answer": "9-5"}
    assert cache.get("what are office hours", context_v2) is None

    now["value"] = 102.1
    assert cache.get("what are office hours", context_v1) is None


def test_cost_math_exact_and_envelope_metadata_complete(monkeypatch) -> None:
    from core.a2a_envelope import certified_handoff
    from core.cost_attribution import estimate_cost_usd, reset_cost_attribution

    estimate = estimate_cost_usd("standard", input_tokens=500, output_tokens=200)
    assert estimate.cost_usd == 0.00063
    assert estimate.cost_per_1k == 0.0009

    reset_cost_attribution()
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b,tenant/reasoning-70b")

    async def run() -> object:
        return await certified_handoff(
            source_agent="policy_qa",
            target_agent="chat",
            func=lambda _payload: {"answer": "Use PTO policy.", "confidence": 0.9},
            payload={"query": "What is my vacation policy?"},
            objectives={
                "schema": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["answer", "confidence"],
                    "additionalProperties": False,
                },
                "require_pii_free": True,
            },
            cost_query="What is my vacation policy?",
            persist=False,
        )

    import asyncio

    envelope = asyncio.run(run())

    assert envelope.metadata["cost_tier"] == "economy"
    assert envelope.metadata["estimated_spend_usd"] >= 0
    assert envelope.metadata["tokens_in_estimate"] > 0
    assert envelope.metadata["tokens_out_estimate"] > 0
    assert envelope.metadata["cost_per_1k"] == 0.0002
    assert envelope.model_id == "tenant/fast-8b"


def test_langsmith_trace_metadata_and_name_convention(monkeypatch) -> None:
    from agents.langsmith_cost_tracker import CostAwareTracer

    calls: list[dict[str, object]] = []

    class FakeClient:
        def create_run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langsmith",
        types.SimpleNamespace(Client=lambda: FakeClient()),
    )

    attribution = CostAwareTracer().trace_agent_step(
        name="policy_qa",
        query="office hours",
        tier="economy",
        tokens_in=500,
        tokens_out=200,
    )

    assert attribution.cost_usd == 0.00014
    assert calls[0]["name"] == "policy_qa_economy"
    metadata = calls[0]["metadata"]
    assert metadata["tokens_in"] == 500
    assert metadata["tokens_out"] == 200
    assert metadata["cost_per_1k"] == 0.0002
    assert metadata["tier"] == "economy"


def test_benchmark_delta_isolated_and_reproducible() -> None:
    from scripts.benchmark_cost_controls import run_ab_benchmark

    baseline = run_ab_benchmark(
        disable_cache=True,
        disable_router=True,
        disable_prefilter=True,
    )
    assert baseline["cost_reduction"] == 0
    assert baseline["controlled"]["provider_calls"] == baseline["uncontrolled"]["provider_calls"]

    runs = [run_ab_benchmark() for _ in range(3)]
    reductions = [run["cost_reduction"] for run in runs]
    assert max(reductions) - min(reductions) < 0.02
    assert all(run["quality_delta"] < 0.05 for run in runs)
