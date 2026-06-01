"""Tests for the schema-constrained skill-negation pass.

The live LLM path can't be exercised in CI (no key), so we test:
  * the re-scoring logic directly (deterministic), and
  * the screener integration with a *mocked* validator (proves the flip),
  * plus the keyless fallback, which must mark mode=keyword_fallback and keep the
    documented blind spot (it must never claim 'validated' without a real pass).
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_apply_audit_discounts_negated_and_aspirational_and_rescores() -> None:
    from agents.skill_validator import SkillAudit, SkillEvidence, apply_audit

    result = {
        "score": 72,
        "recommendation": "hire",
        "reasoning": "Overall fit 72/100.",
        "matched_skills": ["python", "fastapi", "langgraph", "async"],
        "missing_skills": [],
        "needs_review": False,
        "_semantic": 0.6,
        "_total": 4,
    }
    audit = SkillAudit(
        items=[
            SkillEvidence(skill="fastapi", status="negated"),
            SkillEvidence(skill="langgraph", status="aspirational"),
            SkillEvidence(skill="python", status="demonstrated"),
            SkillEvidence(skill="async", status="demonstrated"),
        ]
    )
    out = apply_audit(result, audit)
    assert out["skill_audit_mode"] == "validated"
    assert "fastapi" not in out["matched_skills"] and "langgraph" not in out["matched_skills"]
    assert set(out["unverified_skills"]) == {"fastapi", "langgraph"}
    # demonstrated 2/4 → score = 100*(0.6*0.6 + 0.4*0.5) = 56  (< original 72)
    assert out["score"] == 56
    assert out["recommendation"] == "no-hire"
    assert out["needs_review"] is True


def test_validate_falls_back_to_none_without_key() -> None:
    from agents.skill_validator import skill_validator

    out = asyncio.run(skill_validator.validate(["fastapi"], "abandoned fastapi due to scale"))
    assert out is None  # no live key in CI → keyword fallback


@pytest.mark.asyncio
async def test_screener_validated_path_flips_score(monkeypatch) -> None:
    """With a (mocked) validator marking the matches negated, run() flips the
    score down and reports skill_audit_mode='validated'."""
    from agents import skill_validator as sv
    from agents.resume_screener_agent import resume_screener_agent
    from agents.skill_validator import SkillAudit, SkillEvidence

    async def fake_validate(skills, resume):
        return SkillAudit(items=[SkillEvidence(skill=s, status="negated") for s in skills])

    monkeypatch.setattr(sv.skill_validator, "validate", fake_validate)
    jd = "Senior engineer: FastAPI, LangGraph, Python, async."
    resume = (
        "Assisted a team that attempted FastAPI but abandoned it. Read books on "
        "LangGraph but never built. Python and async in theory."
    )
    r = await resume_screener_agent.run(jd, resume)
    assert r["skill_audit_mode"] == "validated"
    assert r["matched_skills"] == []  # every keyword match was negated
    assert r["unverified_skills"]  # the dropped ones are surfaced
    assert r["recommendation"] == "no-hire"


@pytest.mark.asyncio
async def test_screener_fallback_marks_mode_and_keeps_blindspot() -> None:
    """KNOWN LIMITATION on the keyless path: the negation pass is unavailable, so
    the keyword blind spot persists — and the mode says so explicitly."""
    from agents.resume_screener_agent import resume_screener_agent

    jd = "Senior engineer: FastAPI, LangGraph, Python, async."
    resume = (
        "Assisted a team that attempted FastAPI but abandoned it. Read books on "
        "LangGraph but never built. Python and async in theory."
    )
    r = await resume_screener_agent.run(jd, resume)
    assert r["skill_audit_mode"] == "keyword_fallback"
    assert "fastapi" in r["matched_skills"]  # documented blind spot on fallback
