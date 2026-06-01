"""Tests for the closed gaps: case resolve/reopen (G1), policy soft-delete +
restore (G4), and the resume input guard (G3)."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# --------------------------------------------------------------------------- #
# G1 — manual case resolve / reopen
# --------------------------------------------------------------------------- #


def test_case_status_update_and_audit(tmp_path) -> None:
    import api.routes.cases as cases_mod
    from api.routes.cases import StatusUpdate, update_case_status
    from core.memory import Memory

    fresh = Memory(f"sqlite:///{tmp_path / 'c.db'}")
    orig = cases_mod.memory
    cases_mod.memory = fresh
    try:

        async def scenario():
            case = await fresh.create_case(category="BENEFITS", summary="x", status="open")
            user = {"email": "hr@acme.com", "id": "USR-1", "role": "analyst"}
            env = await update_case_status(
                case["id"], StatusUpdate(status="resolved", note="handled"), user
            )
            assert env["data"]["status"] == "resolved"
            rows = await fresh.list_audit()
            assert any(r["action_type"] == "case_resolved" for r in rows)
            # reopen
            env2 = await update_case_status(case["id"], StatusUpdate(status="open"), user)
            assert env2["data"]["status"] == "open"
            # invalid status rejected
            bad = await update_case_status(case["id"], StatusUpdate(status="bogus"), user)
            assert bad["success"] is False

        asyncio.run(scenario())
    finally:
        cases_mod.memory = orig


# --------------------------------------------------------------------------- #
# G4 — policy soft-delete + restore (undo)
# --------------------------------------------------------------------------- #


def test_policy_soft_delete_and_restore(tmp_path) -> None:
    from core.memory import Memory

    mem = Memory(f"sqlite:///{tmp_path / 'p.db'}")

    async def scenario():
        await mem.upsert_policy(
            "leave", "leave.pdf", 2, 100, source_text="Annual leave is 20 days per year."
        )
        assert len(await mem.list_policies()) == 1

        # soft-delete hides it but keeps the row + source_text
        await mem.set_policy_status("leave", "deleted")
        assert await mem.list_policies() == []  # hidden by default
        assert len(await mem.list_policies(include_deleted=True)) == 1
        p = await mem.get_policy("leave")
        assert p["status"] == "deleted" and p["source_text"]

        # restore brings it back
        await mem.set_policy_status("leave", "ingested")
        active = await mem.list_policies()
        assert len(active) == 1 and active[0]["status"] == "ingested"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# G3 — resume input guard
# --------------------------------------------------------------------------- #


def test_resume_rejects_trivial_input() -> None:
    from agents.resume_screener_agent import resume_screener_agent

    res = asyncio.run(
        resume_screener_agent.run("Senior Python engineer with FastAPI and AWS", "john")
    )
    assert res["needs_review"] is True
    assert res["score"] == 0
    assert "insufficient input" in res["reasoning"].lower()


def test_resume_real_input_not_flagged() -> None:
    from agents.resume_screener_agent import resume_screener_agent

    res = asyncio.run(
        resume_screener_agent.run(
            "Senior Python engineer with FastAPI and AWS",
            "Experienced Python engineer, 6 years building FastAPI services on AWS with ML.",
        )
    )
    assert res["needs_review"] is False
    assert 0 <= res["score"] <= 100
