"""Tests for the request-scoped model factory + the migrated chat/triage paths.

CI-safe: construction + gating only, no network and no real key. Confirms the
chat agent now actually builds (the old api_key= path silently returned None) and
that triage degrades to the deterministic keyword classifier when no key is live.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_FAKE = "fixture-anthropic-key-not-real"
_FIREWORKS_FAKE = "fixture-fireworks-key-not-real"


def test_factory_builds_model_from_key_without_network() -> None:
    pytest.importorskip("pydantic_ai")
    from core.llm_factory import anthropic_model_for_key

    assert anthropic_model_for_key(_FAKE) is not None


def test_factory_returns_none_without_key() -> None:
    from core.llm_factory import anthropic_model_for_key

    assert anthropic_model_for_key("") is None
    assert anthropic_model_for_key(None) is None


def test_request_scoped_model_is_none_when_gated_off() -> None:
    """No key / not mock in the test env → llm_active() False → no live model."""
    from core.llm_factory import get_request_scoped_anthropic_model

    assert get_request_scoped_anthropic_model() is None


def test_fireworks_gate_bypasses_mock_when_harness_env_is_complete(monkeypatch) -> None:
    from core import runtime_key

    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("MOCK_LLM", "true")
    monkeypatch.setenv("FIREWORKS_API_KEY", _FIREWORKS_FAKE)
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "provider/small-1b,provider/large-70b")

    assert runtime_key.llm_active() is True
    assert runtime_key.llm_config_issues() == []


def test_fireworks_config_issues_are_actionable_without_defaults(monkeypatch) -> None:
    from core import runtime_key

    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    monkeypatch.delenv("FIREWORKS_BASE_URL", raising=False)
    monkeypatch.delenv("ALLOWED_MODELS", raising=False)

    assert runtime_key.llm_active() is False
    assert runtime_key.llm_config_issues() == [
        "FIREWORKS_API_KEY is missing or malformed",
        "FIREWORKS_BASE_URL is missing",
        "ALLOWED_MODELS is missing",
    ]


def test_legacy_request_model_alias_routes_through_provider_factory(
    monkeypatch,
) -> None:
    from core import llm_factory
    from core.runtime_key import reset_request_api_key, set_request_api_key

    sentinel = object()
    calls: list[tuple[str | None, str]] = []

    def fake_model_for_key(api_key: str | None, role: str = "default"):
        calls.append((api_key, role))
        return sentinel

    monkeypatch.setattr(llm_factory, "model_for_key", fake_model_for_key)
    token = set_request_api_key(_FIREWORKS_FAKE)
    try:
        assert llm_factory.get_request_scoped_anthropic_model() is sentinel
    finally:
        reset_request_api_key(token)

    assert calls == [(_FIREWORKS_FAKE, "default")]


def test_fireworks_requires_injected_allowed_models(monkeypatch) -> None:
    from core.llm_factory import fireworks_model_for

    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", _FIREWORKS_FAKE)
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("ALLOWED_MODELS", raising=False)

    with pytest.raises(RuntimeError, match="ALLOWED_MODELS"):
        fireworks_model_for(role="triage")


def test_pick_model_for_role_uses_only_allowed_models() -> None:
    from core.llm_factory import pick_model_for_role

    allowed = ["provider/medium-8b", "provider/small-1b", "provider/large-70b"]

    assert pick_model_for_role("triage_agent", allowed) == "provider/small-1b"
    assert pick_model_for_role("policy_rag", allowed) == "provider/large-70b"
    assert pick_model_for_role("unknown", allowed) == "provider/medium-8b"


def test_fireworks_model_constructs_without_network(monkeypatch) -> None:
    pytest.importorskip("pydantic_ai")
    from core.llm_factory import fireworks_model_for

    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", _FIREWORKS_FAKE)
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "provider/small-1b")

    assert fireworks_model_for(role="triage") is not None


def test_fireworks_model_uses_hashed_session_affinity_and_retry_budget(
    monkeypatch,
) -> None:
    pytest.importorskip("pydantic_ai")
    from core.fireworks import affinity_token
    from core.llm_factory import fireworks_model_for

    monkeypatch.setenv("FIREWORKS_API_KEY", _FIREWORKS_FAKE)
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "provider/small-1b")

    model = fireworks_model_for(role="chat", session_id="employee@example.com/chat-1")
    client = model._provider.client
    assert client.default_headers["x-session-affinity"] == affinity_token(
        "employee@example.com/chat-1"
    )
    assert "employee@example.com" not in client.default_headers["x-session-affinity"]
    assert client.max_retries == 4


def test_amd_vllm_requires_env_and_selects_only_allowed_model(monkeypatch) -> None:
    from core.llm_factory import amd_vllm_model_for

    monkeypatch.setenv("AMD_VLLM_API_KEY", "local-secure-key-123456")
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://inference.internal/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/small-1b,tenant/reasoning-32b")
    model = amd_vllm_model_for(role="policy_rag")
    assert model is not None
    assert model.model_name == "tenant/reasoning-32b"


def test_chat_agent_now_builds_with_a_key() -> None:
    """Regression: the old AnthropicModel(api_key=...) path returned None (broken);
    via the provider factory it builds a real agent."""
    pytest.importorskip("pydantic_ai")
    from agents.chat_agent import build_pydantic_ai_agent

    assert build_pydantic_ai_agent(_FAKE) is not None
    assert build_pydantic_ai_agent("") is None


@pytest.mark.asyncio
async def test_triage_llm_classify_falls_back_without_key() -> None:
    """Zero-secret default: _llm_classify yields None so the keyword path runs."""
    from agents.triage_agent import triage_agent

    assert await triage_agent._llm_classify("I am being harassed at work") is None


@pytest.mark.asyncio
async def test_triage_confident_keyword_route_skips_live_model(monkeypatch) -> None:
    from agents.triage_agent import TriageAgent

    agent = TriageAgent()

    async def should_not_run(_text):
        raise AssertionError("live model should not run for a confident fast route")

    monkeypatch.setattr(agent, "_llm_classify", should_not_run)
    result = await agent.run("Urgent safety threat needs immediate help")
    assert result["category"] == "URGENT"
    assert result["dossier"]["method"] == "keyword_fast_path"


def test_triage_decision_schema_rejects_bad_category() -> None:
    """The Literal-typed result blocks arbitrary categories at the schema level."""
    from pydantic import ValidationError

    from agents.triage_agent import TriageDecision

    TriageDecision(
        category="URGENT",
        priority="critical",
        confidence=0.9,
        rationale="harassment",
    )
    with pytest.raises(ValidationError):
        TriageDecision(category="NONSENSE", priority="medium", confidence=0.5, rationale="x")
