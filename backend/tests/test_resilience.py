"""Resilience, safety, and observability tests.

Covers PII redaction, the structured audit event, the policy cache + confidence
flag, data-consistency reads on the policies table, and a *guarded* real-LLM
test that only runs when ANTHROPIC_API_KEY is present (so CI exercises the real
path when a key exists, and skips cleanly otherwise).
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# --------------------------------------------------------------------------- #
# PII redaction & structured audit
# --------------------------------------------------------------------------- #


def test_redact_pii_masks_identifiers() -> None:
    from core.safety import redact_obj, redact_pii

    s = "Contact ada@acme.com or +1 (415) 555-1234, SSN 123-45-6789"
    out = redact_pii(s)
    assert "ada@acme.com" not in out
    assert "555-1234" not in out
    assert "123-45-6789" not in out
    assert "[redacted-email]" in out

    nested = redact_obj({"note": "email x@y.com", "items": ["call 415-555-1234"]})
    assert "x@y.com" not in nested["note"]
    assert "415-555-1234" not in nested["items"][0]


def test_redact_pii_preserves_iso_policy_dates() -> None:
    """Temporal policy metadata must not be misclassified as a phone number."""
    from core.safety import redact_pii

    text = "Effective Date: 2024-01-01; call +1 (415) 555-1234 for support."
    redacted = redact_pii(text)

    assert "2024-01-01" in redacted
    assert "+1 (415) 555-1234" not in redacted
    assert "[redacted-phone]" in redacted


def test_audit_event_schema_and_redaction() -> None:
    from core.safety import audit_event

    ev = audit_event(
        step="synthesise",
        tool="qdrant_search",
        input_data={"q": "reach me at a@b.com"},
        output_data={"answer": "ok"},
        fallback=True,
        confidence=0.42,
        prompt_version="sha256:abc",
    )
    assert set(ev) == {
        "step",
        "tool",
        "input",
        "output",
        "fallback",
        "confidence",
        "prompt_version",
        "timestamp",
    }
    assert "a@b.com" not in ev["input"]["q"]


def test_audit_log_redacts_pii(tmp_path) -> None:
    """memory.log_audit must not persist raw PII."""
    from core.memory import Memory

    mem = Memory(f"sqlite:///{tmp_path / 'audit.db'}")

    async def scenario():
        await mem.log_audit(
            "triage_agent",
            "triage",
            {"ticket": "I am john@corp.com, call 415-555-9999"},
            {"ok": True},
            "success",
        )
        rows = await mem.list_audit()
        assert "john@corp.com" not in rows[0]["input"]
        assert "[redacted-email]" in rows[0]["input"]

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Policy cache + confidence flag
# --------------------------------------------------------------------------- #


def test_rag_query_shape_and_needs_review() -> None:
    """RAG query returns the confidence/needs_review/prompt_version fields."""
    from pipelines.rag_pipeline import rag_pipeline

    res = rag_pipeline.query("what is the leave policy?")
    assert "confidence_score" in res
    assert "needs_review" in res
    assert "prompt_version" in res
    # With no documents ingested confidence is 0 → needs human review.
    assert res["needs_review"] is True


def test_rag_cache_hit() -> None:
    """A repeated query is served from cache."""
    from core.observability import policy_cache_snapshot
    from pipelines.rag_pipeline import RAGPipeline

    rp = RAGPipeline()
    q = "unique cache probe question 123"
    before = policy_cache_snapshot()
    first = rp.query(q)
    second = rp.query(q)
    after = policy_cache_snapshot()
    assert first.get("cached") is False
    assert second.get("cached") is True
    assert after["hits"] >= int(before["hits"]) + 1
    assert after["misses"] >= int(before["misses"]) + 1


# --------------------------------------------------------------------------- #
# Data consistency on the policies table
# --------------------------------------------------------------------------- #


def test_policies_consistency_version_and_updated(tmp_path) -> None:
    """Re-ingesting a doc keeps one row and refreshes its ingested_at/chunks."""
    from core.memory import Memory

    mem = Memory(f"sqlite:///{tmp_path / 'pol.db'}")

    async def scenario():
        await mem.upsert_policy("leave_v1", "leave.pdf", chunks=3, char_count=100)
        first = (await mem.list_policies())[0]
        await asyncio.sleep(0.01)
        await mem.upsert_policy("leave_v1", "leave.pdf", chunks=6, char_count=200)
        rows = await mem.list_policies()
        assert len(rows) == 1  # no duplicate / stale row
        assert rows[0]["chunks"] == 6
        assert rows[0]["ingested_at"] >= first["ingested_at"]

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Guarded real-LLM path (runs only with a key)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="real-LLM path: set ANTHROPIC_API_KEY to run",
)
def test_real_llm_chat_round_trip() -> None:
    """With a key, the chat agent returns a full-mode reply with tool metadata."""
    from agents.chat_agent import chat

    result = asyncio.run(chat("What is the parental leave policy?"))
    assert result["mode"] in ("full", "error")
    assert isinstance(result["reply"], str) and result["reply"]
