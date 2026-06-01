"""Metrics + triage-routing tests — adapted to the real async-dict contracts.

The agents return ``dict`` from ``await agent.run(...)`` (not the attribute-style
objects in the original spec sketch), and metrics are *queried* from the audit
log + cases rather than computed by agents. These tests assert that real
behaviour on an isolated temp DB so counts reflect only what this test creates.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _isolated(tmp_path):
    """Point the memory singleton at a fresh temp DB; return a restore fn.

    ``triage_agent`` did ``from core.memory import memory`` at import, so it holds
    its own reference to the original singleton. We must rebind *that* module
    attribute too — otherwise the agent writes to the real dev DB and the test
    (a) asserts against the wrong store and (b) pollutes the demo data.
    """
    import agents.triage_agent as triage_mod
    import core.memory as memmod

    fresh = memmod.Memory(str(tmp_path / "metrics_test.db"))
    saved_core, saved_triage = memmod.memory, triage_mod.memory
    memmod.memory = fresh
    triage_mod.memory = fresh

    def restore():
        memmod.memory = saved_core
        triage_mod.memory = saved_triage

    return restore


def test_urgent_inputs_escalate_to_human(tmp_path) -> None:
    """Harassment / safety / explicitly-urgent tickets → URGENT + escalated."""
    restore = _isolated(tmp_path)
    try:
        from agents.triage_agent import triage_agent

        urgent = [
            "I'm being harassed by my manager",
            "Safety violation on the floor",
            "Payroll is broken and pay runs in an hour — urgent!",
        ]

        async def scenario():
            for text in urgent:
                r = await triage_agent.run(text)
                assert r["category"] == "URGENT", f"{text!r} → {r['category']}"
                assert r["case"]["status"] == "escalated"
                assert r["case"]["assigned_agent"] == "human"

        asyncio.run(scenario())
    finally:
        restore()


def test_policy_questions_auto_resolve(tmp_path) -> None:
    """Policy-worded tickets are auto-resolved by triage (no human needed)."""
    restore = _isolated(tmp_path)
    try:
        from agents.triage_agent import triage_agent

        async def scenario():
            for text in ["What is the remote work policy?", "Where is the dress code policy?"]:
                r = await triage_agent.run(text)
                assert r["category"] == "POLICY"
                assert r["case"]["status"] == "resolved"

        asyncio.run(scenario())
    finally:
        restore()


def test_non_urgent_not_escalated(tmp_path) -> None:
    """Routine requests must NOT be classified URGENT (false-positive guard)."""
    restore = _isolated(tmp_path)
    try:
        from agents.triage_agent import triage_agent

        async def scenario():
            for text in ["I need a new monitor", "When is the holiday party?"]:
                r = await triage_agent.run(text)
                assert r["category"] != "URGENT", f"false positive on {text!r}"

        asyncio.run(scenario())
    finally:
        restore()


def test_metrics_derived_from_audit_log(tmp_path) -> None:
    """After triaging, the audit-log aggregations reflect exactly what happened."""
    restore = _isolated(tmp_path)
    try:
        import core.memory as memmod
        from agents.triage_agent import triage_agent

        async def scenario():
            await triage_agent.run("I'm being harassed at work")  # URGENT → escalated
            await triage_agent.run("What is the remote work policy?")  # POLICY → resolved
            await triage_agent.run("I need a new laptop for onboarding")  # ONBOARDING → open

            memory = memmod.memory
            total = await memory.count_audit()
            assert total >= 3  # one audit row per triage

            by_agent = {x["agent"]: x["count"] for x in await memory.audit_counts_by_agent()}
            assert by_agent.get("triage_agent", 0) >= 3

            status = await memory.case_counts_by_status()
            assert status.get("escalated", 0) >= 1
            assert status.get("resolved", 0) >= 1

            categories = {c["category"] for c in await memory.case_counts_by_category()}
            assert {"URGENT", "POLICY"} <= categories

        asyncio.run(scenario())
    finally:
        restore()
