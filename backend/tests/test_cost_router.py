"""Deterministic cost routing and cache-key tests."""

from __future__ import annotations

import pytest

from core.cost_router import CostRouter
from services.semantic_cache import HRSemanticCache, context_hash, normalize_query


@pytest.fixture
def allowed_models(monkeypatch):
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b,tenant/reasoning-70b")
    return ["tenant/fast-8b", "tenant/reasoning-70b"]


def test_cost_router_sends_simple_policy_lookup_to_economy(allowed_models):
    route = CostRouter.classify("What is my vacation balance?")

    assert route.tier == "economy"
    assert route.selected_model == allowed_models[0]
    assert route.reason == "simple_policy_lookup_keyword"


def test_cost_router_sends_high_stakes_issue_to_premium(allowed_models):
    route = CostRouter.classify("I need help with a harassment and legal complaint.")

    assert route.tier == "premium"
    assert route.selected_model == allowed_models[1]
    assert route.reason == "high_stakes_hr_keyword"


def test_cost_router_has_no_model_default(monkeypatch):
    monkeypatch.delenv("ALLOWED_MODELS", raising=False)

    with pytest.raises(RuntimeError, match="ALLOWED_MODELS"):
        CostRouter.classify("vacation")


def test_semantic_cache_normalizes_repetitive_queries_and_context():
    cache = HRSemanticCache(maxsize=4, ttl_seconds=0)
    policy_context = context_hash("rag", "prompt-v1", "5", "policies")
    cache.set("What is my VACATION balance?", policy_context, {"answer": "See PTO policy."})

    assert normalize_query("  What is my vacation balance?! ") == "what is my vacation balance"
    assert cache.get("what is my vacation balance", policy_context) == {"answer": "See PTO policy."}
    assert cache.get("what is my vacation balance", context_hash("rag", "prompt-v2")) is None
