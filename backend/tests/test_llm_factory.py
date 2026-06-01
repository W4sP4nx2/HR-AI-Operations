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

_FAKE = "sk-ant-FAKE-not-real"


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


def test_triage_decision_schema_rejects_bad_category() -> None:
    """The Literal-typed result blocks arbitrary categories at the schema level."""
    from pydantic import ValidationError

    from agents.triage_agent import TriageDecision

    TriageDecision(category="URGENT", confidence=0.9, rationale="harassment")
    with pytest.raises(ValidationError):
        TriageDecision(category="NONSENSE", confidence=0.5, rationale="x")
