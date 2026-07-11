"""Governed Pydantic chat wrapper tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.chat_schemas import ChatResponse, normalize_chat_result


def test_chat_response_schema_rejects_extra_and_long_answers() -> None:
    with pytest.raises(ValidationError):
        ChatResponse(
            answer="x" * 501,
            confidence=0.9,
            needs_human_review=False,
            source_policy_ids=[],
            tone="professional",
        )
    with pytest.raises(ValidationError):
        ChatResponse(
            answer="ok",
            confidence=0.9,
            needs_human_review=False,
            source_policy_ids=[],
            tone="professional",
            unexpected=True,
        )


def test_normalize_chat_result_extracts_policy_sources_and_review_flag() -> None:
    structured = normalize_chat_result(
        {
            "reply": "Use the leave policy. [1]",
            "mode": "degraded",
            "citations": [{"doc_id": "leave_policy", "text": "Leave rules"}],
            "tool_calls": [{"tool": "search_policy"}],
        },
        query="How many vacation days?",
    )

    assert structured.source_policy_ids == ["leave_policy"]
    assert structured.confidence >= 0.7
    assert structured.needs_human_review is False


@pytest.mark.asyncio
async def test_governed_chat_certifies_without_allowed_models(monkeypatch) -> None:
    import agents.chat_agent as chat_agent
    from agents.pydantic_chat_agent import governed_chat

    monkeypatch.delenv("ALLOWED_MODELS", raising=False)

    async def fake_chat(_message, _history=None, _session_id=""):
        return {
            "reply": "The leave policy allows reviewed time away. [1]",
            "mode": "degraded",
            "tool_calls": [{"tool": "search_policy"}],
            "citations": [{"doc_id": "leave_policy", "text": "Leave rules"}],
        }

    monkeypatch.setattr(chat_agent, "chat", fake_chat)

    result = await governed_chat("What is the vacation policy?", [], "session-1")

    assert result["certification"]["is_valid"] is True
    assert result["structured"]["source_policy_ids"] == ["leave_policy"]
    assert result["trace_id"]
    assert result["cost_route"]["tier"] == "unavailable"


@pytest.mark.asyncio
async def test_governed_chat_does_not_block_policy_effective_date(monkeypatch) -> None:
    import agents.chat_agent as chat_agent
    from agents.pydantic_chat_agent import governed_chat

    monkeypatch.delenv("ALLOWED_MODELS", raising=False)

    async def fake_chat(_message, _history=None, _session_id=""):
        return {
            "reply": (
                "Effective Date: 2024-01-01. Employees receive 25 days PTO "
                "under the active policy. [1]"
            ),
            "mode": "degraded",
            "tool_calls": [{"tool": "search_policy"}],
            "citations": [{"doc_id": "policy_pto_2024", "text": "25 days PTO"}],
        }

    monkeypatch.setattr(chat_agent, "chat", fake_chat)

    result = await governed_chat("How many PTO days do I have?", [], "session-1")

    assert result["certification"]["is_valid"] is True
    assert result["certification"]["redaction_count"] == 0
    assert result["structured"]["source_policy_ids"] == ["policy_pto_2024"]
    assert "2024-01-01" in result["reply"]


@pytest.mark.asyncio
async def test_governed_chat_records_cost_route_when_allowlist_exists(monkeypatch) -> None:
    import agents.chat_agent as chat_agent
    from agents.pydantic_chat_agent import governed_chat

    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b,tenant/reasoning-70b")

    async def fake_chat(_message, _history=None, _session_id=""):
        return {
            "reply": "Office hours are handled by local policy.",
            "mode": "degraded",
            "tool_calls": [],
            "citations": [],
        }

    monkeypatch.setattr(chat_agent, "chat", fake_chat)

    result = await governed_chat("What are the office hours?", [], "session-1")

    assert result["certification"]["is_valid"] is True
    assert result["cost_route"]["tier"] == "economy"
    assert result["cost_route"]["selected_model"] == "tenant/fast-8b"


@pytest.mark.asyncio
async def test_governed_chat_blocks_pii_before_ui(monkeypatch) -> None:
    import agents.chat_agent as chat_agent
    from agents.pydantic_chat_agent import governed_chat

    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b,tenant/reasoning-70b")

    async def fake_chat(_message, _history=None, _session_id=""):
        return {
            "reply": "I saw SSN 123-45-6789 in the request.",
            "mode": "degraded",
            "tool_calls": [],
            "citations": [],
        }

    monkeypatch.setattr(chat_agent, "chat", fake_chat)

    result = await governed_chat("My SSN is 123-45-6789", [], "session-1")

    assert result["certification"]["is_valid"] is False
    assert result["certification"]["redaction_count"] > 0
    assert "123-45-6789" not in result["reply"]
    assert result["mode"] == "blocked"
