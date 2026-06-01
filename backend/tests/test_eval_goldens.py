"""Triage evaluation harness — a small, balanced golden set with code-based graders.

Built per the eval roadmap: tasks derived from **real reported failures**
(``"sdsd"`` crashing a structured agent, ``"urgent outage"`` landing in the
Cases ledger), unambiguous expected outcomes two reviewers would agree on, and a
**balanced** set that tests when URGENT *should* fire and when it must *not*
(false-positive guard). Graders are code-based (category + escalation), grading
the agent's **output**, not the path it took. Runs on the isolated conftest DB.

Metrics:
  * Per-case objective pass/fail (parametrized) — the gate.
  * Aggregate pass@1 rate over the set, asserted against a threshold.
  * A pass^k consistency check on a critical case (URGENT must be deterministic).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest


@dataclass
class Golden:
    """One eval scenario and its expected, objectively-checkable outcome."""

    text: str
    category: str | None = None  # expected category, if asserted
    escalated: bool = False  # must route to a human
    not_urgent: bool = False  # negative case: must NOT be URGENT/escalated


# Balanced set: positives (should escalate / classify) AND negatives (should not),
# plus the two real-world failures that prompted this harness.
GOLDENS: list[Golden] = [
    # --- URGENT must escalate to a human ---
    Golden("I'm being harassed by my manager", category="URGENT", escalated=True),
    Golden("There is a safety violation on the warehouse floor", category="URGENT", escalated=True),
    Golden(
        "Payroll is broken and pay runs in an hour — urgent!", category="URGENT", escalated=True
    ),
    Golden("I want to report retaliation after my complaint", category="URGENT", escalated=True),
    Golden("urgent outage", category="URGENT", escalated=True),  # real Cases-ledger case
    # --- POLICY auto-resolves ---
    Golden("What is the remote work policy?", category="POLICY"),
    Golden("Where can I find the dress code policy?", category="POLICY"),
    # --- Other categories route, but never escalate as URGENT ---
    Golden("How do I enroll in health insurance benefits?", category="BENEFITS", not_urgent=True),
    Golden(
        "My laptop access isn't set up for my first day", category="ONBOARDING", not_urgent=True
    ),
    Golden("When is my next performance review?", category="PERFORMANCE", not_urgent=True),
    # --- Negatives: routine requests must NOT be flagged urgent ---
    Golden("I need a new monitor", not_urgent=True),
    Golden("When is the holiday party?", not_urgent=True),
    Golden("sdsd", not_urgent=True),  # real failure: garbage input must not crash/escalate
]


def _grade(golden: Golden, result: dict) -> list[str]:
    """Return a list of grader failures (empty list == pass)."""
    failures: list[str] = []
    category = result.get("category")
    status = result.get("case", {}).get("status")
    if golden.category and category != golden.category:
        failures.append(f"category {category!r} != expected {golden.category!r}")
    if golden.escalated and status != "escalated":
        failures.append(f"status {status!r} != 'escalated'")
    if golden.not_urgent and (category == "URGENT" or status == "escalated"):
        failures.append(f"false-positive escalation (category={category}, status={status})")
    return failures


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda g: g.text[:30])
def test_triage_golden_case(golden: Golden) -> None:
    """Each golden scenario must satisfy its objective grader."""
    from agents.triage_agent import triage_agent

    result = asyncio.run(triage_agent.run(golden.text))
    failures = _grade(golden, result)
    assert not failures, f"{golden.text!r}: " + "; ".join(failures)


def test_triage_aggregate_pass_at_1() -> None:
    """pass@1 over the whole set must clear the bar (deterministic → expect 100%)."""
    from agents.triage_agent import triage_agent

    async def run_all():
        passed = 0
        for g in GOLDENS:
            result = await triage_agent.run(g.text)
            if not _grade(g, result):
                passed += 1
        return passed / len(GOLDENS)

    rate = asyncio.run(run_all())
    assert rate >= 0.9, f"pass@1 {rate:.0%} below 90% bar"


def test_triage_urgent_consistency_pass_pow_k() -> None:
    """pass^k: a clear emergency must classify URGENT on every attempt (k=3)."""
    from agents.triage_agent import triage_agent

    async def run_k():
        return [
            (await triage_agent.run("I'm being harassed at work"))["category"] for _ in range(3)
        ]

    assert asyncio.run(run_k()) == ["URGENT", "URGENT", "URGENT"]
