"""Tests for the two-node résumé cross-validation pipeline.

Deterministic, code-based graders. They assert the consistency pass flags real
data-integrity anomalies, and — just as importantly — that it does NOT flag
employment gaps (a protected-class proxy we deliberately refuse to penalise).
"""

from __future__ import annotations

import asyncio

from agents.resume_resolver import ResumeResolver


def _analyze(text: str):
    return asyncio.run(ResumeResolver().analyze(text))


def test_clean_timeline_has_no_flags() -> None:
    """Sequential, well-formed ranges raise nothing."""
    resume = "Engineer 2015-2018. Senior Engineer 2018-2021. Lead 2021-Present."
    out = _analyze(resume)
    assert out["flags"] == []
    assert len(out["spans"]) == 3


def test_reversed_range_is_flagged() -> None:
    """A range that ends before it begins is a typo-class anomaly."""
    out = _analyze("Analyst 2020-2017 at Acme.")
    assert any("ends before it begins" in f for f in out["flags"])


def test_future_date_is_flagged() -> None:
    """A clearly future-dated entry is flagged for verification."""
    out = _analyze("Director 2090-2095.")
    assert any("future" in f.lower() for f in out["flags"])


def test_fully_overlapping_roles_flagged_as_concurrency() -> None:
    """One role wholly inside another → confirm-concurrency flag (not fabrication)."""
    out = _analyze("Engineer 2015-2022. Consultant 2017-2019.")
    assert any("overlap" in f.lower() for f in out["flags"])


def test_employment_gap_is_NOT_flagged() -> None:
    """Fairness guard: a gap between roles must never be flagged."""
    # 2016-2018 then 2021-2023 → a multi-year gap, but no logical inconsistency.
    out = _analyze("Engineer 2016-2018. Engineer 2021-2023.")
    assert out["flags"] == [], f"gap should not be flagged, got: {out['flags']}"


def test_no_dates_yields_no_flags() -> None:
    """Résumés without parseable date ranges simply produce no flags."""
    out = _analyze("Experienced software engineer skilled in Python and Go.")
    assert out["flags"] == []
    assert out["spans"] == []


def test_sequential_fallback_when_langgraph_absent() -> None:
    """With the graph disabled, the plain-function path produces identical flags."""
    resolver = ResumeResolver()
    resolver._graph = None
    out = asyncio.run(resolver.analyze("Analyst 2020-2017."))
    assert any("ends before it begins" in f for f in out["flags"])
