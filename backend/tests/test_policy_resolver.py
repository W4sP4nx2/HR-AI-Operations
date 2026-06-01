"""Tests for the agentic POLICY resolution loop (agents/policy_resolver.py).

Graders are code-based and deterministic: we stub ``rag_pipeline.query`` with
scripted confidence sequences and assert the loop's *behaviour* — that it retries
on low confidence, stops at the attempt cap, keeps the best result, and falls
back safely on timeout. No vector backend required.
"""

from __future__ import annotations

import asyncio
import time

import pipelines.rag_pipeline as rp
from agents.policy_resolver import PolicyResolver


def _scripted_query(confidences: list[float]):
    """A fake rag_pipeline.query returning the next scripted confidence per call."""
    state = {"i": 0}

    def q(query: str, top_k=None):
        conf = confidences[min(state["i"], len(confidences) - 1)]
        state["i"] += 1
        return {
            "answer": f"answer for {query!r}",
            "source_documents": [{"doc_id": "d", "score": conf}] if conf > 0 else [],
            "confidence_score": conf,
            "needs_review": conf < 0.7,
            "prompt_version": "test",
        }

    return q


def _steps(trace, step):
    return [s for s in trace if s.get("step") == step]


def test_accepts_first_pass_when_confident(monkeypatch) -> None:
    """A confident first answer (≥ floor) is accepted with no retry."""
    monkeypatch.setattr(rp.rag_pipeline, "query", _scripted_query([0.9]))
    r = asyncio.run(PolicyResolver().resolve("What is the remote work policy?"))
    assert len(_steps(r["trace"], "retrieve")) == 1
    assert _steps(r["trace"], "reformulate") == []
    assert r["resolution"]["confidence_score"] == 0.9


def test_low_confidence_retries_then_stops_at_cap(monkeypatch) -> None:
    """Two low-confidence passes → exactly one reformulation, bounded at the cap."""
    monkeypatch.setattr(rp.rag_pipeline, "query", _scripted_query([0.0, 0.1]))
    r = asyncio.run(PolicyResolver().resolve("remote work?"))
    assert len(_steps(r["trace"], "retrieve")) == 2  # MAX_ATTEMPTS
    assert len(_steps(r["trace"], "reformulate")) == 1
    # Keeps the higher-confidence of the two attempts.
    assert r["resolution"]["confidence_score"] == 0.1


def test_retry_recovers_a_good_answer(monkeypatch) -> None:
    """A weak first pass that the reformulated retry improves is accepted."""
    monkeypatch.setattr(rp.rag_pipeline, "query", _scripted_query([0.1, 0.8]))
    r = asyncio.run(PolicyResolver().resolve("dress code?"))
    assert len(_steps(r["trace"], "retrieve")) == 2
    assert r["resolution"]["confidence_score"] == 0.8


def test_reformulate_strips_filler_and_leads_with_nouns() -> None:
    """Reformulation drops question filler and leads with policy-bearing tokens."""
    out = PolicyResolver._reformulate_query("What is the remote work policy?")
    words = out.split()
    assert "what" not in words and "is" not in words and "the" not in words
    assert "remote" in words and "work" in words
    assert out.endswith("policy guidelines")


def test_sequential_fallback_matches_graph_behaviour(monkeypatch) -> None:
    """With LangGraph disabled, the plain loop is still bounded and correct."""
    monkeypatch.setattr(rp.rag_pipeline, "query", _scripted_query([0.0, 0.0]))
    resolver = PolicyResolver()
    resolver._graph = None  # force the no-langgraph path
    r = asyncio.run(resolver.resolve("policy?"))
    assert len(_steps(r["trace"], "retrieve")) == 2


def test_timeout_falls_back_to_single_pass(monkeypatch) -> None:
    """A loop that exceeds the wall-clock guard degrades to one safe pass."""

    def slow(query: str, top_k=None):
        time.sleep(0.05)
        return {
            "answer": "a",
            "source_documents": [],
            "confidence_score": 0.0,
            "needs_review": True,
            "prompt_version": "test",
        }

    monkeypatch.setattr(rp.rag_pipeline, "query", slow)
    resolver = PolicyResolver()
    resolver.TIMEOUT_S = 0.001  # force the timeout branch
    r = asyncio.run(resolver.resolve("policy?"))
    assert r["resolution"] is not None
    assert any(s.get("note") == "fallback (loop unavailable)" for s in r["trace"])
