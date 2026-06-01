"""Tests for the retention feedback telemetry (append-only ledger + stats + API).

Data-layer tests use a transient SQLite file (matching the project's harness);
the 422 test exercises the real FastAPI validation through an ASGI client.
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mem(tmp_path):
    from core.memory import Memory

    return Memory(f"sqlite:///{tmp_path / 'feedback.db'}")


@pytest.mark.asyncio
async def test_record_feedback_is_append_only(tmp_path) -> None:
    """Each call inserts a distinct, immutable row — there is no update/delete path."""
    mem = _mem(tmp_path)
    a = await mem.record_feedback(
        case_id="CASE-1",
        suggestion_id="performance_score",
        risk_driver="performance_score",
        action_taken="accepted",
        decided_by_id="u1",
    )
    b = await mem.record_feedback(
        case_id="CASE-1",
        suggestion_id="performance_score",
        risk_driver="performance_score",
        action_taken="rejected",
        decided_by_id="u1",
    )
    assert a["id"] != b["id"]  # distinct rows, nothing overwritten
    # The ledger exposes no mutation surface.
    assert not hasattr(mem, "update_feedback")
    assert not hasattr(mem, "delete_feedback")


@pytest.mark.asyncio
async def test_manager_notes_are_pii_redacted_at_rest(tmp_path) -> None:
    """Free-text notes are redacted before they touch the database."""
    mem = _mem(tmp_path)
    rec = await mem.record_feedback(
        case_id="CASE-1",
        suggestion_id="salary_band",
        risk_driver="salary_band",
        action_taken="edited",
        manager_notes="email me at jane.doe@corp.com about this",
    )
    assert "jane.doe@corp.com" not in rec["manager_notes"]


@pytest.mark.asyncio
async def test_feedback_stats_aggregate_exactly(tmp_path) -> None:
    """Aggregates are exact: 3 accepted / 1 rejected → rate 0.75, no rounding drift."""
    mem = _mem(tmp_path)
    for action in ("accepted", "accepted", "accepted", "rejected"):
        await mem.record_feedback(
            case_id="CASE-X",
            suggestion_id="last_promotion_months",
            risk_driver="last_promotion_months",
            action_taken=action,
        )
    stats = await mem.feedback_stats()
    row = next(r for r in stats if r["risk_driver"] == "last_promotion_months")
    assert row["accepted"] == 3
    assert row["rejected"] == 1
    assert row["edited"] == 0
    assert row["total"] == 4
    assert row["acceptance_rate"] == 0.75


@pytest_asyncio.fixture
async def client(tmp_path):
    """ASGI client with the feedback route's memory rebound to a fresh DB."""
    import api.routes.feedback as feedback_mod
    from api.main import app

    fresh = _mem(tmp_path)
    saved = feedback_mod.memory
    feedback_mod.memory = fresh
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, fresh
    finally:
        feedback_mod.memory = saved


@pytest.mark.asyncio
async def test_invalid_action_returns_422_before_data_layer(client) -> None:
    """An out-of-enum action is rejected by validation (422), never persisted."""
    c, mem = client
    r = await c.post(
        "/feedback",
        json={
            "case_id": "CASE-1",
            "suggestion_id": "salary_band",
            "risk_driver": "salary_band",
            "action_taken": "maybe",  # not in {accepted, rejected, edited}
        },
    )
    assert r.status_code == 422
    # Nothing reached the ledger.
    assert await mem.feedback_stats() == []


@pytest.mark.asyncio
async def test_valid_feedback_persists(client) -> None:
    """A valid submission is accepted and shows up in the aggregates."""
    c, mem = client
    r = await c.post(
        "/feedback",
        json={
            "case_id": "CASE-1",
            "suggestion_id": "manager_rating",
            "risk_driver": "manager_rating",
            "action_taken": "accepted",
        },
    )
    assert r.status_code == 200
    assert r.json()["success"] is True
    stats = await mem.feedback_stats()
    assert any(s["risk_driver"] == "manager_rating" and s["accepted"] == 1 for s in stats)
