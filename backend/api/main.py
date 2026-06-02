"""FastAPI application entrypoint for the HR AI Command Center.

Wires together:
  * CORS for the Next.js frontend (localhost:3000),
  * REST routers: /agents, /cases, /audit, plus /health,
  * a WebSocket endpoint at /ws/feed broadcasting live case and approval events.

Everything is async. Agents that emit live events are given the WebSocket
broadcaster on startup so human-in-the-loop checkpoints push to the frontend.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from agents.onboarding_agent import onboarding_agent
from agents.triage_agent import triage_agent
from api.responses import ok
from api.routes import agents as agents_routes
from api.routes import audit as audit_routes
from api.routes import auth as auth_routes
from api.routes import byok as byok_routes
from api.routes import cases as cases_routes
from api.routes import chat as chat_routes
from api.routes import feedback as feedback_routes
from api.routes import metrics as metrics_routes
from api.routes import policies as policies_routes
from api.routes import webhooks as webhooks_routes
from api.websocket_manager import manager
from core.config import settings
from core.memory import memory


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup: wire broadcasters, seed agent rows, warn on insecure prod config."""
    onboarding_agent.set_broadcaster(manager.broadcast)
    triage_agent.set_broadcaster(manager.broadcast)
    for entry in agents_routes.AGENT_REGISTRY:
        await memory.upsert_agent(entry["name"], status="idle", last_action="initialised")

    # First-run admin: create from env if configured and not already present.
    if settings.admin_email and settings.admin_password:
        if not await memory.get_user_by_email(settings.admin_email):
            from core.security import hash_password

            await memory.create_user(
                email=settings.admin_email,
                name="Administrator",
                role="admin",
                password_hash=hash_password(settings.admin_password),
                provider="local",
            )
            logging.getLogger("uvicorn.error").info(
                "Created first-run admin %s", settings.admin_email
            )

    if settings.auth_enforce and "insecure" in settings.jwt_secret:
        logging.getLogger("uvicorn.error").warning(
            "AUTH_ENFORCE is on but JWT_SECRET is the insecure default — "
            "set a strong JWT_SECRET before exposing this publicly."
        )
    yield


app = FastAPI(
    title="HR AI Command Center",
    version="1.0.0",
    description="Multi-agent HR operations control plane.",
    lifespan=lifespan,
)

SHOWCASE_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://hr-frontend-sve4.onrender.com",
    "https://hr-frontend.onrender.com",
]


def _allowed_origins() -> list[str]:
    """Return concrete browser origins allowed for HTTP and WebSocket traffic."""
    configured = settings.cors_origins or SHOWCASE_ORIGINS
    # Render's dashboard may temporarily carry ["*"] during showcase debugging.
    # Keep the deployed service safe by expanding that to known frontend origins.
    if "*" in configured:
        return SHOWCASE_ORIGINS
    return configured


def _origin_allowed(origin: str | None) -> bool:
    """Browser WebSocket origin check matching the CORS allowlist."""
    if not origin:
        return True
    normalized = origin.rstrip("/")
    return normalized in {item.rstrip("/") for item in _allowed_origins()}


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Expose the BYOK signal so the dashboard can read whether the server
    # accepted a visitor's own key for this request (the live pulse indicator).
    expose_headers=["X-BYOK"],
)
# Required by Authlib for the Google OAuth redirect flow.
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret)


@app.middleware("http")
async def _byok_key(request, call_next):
    """Bind a visitor's own LLM key (``X-Client-LLM-Key``) to the request only.

    The key is held in a request-scoped contextvar for the duration of the call
    and cleared in ``finally`` — it is never persisted, audited, or logged. LLM
    call-sites read ``core.runtime_key.effective_api_key()``; if no key is
    present (or it fails upstream) they fall back to the deterministic baseline.
    """
    from core.runtime_key import looks_like_key, reset_request_api_key, set_request_api_key

    header_key = request.headers.get("x-client-llm-key") or request.headers.get("x-lm-key")
    # Bind the raw key for this request (so /byok/verify can report malformed vs
    # missing); `llm_active()` gates on format so junk never reaches a real call.
    token = set_request_api_key((header_key or "").strip() or None)
    try:
        response = await call_next(request)
    finally:
        reset_request_api_key(token)
    # Signal to clients whether a usable BYOK key was attached for this request.
    response.headers["X-BYOK"] = "1" if looks_like_key(header_key) else "0"
    return response


@app.middleware("http")
async def _security_headers(request, call_next):
    """Attach conservative security headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


# In-memory per-IP request timestamps for the optional rate limiter. Fine for a
# single-process reference deployment; front with a shared store (Redis) when
# scaling horizontally (see SCALING.md).
_rate_buckets: dict[str, list[float]] = {}


@app.middleware("http")
async def _rate_limit(request, call_next):
    """Cap requests per IP over a rolling window when RATE_LIMIT_REQUESTS > 0.

    Disabled by default (limit 0) so dev and tests are unaffected; set the env
    var in production to bound cost and abuse. WebSocket upgrades bypass this.
    """
    limit = settings.rate_limit_requests
    if limit <= 0 or request.url.path == "/health":
        return await call_next(request)

    import time

    from fastapi.responses import JSONResponse

    now = time.monotonic()
    window = settings.rate_limit_window_seconds
    ip = request.client.host if request.client else "unknown"
    hits = [t for t in _rate_buckets.get(ip, []) if now - t < window]
    if len(hits) >= limit:
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "status": "error",
                "data": None,
                "error": "rate limit exceeded — try again later",
            },
        )
    hits.append(now)
    _rate_buckets[ip] = hits
    return await call_next(request)


app.include_router(auth_routes.router)
app.include_router(byok_routes.router)
app.include_router(agents_routes.router)
app.include_router(cases_routes.router)
app.include_router(feedback_routes.router)
app.include_router(audit_routes.router)
app.include_router(chat_routes.router)
app.include_router(metrics_routes.router)
app.include_router(policies_routes.router)
app.include_router(webhooks_routes.router)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness/health endpoint with a snapshot of system state.

    Also reports the security/capability posture so the dashboard can show an
    honest banner (advisory vs. enforced auth, LLM on/off).
    """
    agent_rows = await memory.list_agents()
    active = sum(1 for a in agent_rows if a.get("status") == "running")
    return ok(
        {
            "status": "healthy",
            "environment": settings.environment,
            "agents_registered": len(agent_rows),
            "agents_active": active,
            "auth_enforced": settings.auth_enforce,
            "llm_enabled": bool(settings.anthropic_api_key) and not settings.mock_llm,
            "demo_mode": settings.demo_mode,
        }
    )


@app.websocket("/ws/feed")
async def feed(websocket: WebSocket) -> None:
    """WebSocket endpoint streaming live case and approval events.

    The client may send pings; the server echoes a heartbeat. All real events
    are pushed by agents/routes via the connection manager.
    """
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "message": "feed online"})
        while True:
            # Keep the connection open; treat any inbound message as a ping.
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
                await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:  # noqa: BLE001
        await manager.disconnect(websocket)
