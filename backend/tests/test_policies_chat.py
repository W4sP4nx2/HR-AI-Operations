"""Tests for the policy registry and the Pydantic AI chat agent.

These cover:
  * Policy CRUD in the memory layer (upsert, list, delete).
  * The chat agent's deterministic fallback (no API key needed).
  * The /chat endpoint response envelope.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# --------------------------------------------------------------------------- #
# Policy registry
# --------------------------------------------------------------------------- #


def test_policy_upsert_list_delete(tmp_path) -> None:
    """Policy records can be created, listed and deleted."""
    from core.memory import Memory

    mem = Memory(f"sqlite:///{tmp_path / 'pol.db'}")

    async def scenario():
        # upsert
        rec = await mem.upsert_policy(
            doc_id="leave_policy_abc",
            filename="leave_policy.pdf",
            chunks=4,
            char_count=1200,
            status="ingested",
        )
        assert rec["doc_id"] == "leave_policy_abc"
        assert rec["chunks"] == 4

        # list
        lst = await mem.list_policies()
        assert len(lst) == 1
        assert lst[0]["filename"] == "leave_policy.pdf"

        # re-upsert (update)
        await mem.upsert_policy(
            doc_id="leave_policy_abc",
            filename="leave_policy.pdf",
            chunks=8,
            char_count=2400,
            status="ingested",
        )
        lst2 = await mem.list_policies()
        assert len(lst2) == 1  # still one record
        assert lst2[0]["chunks"] == 8

        # delete
        deleted = await mem.delete_policy("leave_policy_abc")
        assert deleted is True
        assert len(await mem.list_policies()) == 0

        # delete again → not found
        not_found = await mem.delete_policy("leave_policy_abc")
        assert not_found is False

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Chat agent — deterministic fallback
# --------------------------------------------------------------------------- #


def test_chat_fallback_policy_question() -> None:
    """A policy-related message triggers the search_policy tool in degraded mode."""
    from agents.chat_agent import _fallback_chat

    result = asyncio.run(_fallback_chat("How many vacation days do I get?"))
    assert result["mode"] == "degraded"
    assert result["tool_calls"][0]["tool"] == "search_policy"
    # The degraded answer is grounded in retrieved policy text and carries
    # citations the UI renders as clickable source chips.
    assert result["reply"].strip()
    if result["citations"]:
        top = result["citations"][0]
        assert {"n", "doc_id", "title", "score", "text"} <= set(top)


def test_chat_fallback_triage_message() -> None:
    """An urgent message triggers the triage_ticket tool and opens a case."""
    from agents.chat_agent import _fallback_chat

    result = asyncio.run(_fallback_chat("System down, cannot run payroll, urgent!"))
    assert result["mode"] == "degraded"
    assert result["tool_calls"][0]["tool"] == "triage_ticket"
    # The triage result should include a case id.
    triage_result = result["tool_calls"][0]["result"]
    assert triage_result is not None
    assert "case" in triage_result


def test_chat_fallback_unknown_intent() -> None:
    """An unrecognised message returns a helpful prompt without crashing."""
    from agents.chat_agent import _fallback_chat

    result = asyncio.run(_fallback_chat("hello there"))
    assert result["mode"] == "degraded"
    # A vague greeting now attempts a policy search (intent expansion) but, finding
    # nothing relevant, falls to the capability helper without surfacing a stray policy.
    assert "can help with" in result["reply"]
    assert not result.get("citations")


# --------------------------------------------------------------------------- #
# Chat response envelope
# --------------------------------------------------------------------------- #


def test_chat_response_shape() -> None:
    """The public chat() function always returns the expected dict shape."""
    from agents.chat_agent import chat

    result = asyncio.run(chat("What is the leave policy?"))
    assert "reply" in result
    assert "tool_calls" in result
    assert "mode" in result
    assert result["mode"] in ("full", "degraded", "error")
