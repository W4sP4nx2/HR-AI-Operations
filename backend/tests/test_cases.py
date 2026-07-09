"""Tests for the case store and the case-detail activity trail.

Regression guard: the async data-layer migration removed the old ``*_sync``
methods, so the case routes must use the async ``get_case`` and the new
``list_audit_for_case`` helper.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest
import pytest_asyncio

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


@pytest_asyncio.fixture
async def reroute_client(tmp_path):
    """ASGI client with cases + metrics memory rebound to a fresh DB."""
    import api.routes.cases as cases_mod
    import api.routes.metrics as metrics_mod
    from api.main import app
    from core.memory import Memory

    fresh = Memory(f"sqlite:///{tmp_path / 'reroute.db'}")
    saved = {cases_mod: cases_mod.memory, metrics_mod: metrics_mod.memory}
    cases_mod.memory = fresh
    metrics_mod.memory = fresh
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, fresh
    finally:
        for mod, prev in saved.items():
            mod.memory = prev


@pytest.mark.asyncio
async def test_reroute_records_override_and_reassigns(reroute_client) -> None:
    """Re-routing hands the case to a human queue and writes a triage_override row."""
    c, mem = reroute_client
    case = await mem.create_case(
        category="POLICY",
        summary="misrouted",
        assigned_agent="policy_qa_agent",
        status="resolved",
    )
    r = await c.patch(
        f"/cases/{case['id']}/reroute",
        json={"queue": "legal", "reason": "actually a legal matter"},
    )
    assert r.status_code == 200
    updated = r.json()["data"]
    assert updated["assigned_agent"] == "legal"
    assert updated["status"] == "open"  # re-opened, not falsely resolved

    # An immutable triage_override row exists (the override-rate numerator).
    rows = await mem.list_audit()
    overrides = [a for a in rows if a["action_type"] == "triage_override"]
    assert len(overrides) == 1
    assert "legal" in overrides[0]["output"]

    # Metrics expose the override telemetry.
    metrics = (await c.get("/metrics")).json()["data"]
    assert metrics["triage_overrides"] == 1


@pytest.mark.asyncio
async def test_cases_endpoint_uses_cursor_pagination(reroute_client) -> None:
    """Large case lists are returned as bounded cursor pages."""
    c, mem = reroute_client
    for i in range(205):
        await mem.create_case(category="POLICY", summary=f"case {i}", status="open")

    first = await c.get("/cases?limit=50")
    assert first.status_code == 200
    first_page = first.json()["data"]
    assert len(first_page["items"]) == 50
    assert first_page["next_cursor"]

    second = await c.get(f"/cases?limit=50&cursor={first_page['next_cursor']}")
    second_page = second.json()["data"]
    assert len(second_page["items"]) == 50
    assert first_page["items"][-1]["id"] != second_page["items"][0]["id"]


@pytest.mark.asyncio
async def test_reroute_rejects_unknown_queue_422(reroute_client) -> None:
    """An out-of-enum queue is rejected by validation (422), nothing logged."""
    c, mem = reroute_client
    case = await mem.create_case(category="POLICY", summary="x", status="open")
    r = await c.patch(f"/cases/{case['id']}/reroute", json={"queue": "marketing"})
    assert r.status_code == 422
    rows = await mem.list_audit()
    assert not [a for a in rows if a["action_type"] == "triage_override"]
