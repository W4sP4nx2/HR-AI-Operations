"""Mission-alignment tests — one per non-negotiable principle in MISSION.md.

These guard the *promises*, not just the plumbing: audit-everything, graceful
degradation, own-your-data, and least privilege. They run on the isolated test
DB (see conftest) with no API key.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException


def test_audit_everything_action_is_logged() -> None:
    """Every agent action appends an immutable row to the audit log."""
    from core.memory import memory

    async def scenario():
        before = await memory.count_audit()
        from agents.triage_agent import triage_agent

        await triage_agent.run("I am being harassed at work")
        after = await memory.count_audit()
        assert after > before  # the action was written; if it isn't logged, it didn't happen

    asyncio.run(scenario())


def test_graceful_degradation_works_without_key_or_vector_service() -> None:
    """With no API key and no external vector DB, chat + RAG still function."""
    from agents.chat_agent import chat
    from services import rag

    # Zero-dependency RAG: ingest + retrieve via the in-process local backend.
    assert rag.active_backend() == "local"

    async def scenario():
        await rag.ingest_chunks(
            [
                {
                    "text": "Annual leave is 20 days per year",
                    "doc_id": "leave",
                    "metadata": {"chunk_index": 0},
                }
            ]
        )
        hits = await rag.retrieve("how many vacation days", top_k=1)
        assert hits and hits[0]["doc_id"] == "leave"

        reply = await chat("how many vacation days do I get?")
        assert reply["mode"] == "degraded"  # deterministic fallback, no LLM
        assert reply["reply"].strip()

    asyncio.run(scenario())


def test_own_your_data_chat_session_is_deletable() -> None:
    """Users control their data: a chat session and its messages can be deleted."""
    from core.memory import memory

    async def scenario():
        session = await memory.create_chat_session(title="my chat")
        await memory.add_chat_message(session["id"], "user", "hello")
        assert await memory.get_chat_messages(session["id"])  # exists
        assert await memory.delete_chat_session(session["id"]) is True
        assert await memory.get_chat_messages(session["id"]) == []  # gone

    asyncio.run(scenario())


def test_own_your_data_pii_redacted_before_write() -> None:
    """PII is masked before anything is persisted to the audit trail."""
    from core.memory import memory

    async def scenario():
        row = await memory.log_audit(
            "test_agent",
            "pii_check",
            {"note": "contact jane@acme.com or 123-45-6789"},
            {"ok": True},
            "success",
        )
        assert "jane@acme.com" not in row["input"]
        assert "123-45-6789" not in row["input"]
        assert "redacted" in row["input"]

    asyncio.run(scenario())


def test_least_privilege_enforced_only_when_auth_enforced(monkeypatch) -> None:
    """require_role is advisory in demo mode, hard-blocks under AUTH_ENFORCE=true."""
    from core import security

    manager_only = security.require_role("manager")
    viewer = {"id": "u1", "email": "e@x.com", "role": "viewer"}

    # Advisory (demo) mode: the viewer is allowed through.
    monkeypatch.setattr(security.settings, "auth_enforce", False)
    assert asyncio.run(manager_only(viewer)) is viewer

    # Enforced mode: insufficient role is blocked with 403.
    monkeypatch.setattr(security.settings, "auth_enforce", True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(manager_only(viewer))
    assert exc.value.status_code == 403
