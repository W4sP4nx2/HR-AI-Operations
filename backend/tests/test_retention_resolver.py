"""Tests for the Attrition × Policy composition (agents/retention_resolver.py).

We stub ``services.rag.query`` so the test is deterministic and needs no vector
backend, then assert the composition maps drivers to policy lookups, stays
bounded, and degrades safely.
"""

from __future__ import annotations

import asyncio

import services.rag as rag
from agents.retention_resolver import RetentionResolver


def _stub_rag(monkeypatch, *, mode="grounded_excerpt"):
    async def q(query: str, top_k=None):
        return {
            "answer": f"Policy text for: {query}",
            "mode": mode,
            "source_documents": [{"doc_id": "remote_work_policy", "score": 0.5}],
            "confidence_score": 0.5,
            "needs_review": False,
        }

    monkeypatch.setattr(rag, "query", q)


def test_maps_top_factors_to_policy_lookups(monkeypatch) -> None:
    _stub_rag(monkeypatch)
    factors = [
        {"factor": "disengagement_index", "contribution": 0.4},
        {"factor": "last_promotion_months", "contribution": 0.3},
        {"factor": "salary_band", "contribution": 0.2},
    ]
    out = asyncio.run(RetentionResolver().suggest(0.8, factors))
    assert [s["factor"] for s in out] == ["disengagement_index", "last_promotion_months"]
    assert all(s["grounded"] for s in out)
    assert all("policy_query" in s and s["policy_answer"] for s in out)


def test_bounded_to_max_factors(monkeypatch) -> None:
    _stub_rag(monkeypatch)
    factors = [
        {"factor": "last_promotion_months", "contribution": 0.3},
        {"factor": "salary_band", "contribution": 0.2},
        {"factor": "absence_days", "contribution": 0.1},
    ]
    out = asyncio.run(RetentionResolver().suggest(0.9, factors))
    assert len(out) == RetentionResolver.MAX_FACTORS  # only the top 2 looked up


def test_no_matching_policy_is_honest_not_fabricated(monkeypatch) -> None:
    _stub_rag(monkeypatch, mode="no_context")
    out = asyncio.run(
        RetentionResolver().suggest(0.8, [{"factor": "manager_rating", "contribution": 0.4}])
    )
    assert out[0]["grounded"] is False
    assert "No specific policy located" in out[0]["policy_answer"]


def test_unknown_factor_is_skipped(monkeypatch) -> None:
    _stub_rag(monkeypatch)
    out = asyncio.run(
        RetentionResolver().suggest(0.8, [{"factor": "not_a_real_factor", "contribution": 0.4}])
    )
    assert out == []


def test_rag_failure_yields_empty_never_raises(monkeypatch) -> None:
    async def boom(query: str, top_k=None):
        raise RuntimeError("vector backend down")

    monkeypatch.setattr(rag, "query", boom)
    out = asyncio.run(
        RetentionResolver().suggest(0.8, [{"factor": "salary_band", "contribution": 0.4}])
    )
    assert out == []  # advisory pass must never break the prediction
