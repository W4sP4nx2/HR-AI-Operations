"""End-to-end API tests through the real ASGI app (middleware + auth + envelopes).

Unlike the unit tests that call route functions directly, these drive the full
FastAPI application via ``httpx.ASGITransport`` — exercising middleware, the status
envelope, auth headers, RBAC enforcement, and security headers as a real client.

Isolation: the fixture flips ``settings.auth_enforce`` on, sets a strong test JWT
secret, and rebinds the shared ``memory`` singleton (and each route module's
binding) to a fresh temp-DB ``Memory`` — then restores everything on teardown.
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest_asyncio.fixture
async def client(tmp_path):
    """Yield an AsyncClient bound to the ASGI app with enforced auth + fresh DB."""
    import api.routes.agents as agents_mod
    import api.routes.auth as auth_mod
    import api.routes.cases as cases_mod
    import api.routes.chat as chat_mod
    import api.routes.policies as policies_mod
    import core.security as security_mod
    from api.main import app
    from core.config import settings
    from core.memory import Memory

    fresh = Memory(f"sqlite:///{tmp_path / 'itest.db'}")

    # Save + override config.
    saved_enforce = settings.auth_enforce
    saved_secret = settings.jwt_secret
    settings.auth_enforce = True
    settings.jwt_secret = "test-secret-key-that-is-long-enough-0123456789"

    # Rebind the memory singleton everywhere it was imported.
    rebind = [security_mod, agents_mod, auth_mod, cases_mod, chat_mod, policies_mod]
    saved_mem = {m: getattr(m, "memory", None) for m in rebind}
    for m in rebind:
        if hasattr(m, "memory"):
            m.memory = fresh

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        settings.auth_enforce = saved_enforce
        settings.jwt_secret = saved_secret
        for m, prev in saved_mem.items():
            if prev is not None:
                m.memory = prev


@pytest.mark.asyncio
async def test_health_envelope_and_security_headers(client) -> None:
    """/health returns the status envelope + posture, with security headers."""
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["status"] == "ok"
    assert body["data"]["auth_enforced"] is True
    assert "agents_registered" in body["data"]
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"


@pytest.mark.asyncio
async def test_showcase_cors_allows_render_frontend_preflight(client) -> None:
    """Showcase CORS accepts the deployed frontend origin cleanly."""
    r = await client.options(
        "/health",
        headers={
            "Origin": "https://hr-frontend-sve4.onrender.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-client-llm-key",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "https://hr-frontend-sve4.onrender.com"
    assert "authorization" in r.headers.get("access-control-allow-headers", "").lower()


@pytest.mark.asyncio
async def test_showcase_cors_rejects_unknown_origin_preflight(client) -> None:
    """Unknown browser origins are not granted CORS access."""
    r = await client.options(
        "/health",
        headers={
            "Origin": "https://example.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 400
    assert r.headers.get("access-control-allow-origin") is None


def test_websocket_feed_accepts_browser_connection() -> None:
    """The live feed route accepts a standard browser WebSocket handshake."""
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/feed",
            headers={"Origin": "https://hr-frontend-sve4.onrender.com"},
        ) as websocket:
            assert websocket.receive_json() == {
                "type": "connected",
                "message": "feed online",
            }


def test_websocket_feed_rejects_unknown_browser_origin() -> None:
    """The live feed does not accept WebSocket upgrades from random origins."""
    import pytest
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from api.main import app

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "/ws/feed",
                headers={"Origin": "https://example.invalid"},
            ):
                pass
        assert exc.value.code == 1008


@pytest.mark.asyncio
async def test_register_login_and_me(client) -> None:
    """First user becomes admin; the token authenticates /auth/me."""
    r = await client.post(
        "/auth/register",
        json={"email": "admin@test.com", "password": "supersecret1", "name": "Admin"},
    )
    data = r.json()["data"]
    assert data["user"]["role"] == "admin"
    token = data["token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["email"] == "admin@test.com"

    # Wrong password is rejected.
    bad = await client.post("/auth/login", json={"email": "admin@test.com", "password": "nope"})
    assert bad.json()["status"] == "error"


@pytest.mark.asyncio
async def test_rbac_enforced_blocks_then_allows(client) -> None:
    """Under enforcement: 401 without a token, 200 with an admin token."""
    reg = await client.post(
        "/auth/register", json={"email": "admin@test.com", "password": "supersecret1"}
    )
    token = reg.json()["data"]["token"]

    anon = await client.get("/auth/users")
    assert anon.status_code == 401

    ok = await client.get("/auth/users", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert ok.json()["success"] is True


@pytest.mark.asyncio
async def test_agent_trigger_envelope(client) -> None:
    """Triggering triage returns the ok/error/unavailable envelope.

    Triggering is write-authority (triage needs analyst+); under enforcement we
    authenticate as the first user (admin) before triggering.
    """
    reg = await client.post(
        "/auth/register", json={"email": "trigger@test.com", "password": "supersecret1"}
    )
    token = reg.json()["data"]["token"]
    r = await client.post(
        "/agents/triage_agent/trigger",
        json={"input": "payroll is down, urgent!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = r.json()
    assert body["status"] in ("ok", "error", "unavailable")
    if body["status"] == "ok":
        assert "category" in body["data"]


@pytest.mark.asyncio
async def test_audit_read(client) -> None:
    """The audit endpoint returns a list envelope (manager+ under enforcement)."""
    reg = await client.post(
        "/auth/register", json={"email": "auditor@test.com", "password": "supersecret1"}
    )
    token = reg.json()["data"]["token"]  # first user → admin
    auth = {"Authorization": f"Bearer {token}"}
    await client.post("/agents/triage_agent/trigger", json={"input": "urgent outage"})
    # Audit is least-privilege gated: no token is rejected, admin is allowed.
    assert (await client.get("/audit")).status_code == 401
    r = await client.get("/audit", headers=auth)
    assert r.status_code == 200
    assert isinstance(r.json()["data"], list)
