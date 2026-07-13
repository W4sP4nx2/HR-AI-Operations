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


def test_external_text_agents_redact_pii_before_dispatch() -> None:
    from services.input_shield import prepare

    text, payload = prepare(
        "resume_screener_agent",
        "SSN 123-45-6789",
        {"resume": "Contact jane@example.com or 415-555-1212"},
    )

    assert "123-45-6789" not in text
    assert "jane@example.com" not in payload["resume"]
    assert "415-555-1212" not in payload["resume"]


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

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert runtime_key.effective_api_key() == ""
    monkeypatch.setattr(settings, "anthropic_api_key", "fixture-server-key-1234567890")
    assert runtime_key.effective_api_key() == "fixture-server-key-1234567890"


def test_hosted_provider_request_key_overrides_and_clears(monkeypatch) -> None:
    from core import runtime_key

    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    assert runtime_key.request_api_key() is None
    token = runtime_key.set_request_api_key("test-key-test-key")
    try:
        assert runtime_key.request_api_key() == "test-key-test-key"
        assert runtime_key.effective_api_key() == "test-key-test-key"
    finally:
        runtime_key.reset_request_api_key(token)
    assert runtime_key.request_api_key() is None  # cleared, never lingers


def test_amd_service_key_cannot_be_overridden_by_request_key(monkeypatch) -> None:
    from core import runtime_key

    monkeypatch.setenv("LLM_PROVIDER", "amd_vllm")
    monkeypatch.setenv("AMD_VLLM_API_KEY", "test-key-test-key")
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://amd-vllm:8000/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "amd-gemma-3-27b-it")

    token = runtime_key.set_request_api_key("browser-key-must-not-win-1234567890")
    try:
        assert runtime_key.byok_supported() is False
        assert runtime_key.effective_api_key() == "test-key-test-key"
        assert runtime_key.llm_active() is True
    finally:
        runtime_key.reset_request_api_key(token)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/byok/verify"),
        ("POST", "/chat"),
        ("POST", "/chat/stream"),
        ("POST", "/agents/triage_agent/trigger"),
        ("POST", "/agents/resume_screener_agent/trigger/upload"),
        ("POST", "/crews/hierarchical/resume_review/run"),
    ],
)
def test_byok_route_allowlist_accepts_only_model_capable_requests(method: str, path: str) -> None:
    from api.main import _byok_capable_request

    assert _byok_capable_request(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/health"),
        ("GET", "/metrics"),
        ("POST", "/auth/login"),
        ("GET", "/audit"),
        ("POST", "/policies/ingest"),
        ("POST", "/agents/orchestrator/plan"),
    ],
)
def test_byok_route_allowlist_rejects_non_inference_requests(method: str, path: str) -> None:
    from api.main import _byok_capable_request

    assert not _byok_capable_request(method, path)


def test_byok_header_is_ignored_on_health() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    response = TestClient(app).get(
        "/health",
        headers={"X-Client-LLM-Key": "test-key-test-key"},
    )

    assert response.headers["X-BYOK"] == "0"


def test_byok_header_is_accepted_on_verification(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from api.main import app
    from api.routes import byok

    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setattr(
        byok,
        "_verify_sync",
        lambda _key: {
            "valid": True,
            "status": "verified",
            "provider": "fireworks",
            "detail": "key accepted by provider",
        },
    )
    response = TestClient(app).get(
        "/byok/verify",
        headers={"X-Client-LLM-Key": "test-key-test-key"},
    )

    assert response.headers["X-BYOK"] == "1"
    assert response.json()["data"]["status"] == "verified"


def test_byok_overrides_mock_llm_cost_guard(monkeypatch) -> None:
    """A visitor key activates the LLM even under MOCK_LLM/DEMO_MODE (they opted in)."""
    from core import runtime_key
    from core.config import settings

    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")

    assert runtime_key.llm_active() is False  # no key → deterministic
    token = runtime_key.set_request_api_key("test-key-test-key")
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


def test_open_access_role_switch_mints_no_login_session(monkeypatch) -> None:
    """Open-access role switching gives reviewers a scoped session without a password."""
    from fastapi.testclient import TestClient

    from core.config import settings

    monkeypatch.setattr(settings, "auth_enforce", False)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-key-that-is-long-enough-0123456789")

    from api.main import app

    client = TestClient(app)
    response = client.post("/auth/open-access/switch", json={"role": "manager"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["token"]
    assert body["data"]["user"]["name"] == "HR Manager"
    assert body["data"]["user"]["role"] == "manager"


def test_agent_trigger_enforces_per_agent_min_role(monkeypatch) -> None:
    """Under enforcement, triggering an agent needs its contract min_role."""
    from fastapi.testclient import TestClient

    from core import security
    from core.config import settings
    from core.memory import memory

    viewer = asyncio.run(
        memory.create_user(email="viewer@corp.com", role="viewer", provider="local")
    )
    manager = asyncio.run(
        memory.create_user(email="mgr2@corp.com", role="manager", provider="local")
    )
    monkeypatch.setattr(settings, "auth_enforce", True)

    from api.main import app

    client = TestClient(app)
    v = {"Authorization": f"Bearer {security.create_access_token(viewer)}"}
    m = {"Authorization": f"Bearer {security.create_access_token(manager)}"}

    # A manager can trigger the manager-tier resume screener…
    r1 = client.post(
        "/agents/resume_screener_agent/trigger",
        json={
            "input": "x",
            "payload": {"job_description": "Python", "resume": "Python dev " * 5},
        },
        headers=m,
    )
    assert r1.status_code == 200
    # A viewer cannot trigger the manager-tier attrition agent.
    r2 = client.post(
        "/agents/attrition_agent/trigger",
        json={"input": "", "payload": {"tenure_months": 10}},
        headers=v,
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
    missing = client.get("/byok/verify").json()["data"]
    assert missing["status"] == "missing"
    assert missing["provider"]
    short = client.get("/byok/verify", headers={"X-Client-LLM-Key": "short"}).json()["data"]
    assert short["status"] == "malformed" and short["valid"] is False
    assert short["provider"]
    # A well-formed but fake key reaches the provider check → not "verified"
    # (rejected if the network is up, unverifiable if offline — never valid).
    fake = client.get(
        "/byok/verify",
        headers={"X-Client-LLM-Key": "fixture-anthropic-key-1234567890abcdef"},
    ).json()["data"]
    assert fake["valid"] is False and fake["status"] in {"rejected", "unverifiable"}
    assert fake["provider"]


def test_byok_verify_rejects_amd_service_key_without_network(monkeypatch) -> None:
    """AMD/vLLM uses private service auth, never the browser BYOK boundary."""
    import httpx

    monkeypatch.setenv("LLM_PROVIDER", "amd_vllm")
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://amd-vllm:8000/v1")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *_args, **_kwargs: pytest.fail("AMD BYOK must not contact vLLM"),
    )

    from fastapi.testclient import TestClient

    from api.main import app

    response = TestClient(app).get(
        "/byok/verify",
        headers={"X-Client-LLM-Key": "test-key-test-key"},
    )
    result = response.json()["data"]

    assert response.headers["X-BYOK"] == "0"
    assert result["valid"] is False
    assert result["status"] == "unsupported"
    assert result["provider"] == "amd_vllm"


def test_byok_key_is_never_persisted_to_audit() -> None:
    """A request key must not leak into the immutable audit log."""
    from core import runtime_key
    from core.memory import memory

    secret = "test-secret-test-secret"
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
