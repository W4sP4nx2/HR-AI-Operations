"""Tests for the input shield (pre-flight firewall) and ephemeral BYOK key layer."""

from __future__ import annotations

import asyncio

import pytest

# --------------------------------------------------------------------------- #
# Input shield
# --------------------------------------------------------------------------- #


def test_sanitize_strips_control_chars_and_caps_length() -> None:
    from services.input_shield import MAX_TEXT_CHARS, sanitize_text

    assert sanitize_text("  hello\x00\x07   world \t ") == "hello world"
    assert len(sanitize_text("x" * (MAX_TEXT_CHARS + 500))) == MAX_TEXT_CHARS
    assert sanitize_text(None) == ""


def test_attrition_rejects_free_text() -> None:
    """Raw text to the maths module is rejected here, not crashed downstream."""
    from services.input_shield import InvalidAgentInput, prepare

    with pytest.raises(InvalidAgentInput) as exc:
        prepare("attrition_agent", "sdsd", {})
    assert exc.value.capability == "structured_input"


def test_attrition_accepts_structured_features() -> None:
    from services.input_shield import prepare

    _text, payload = prepare("attrition_agent", "", {"tenure_months": "12", "manager_rating": 4})
    assert payload["tenure_months"] == 12.0  # coerced to float
    assert payload["manager_rating"] == 4.0


def test_text_agents_pass_through_sanitized() -> None:
    from services.input_shield import prepare

    text, payload = prepare("triage_agent", "  payroll\x00 down ", None)
    assert text == "payroll down"
    assert payload == {}


def test_dispatch_attrition_with_text_returns_unavailable_not_crash() -> None:
    """End-to-end: the JSON trigger path degrades gracefully on free text."""
    from api.routes.agents import dispatch_agent
    from services.input_shield import InvalidAgentInput

    with pytest.raises(InvalidAgentInput):
        asyncio.run(dispatch_agent("attrition_agent", "is John about to quit?", None))


# --------------------------------------------------------------------------- #
# Ephemeral BYOK key
# --------------------------------------------------------------------------- #


def test_effective_key_falls_back_to_server_then_empty(monkeypatch) -> None:
    from core import runtime_key
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert runtime_key.effective_api_key() == ""
    monkeypatch.setattr(settings, "anthropic_api_key", "fixture-server-key-1234567890")
    assert runtime_key.effective_api_key() == "fixture-server-key-1234567890"


def test_request_key_overrides_and_clears() -> None:
    from core import runtime_key

    assert runtime_key.request_api_key() is None
    token = runtime_key.set_request_api_key("fixture-visitor-key-abcdefghij1234567890")
    try:
        assert runtime_key.request_api_key() == "fixture-visitor-key-abcdefghij1234567890"
        assert runtime_key.effective_api_key() == "fixture-visitor-key-abcdefghij1234567890"
    finally:
        runtime_key.reset_request_api_key(token)
    assert runtime_key.request_api_key() is None  # cleared, never lingers


def test_byok_overrides_mock_llm_cost_guard(monkeypatch) -> None:
    """A visitor key activates the LLM even under MOCK_LLM/DEMO_MODE (they opted in)."""
    from core import runtime_key
    from core.config import settings

    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    assert runtime_key.llm_active() is False  # no key → deterministic
    token = runtime_key.set_request_api_key("fixture-visitor-key-abcdefghij1234567890")
    try:
        assert runtime_key.llm_active() is True  # BYOK overrides cost guards
    finally:
        runtime_key.reset_request_api_key(token)


def test_demo_persona_rejected_when_enforced(monkeypatch) -> None:
    """A demo (mock) persona token must NOT authenticate against an enforced instance."""
    from fastapi.testclient import TestClient

    from core import security
    from core.config import settings
    from core.memory import memory

    demo = asyncio.run(
        memory.create_user(email="demo-mgr@demo.local", role="manager", provider="demo")
    )
    real = asyncio.run(
        memory.create_user(email="real-mgr@corp.com", role="manager", provider="local")
    )
    monkeypatch.setattr(settings, "auth_enforce", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-key-that-is-long-enough-0123456789")

    from api.main import app

    client = TestClient(app)
    demo_tok = security.create_access_token(demo)
    real_tok = security.create_access_token(real)

    assert (
        client.get("/auth/me", headers={"Authorization": f"Bearer {demo_tok}"}).status_code == 401
    )
    assert (
        client.get("/auth/me", headers={"Authorization": f"Bearer {real_tok}"}).status_code == 200
    )


def test_agent_trigger_enforces_per_agent_min_role(monkeypatch) -> None:
    """Under enforcement, triggering an agent needs its contract min_role."""
    from fastapi.testclient import TestClient

    from core import security
    from core.config import settings
    from core.memory import memory

    analyst = asyncio.run(
        memory.create_user(email="analyst@corp.com", role="analyst", provider="local")
    )
    manager = asyncio.run(
        memory.create_user(email="mgr2@corp.com", role="manager", provider="local")
    )
    monkeypatch.setattr(settings, "auth_enforce", True)

    from api.main import app

    client = TestClient(app)
    a = {"Authorization": f"Bearer {security.create_access_token(analyst)}"}
    m = {"Authorization": f"Bearer {security.create_access_token(manager)}"}

    # Analyst CAN trigger the analyst-tier resume screener…
    r1 = client.post(
        "/agents/resume_screener_agent/trigger",
        json={"input": "x", "payload": {"job_description": "Python", "resume": "Python dev " * 5}},
        headers=a,
    )
    assert r1.status_code == 200
    # …but NOT the manager-tier attrition agent.
    r2 = client.post(
        "/agents/attrition_agent/trigger",
        json={"input": "", "payload": {"tenure_months": 10}},
        headers=a,
    )
    assert r2.status_code == 403
    # A manager can.
    r3 = client.post(
        "/agents/attrition_agent/trigger",
        json={"input": "", "payload": {"tenure_months": 10}},
        headers=m,
    )
    assert r3.status_code == 200


def test_byok_verify_missing_and_malformed() -> None:
    """The verify endpoint distinguishes missing vs malformed vs (un)verifiable."""
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    assert client.get("/byok/verify").json()["data"]["status"] == "missing"
    short = client.get("/byok/verify", headers={"X-Client-LLM-Key": "short"}).json()["data"]
    assert short["status"] == "malformed" and short["valid"] is False
    # A well-formed but fake key reaches the provider check → not "verified"
    # (rejected if the network is up, unverifiable if offline — never valid).
    fake = client.get(
        "/byok/verify",
        headers={"X-Client-LLM-Key": "fixture-anthropic-key-1234567890abcdef"},
    ).json()["data"]
    assert fake["valid"] is False and fake["status"] in {"rejected", "unverifiable"}


def test_byok_key_is_never_persisted_to_audit() -> None:
    """A request key must not leak into the immutable audit log."""
    from core import runtime_key
    from core.memory import memory

    secret = "fixture-visitor-key-DEADBEEF-never-store-1234567890"
    token = runtime_key.set_request_api_key(secret)
    try:

        async def scenario():
            from agents.triage_agent import triage_agent

            await triage_agent.run("payroll outage, urgent!")
            rows = await memory.list_audit(limit=50)
            blob = " ".join((r.get("input") or "") + (r.get("output") or "") for r in rows)
            assert secret not in blob

        asyncio.run(scenario())
    finally:
        runtime_key.reset_request_api_key(token)
