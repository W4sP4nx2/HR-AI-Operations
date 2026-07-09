"""Tests for agents, model and core layers.

These tests exercise the deterministic fallback paths so they run without an
Anthropic API key, Qdrant, or the heavy LLM frameworks installed. Components
that need optional dependencies are skipped gracefully when unavailable.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types

import pytest

# Make the backend package importable when running ``pytest`` from repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_chunk_text_overlap() -> None:
    """Chunking should respect size and produce overlapping windows."""
    from pipelines.ingestion import chunk_text

    words = " ".join(str(i) for i in range(1000))
    chunks = chunk_text(words, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    # Each chunk has at most chunk_size words.
    assert all(len(c.split()) <= 100 for c in chunks)


def test_api_response_envelope() -> None:
    """Response helpers must produce the consistent envelope shape."""
    from api.responses import fail, ok

    success = ok({"x": 1})
    assert success == {
        "success": True,
        "status": "ok",
        "data": {"x": 1},
        "error": None,
    }
    error = fail("boom")
    assert error["success"] is False
    assert error["status"] == "error"
    assert error["error"] == "boom"

    from api.responses import unavailable

    una = unavailable("no LLM key configured")
    assert una["success"] is False
    assert una["status"] == "unavailable"
    assert una["error"] == "no LLM key configured"


def test_embedder_falls_back_when_sentence_transformer_model_load_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A present-but-unloadable HF model must degrade to hashing embeddings.

    This is the offline circuit-breaker case: sentence-transformers may be
    installed, but Hugging Face network/cache lookup can fail in CI or demos.
    """
    import core.embeddings as emb

    class BrokenSentenceTransformer:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("offline cache miss")

    fake_module = types.SimpleNamespace(SentenceTransformer=BrokenSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    emb._load_model.cache_clear()
    try:
        assert emb._load_model() is None
        vector = emb.Embedder().embed("annual leave policy")
    finally:
        emb._load_model.cache_clear()

    assert len(vector) == emb._FALLBACK_DIM
    assert any(v != 0.0 for v in vector)


def test_triage_keyword_classifier() -> None:
    """The keyword classifier should detect URGENT and category tickets."""
    from agents.triage_agent import TriageAgent

    agent = TriageAgent()
    assert agent._keyword_classify("This is urgent, harassment complaint") == "URGENT"
    assert agent._keyword_classify("Question about my 401k benefits") == "BENEFITS"
    assert agent._keyword_classify("What is the remote work policy?") == "POLICY"


def test_attrition_model_predicts_probability() -> None:
    """The attrition model should return a probability and risk factors."""
    pytest.importorskip("sklearn")
    from models.attrition_model import AttritionModel

    model = AttritionModel()
    result = model.predict(
        {
            "tenure_months": 6,
            "performance_score": 2.0,
            "absence_days": 20,
            "last_promotion_months": 40,
            "salary_band": 1,
            "manager_rating": 2.0,
        }
    )
    assert 0.0 <= result["attrition_risk_score"] <= 1.0
    assert len(result["top_risk_factors"]) == 3
    assert "explanation" in result


def test_attrition_high_vs_low_risk_ordering() -> None:
    """A clearly at-risk profile should score higher than a healthy one."""
    pytest.importorskip("sklearn")
    from models.attrition_model import AttritionModel

    model = AttritionModel()
    high = model.predict(
        {
            "tenure_months": 4,
            "performance_score": 1.5,
            "absence_days": 25,
            "last_promotion_months": 50,
            "salary_band": 1,
            "manager_rating": 1.5,
        }
    )["attrition_risk_score"]
    low = model.predict(
        {
            "tenure_months": 60,
            "performance_score": 4.8,
            "absence_days": 1,
            "last_promotion_months": 3,
            "salary_band": 5,
            "manager_rating": 4.8,
        }
    )["attrition_risk_score"]
    assert high > low


def test_resume_screener_fallback_contract() -> None:
    """The resume screener fallback must return the full JSON contract.

    Runs even without sentence-transformers installed: the embedder degrades to
    a deterministic hashing embedding, so the screener still honours its
    structured contract.
    """
    from agents.resume_screener_agent import ResumeScreenerAgent

    agent = ResumeScreenerAgent()
    result = asyncio.run(
        agent.run(
            "Looking for a Python engineer with PyTorch and AWS experience.",
            "Experienced Python developer skilled in PyTorch and AWS.",
        )
    )
    for key in (
        "score",
        "recommendation",
        "reasoning",
        "matched_skills",
        "missing_skills",
    ):
        assert key in result
    assert 0 <= result["score"] <= 100
