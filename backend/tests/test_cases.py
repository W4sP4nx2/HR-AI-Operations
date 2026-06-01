"""Tests for the case store and the case-detail activity trail.

Regression guard: the async data-layer migration removed the old ``*_sync``
methods, so the case routes must use the async ``get_case`` and the new
``list_audit_for_case`` helper.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_get_case_and_activity_trail(tmp_path) -> None:
    """A created case is retrievable and its audit activity is found by id."""
    from core.memory import Memory

    db = tmp_path / "cases.db"
    mem = Memory(f"sqlite:///{db}")

    async def scenario() -> None:
        case = await mem.create_case(
            category="URGENT",
            summary="payroll down",
            detail="cannot run payroll",
            assigned_agent="human",
            status="escalated",
        )
        cid = case["id"]

        # get_case (async) returns the record — the old get_case_sync is gone.
        fetched = await mem.get_case(cid)
        assert fetched is not None
        assert fetched["id"] == cid
        assert fetched["status"] == "escalated"

        # An audit row referencing the case id is discoverable for the drawer.
        await mem.log_audit(
            "triage_agent",
            "triage",
            {"ticket": "payroll down"},
            {"category": "URGENT", "status": "escalated", "case_id": cid},
            "success",
        )
        # An unrelated audit row must NOT match.
        await mem.log_audit("policy_qa_agent", "query", {"q": "x"}, {"answer": "y"}, "success")

        trail = await mem.list_audit_for_case(cid)
        assert len(trail) == 1
        assert trail[0]["agent_name"] == "triage_agent"
        assert cid in trail[0]["output"]

        # Unknown case → no record.
        assert await mem.get_case("CASE-NOPE") is None

    asyncio.run(scenario())


def test_resolve_agent_task_is_atomic_compare_and_set(tmp_path) -> None:
    """Only the first decision wins; a second (duplicate) decision returns None.

    Guards the human-in-the-loop approval against double-execution: a second
    approve/reject of an already-decided task must not transition it again (which
    is what would re-resume a workflow and duplicate its side-effects).
    """
    from core.memory import Memory

    mem = Memory(f"sqlite:///{tmp_path / 'tasks.db'}")

    async def scenario() -> None:
        task = await mem.create_agent_task(
            "onboarding_agent",
            step="send_welcome_email",
            context="ready",
            state={"new_hire": {"email": "a@b.co"}, "accounts": ["sso:a@b.co"]},
        )
        tid = task["id"]

        # First approval transitions the task and returns the row.
        first = await mem.resolve_agent_task(tid, "approved", "")
        assert first is not None
        assert first["status"] == "approved"

        # Second (duplicate / racing) decision changes nothing → None.
        second = await mem.resolve_agent_task(tid, "approved", "")
        assert second is None, "already-decided task must not resolve twice"

        # A reject after an approve is likewise refused (status no longer pending).
        third = await mem.resolve_agent_task(tid, "rejected", "changed mind")
        assert third is None

        # Unknown task id → None (not found).
        assert await mem.resolve_agent_task("TASK-NOPE", "approved", "") is None

    asyncio.run(scenario())
