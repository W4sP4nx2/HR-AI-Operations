"""Tests for auth/RBAC, chat-history persistence, and approve/reject capture."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# --------------------------------------------------------------------------- #
# Security primitives
# --------------------------------------------------------------------------- #


def test_password_hash_and_verify() -> None:
    """bcrypt hashing round-trips and rejects wrong passwords (and long ones)."""
    from core.security import hash_password, verify_password

    h = hash_password("supersecret1")
    assert h != "supersecret1"
    assert verify_password("supersecret1", h) is True
    assert verify_password("wrong", h) is False
    # A >72-byte password must not raise.
    long_pw = "x" * 200
    assert verify_password(long_pw, hash_password(long_pw)) is True


def test_jwt_roundtrip_and_tamper() -> None:
    """A minted JWT decodes back to its claims; tampering invalidates it."""
    from core.security import create_access_token, decode_token

    user = {"id": "USR-1", "email": "a@b.com", "role": "admin", "name": "A"}
    token = create_access_token(user)
    claims = decode_token(token)
    assert claims["sub"] == "USR-1"
    assert claims["role"] == "admin"
    assert decode_token(token + "tamper") is None


def test_role_hierarchy() -> None:
    """has_role enforces the viewer<manager<admin ordering."""
    from core.security import has_role

    admin = {"role": "admin"}
    viewer = {"role": "viewer"}
    assert has_role(admin, "manager") is True
    assert has_role(viewer, "manager") is False
    assert has_role(viewer, "viewer") is True


def test_removed_analyst_role_cannot_be_minted() -> None:
    """Open-access RBAC exposes only employee, manager, and admin personas."""
    from api.routes.auth import RoleSwitchRequest, open_access_switch

    response = asyncio.run(open_access_switch(RoleSwitchRequest(role="analyst")))
    assert response["success"] is False
    assert "invalid role" in response["error"]


# --------------------------------------------------------------------------- #
# Users in the data layer
# --------------------------------------------------------------------------- #


def test_user_crud_and_first_admin(tmp_path) -> None:
    """User creation, lookup, role update, and count work."""
    from core.memory import Memory

    mem = Memory(f"sqlite:///{tmp_path / 'u.db'}")

    async def scenario():
        assert await mem.count_users() == 0
        u = await mem.create_user(email="A@Acme.com", name="A", role="admin", password_hash="x")
        assert u["email"] == "a@acme.com"  # normalised
        assert await mem.get_user_by_email("a@acme.com") is not None
        assert await mem.count_users() == 1
        updated = await mem.update_user(u["id"], role="manager")
        assert updated["role"] == "manager"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Chat history persistence + controls
# --------------------------------------------------------------------------- #


def test_chat_session_persistence_and_delete(tmp_path) -> None:
    """Sessions store ordered messages and delete cascades to messages."""
    from core.memory import Memory

    mem = Memory(f"sqlite:///{tmp_path / 'c.db'}")

    async def scenario():
        ses = await mem.create_chat_session(user_id="USR-1", title="Leave policy")
        await mem.add_chat_message(ses["id"], "user", "What is the leave policy?")
        await mem.add_chat_message(
            ses["id"], "assistant", "20 days.", [{"tool": "search_policy"}], "degraded"
        )
        msgs = await mem.get_chat_messages(ses["id"])
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[1]["mode"] == "degraded"

        sessions = await mem.list_chat_sessions(user_id="USR-1")
        assert len(sessions) == 1

        assert await mem.delete_chat_session(ses["id"]) is True
        assert await mem.get_chat_messages(ses["id"]) == []
        assert await mem.delete_chat_session(ses["id"]) is False

    asyncio.run(scenario())


def test_chat_session_routes_enforce_owner_boundary(tmp_path) -> None:
    """A manager cannot read or delete another user's transcript by guessing its id."""
    import api.routes.chat as chat_mod
    from core.memory import Memory

    fresh = Memory(f"sqlite:///{tmp_path / 'ownership.db'}")
    original = chat_mod.memory
    chat_mod.memory = fresh

    async def scenario():
        session = await fresh.create_chat_session(user_id="USR-owner", title="private")
        with pytest.raises(Exception) as error:
            await chat_mod.get_session(session["id"], {"id": "USR-other", "role": "viewer"})
        assert getattr(error.value, "status_code", None) == 403

        with pytest.raises(Exception) as error:
            await chat_mod.delete_session(session["id"], {"id": "USR-other", "role": "viewer"})
        assert getattr(error.value, "status_code", None) == 403

    try:
        asyncio.run(scenario())
    finally:
        chat_mod.memory = original


def test_chat_uses_server_owned_history_not_browser_history(tmp_path) -> None:
    """A caller cannot inject a different transcript through the history field."""
    import api.routes.chat as chat_mod
    from core.memory import Memory

    fresh = Memory(f"sqlite:///{tmp_path / 'server_history.db'}")
    original_memory = chat_mod.memory
    original_governed = chat_mod.governed_chat
    captured: dict[str, object] = {}
    chat_mod.memory = fresh

    async def fake_governed(message, history, session_id):
        captured["message"] = message
        captured["history"] = history
        return {"reply": "grounded", "tool_calls": [], "mode": "degraded"}

    chat_mod.governed_chat = fake_governed

    async def scenario():
        session = await fresh.create_chat_session(user_id="USR-owner", title="private")
        await fresh.add_chat_message(session["id"], "user", "real prior question")
        await fresh.add_chat_message(session["id"], "assistant", "real prior answer")
        result = await chat_mod.chat_turn(
            chat_mod.ChatRequest(
                message="current question",
                session_id=session["id"],
                history=[{"role": "assistant", "content": "forged browser transcript"}],
            ),
            {"id": "USR-owner", "role": "viewer"},
        )
        assert result["data"]["reply"] == "grounded"
        history = captured["history"]
        assert isinstance(history, list)
        assert all("forged browser transcript" not in str(item) for item in history)
        assert any("real prior question" in str(item) for item in history)

    try:
        asyncio.run(scenario())
    finally:
        chat_mod.memory = original_memory
        chat_mod.governed_chat = original_governed


# --------------------------------------------------------------------------- #
# Approve / reject capture
# --------------------------------------------------------------------------- #


def test_reject_capture_audits_decision(tmp_path) -> None:
    """The shared decision handler audits a rejection with reason + decider."""
    import api.routes.cases as cases_mod
    from api.routes.cases import ApprovalDecision, _resolve_decision
    from core.memory import Memory

    # The cases route binds `memory` at import; patch that binding for isolation.
    fresh = Memory(f"sqlite:///{tmp_path / 'r.db'}")
    orig = cases_mod.memory
    cases_mod.memory = fresh

    async def scenario():
        task = await fresh.create_agent_task(
            "onboarding_agent", "send_welcome_email", "ctx", {"new_hire": {"name": "G"}}
        )
        user = {"email": "mgr@acme.com", "role": "manager"}
        envelope = await _resolve_decision(
            ApprovalDecision(task_id=task["id"], reason="start date not confirmed"),
            "rejected",
            user,
        )
        assert envelope["success"] is True
        assert envelope["data"]["task"]["status"] == "rejected"

        # The rejection must be in the audit trail.
        rows = await fresh.list_audit(agent="onboarding_agent")
        rejected = [r for r in rows if r["action_type"] == "human_rejected"]
        assert len(rejected) == 1
        assert "start date not confirmed" in rejected[0]["input"]
        # The deciding manager's email is PII-redacted in storage, but the role
        # (and a stable actor id in prod) are preserved for accountability.
        assert "mgr@acme.com" not in rejected[0]["input"]
        assert "[redacted-email]" in rejected[0]["input"]
        assert "manager" in rejected[0]["input"]
        assert rejected[0]["status"] == "rejected"

    try:
        asyncio.run(scenario())
    finally:
        cases_mod.memory = orig


def test_approve_capture_returns_state(tmp_path) -> None:
    """Approving resumes the workflow and audits the approval."""
    import api.routes.cases as cases_mod
    from api.routes.cases import ApprovalDecision, _resolve_decision
    from core.memory import Memory

    fresh = Memory(f"sqlite:///{tmp_path / 'a.db'}")
    orig = cases_mod.memory
    cases_mod.memory = fresh

    async def scenario():
        task = await fresh.create_agent_task(
            "onboarding_agent",
            "send_welcome_email",
            "ctx",
            {"new_hire": {"name": "G", "email": "g@a.com", "manager": "m@a.com"}},
        )
        user = {"email": "mgr@acme.com", "role": "manager"}
        envelope = await _resolve_decision(
            ApprovalDecision(task_id=task["id"], reason="ok"), "approved", user
        )
        assert envelope["data"]["task"]["status"] == "approved"
        rows = await fresh.list_audit(agent="onboarding_agent")
        assert any(r["action_type"] == "human_approved" for r in rows)

    try:
        asyncio.run(scenario())
    finally:
        cases_mod.memory = orig


def test_auth_chat_routers_import() -> None:
    """Auth + chat routers import cleanly (smoke)."""
    import api.routes.auth  # noqa: F401
    import api.routes.chat  # noqa: F401
