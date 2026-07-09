"""Authentication & account endpoints.

Two sign-in paths:

  * **Email + password** (`/auth/register`, `/auth/login`) — for local/dev and
    self-hosted deployments. The first registered user becomes ``admin``.
  * **Google OAuth** (`/auth/google/login` → `/auth/google/callback`) — enabled
    automatically when ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET`` are set.

Tokens are JWTs returned in the body and also set as an ``access_token`` cookie
so the dashboard can authenticate WebSocket/stream requests.

Admin-only user management lives under `/auth/users` (list + set role).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from api.responses import fail, ok
from core.config import settings
from core.memory import memory
from core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class RegisterRequest(BaseModel):
    """New-account payload."""

    email: EmailStr
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    """Email/password login payload."""

    email: EmailStr
    password: str


class RoleUpdate(BaseModel):
    """Admin role assignment payload."""

    role: str


class RoleSwitchRequest(BaseModel):
    """Open-access role switch payload (no password — advisory mode only)."""

    role: str


def _public_user(u: dict[str, Any]) -> dict[str, Any]:
    """Strip secrets from a user record before returning it."""
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u.get("name"),
        "role": u["role"],
        "provider": u.get("provider", "local"),
        "avatar_url": u.get("avatar_url"),
    }


def _issue(user: dict[str, Any]) -> dict[str, Any]:
    """Build the token envelope for a user."""
    token = create_access_token(user)
    return {"token": token, "user": _public_user(user)}


# --------------------------------------------------------------------------- #
# Email + password
# --------------------------------------------------------------------------- #


@router.post("/register")
async def register(body: RegisterRequest) -> dict[str, Any]:
    """Register a new local account. First user becomes admin."""
    if not settings.auth_open_registration:
        return fail("self-registration is disabled; contact an administrator")
    if len(body.password) < 8:
        return fail("password must be at least 8 characters")
    if await memory.get_user_by_email(body.email):
        return fail("an account with this email already exists")

    role = "admin" if await memory.count_users() == 0 else "viewer"
    user = await memory.create_user(
        email=body.email,
        name=body.name,
        role=role,
        password_hash=hash_password(body.password),
        provider="local",
    )
    await memory.update_user(user["id"], last_login=_now())
    return ok(_issue(user))


@router.post("/login")
async def login(body: LoginRequest) -> dict[str, Any]:
    """Authenticate with email + password and return a JWT."""
    user = await memory.get_user_by_email(body.email)
    if not user or not verify_password(body.password, user.get("password_hash")):
        return fail("invalid email or password")
    await memory.update_user(user["id"], last_login=_now())
    return ok(_issue(user))


@router.get("/me")
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Return the currently authenticated user (or the anonymous viewer)."""
    return ok(_public_user(user))


# --------------------------------------------------------------------------- #
# Open-access role switch (advisory mode only — no real accounts, no passwords)
# --------------------------------------------------------------------------- #


@router.post("/open-access/switch")
async def open_access_switch(body: RoleSwitchRequest) -> dict[str, Any]:
    """Mint a token for a pre-seeded open-access account of the requested role.

    This is the no-login "switch roles" affordance: instead of creating
    separate accounts, a reviewer flips between viewer / analyst / manager /
    admin to see how the surface changes. It is **only** available when
    ``AUTH_ENFORCE`` is off; in an enforced deployment it is
    disabled so it can never be used to escalate privilege.
    """
    from core.security import ROLES

    if settings.auth_enforce:
        return fail("role switching is disabled when AUTH_ENFORCE is on")
    if body.role not in ROLES:
        return fail(f"invalid role; must be one of {ROLES}")

    role_names = {
        "viewer": "Employee",
        "analyst": "HR Analyst",
        "manager": "HR Manager",
        "admin": "Admin",
    }
    display_name = role_names[body.role]
    email = f"{body.role}@demo.local"
    user = await memory.get_user_by_email(email)
    if not user:
        user = await memory.create_user(
            email=email,
            name=display_name,
            role=body.role,
            provider="demo",
        )
    elif user["role"] != body.role or user.get("name") != display_name:
        # Keep the open-access account in sync if roles or labels ever change.
        user = await memory.update_user(user["id"], role=body.role, name=display_name)
    await memory.update_user(user["id"], last_login=_now())
    return ok(_issue(user))


@router.post("/demo/switch")
async def demo_switch(body: RoleSwitchRequest) -> dict[str, Any]:
    """Backward-compatible alias for older local frontends."""
    return await open_access_switch(body)


# --------------------------------------------------------------------------- #
# Google OAuth (enabled when client id/secret are configured)
# --------------------------------------------------------------------------- #


def _google_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _oauth_client():
    """Lazily build an Authlib OAuth client for Google."""
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


@router.get("/google/status")
async def google_status() -> dict[str, Any]:
    """Report whether Google sign-in is configured (for the login UI)."""
    return ok({"enabled": _google_enabled()})


@router.get("/google/login")
async def google_login(request: Request):
    """Begin the Google OAuth flow (redirects to Google's consent screen)."""
    if not _google_enabled():
        return fail("Google sign-in is not configured")
    oauth = _oauth_client()
    redirect_uri = f"{settings.oauth_redirect_base}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request):
    """Handle Google's redirect: upsert the user and redirect to the dashboard."""
    if not _google_enabled():
        return fail("Google sign-in is not configured")
    oauth = _oauth_client()
    try:
        token = await oauth.google.authorize_access_token(request)
        info = token.get("userinfo") or {}
    except Exception as exc:  # noqa: BLE001
        return fail(f"Google authentication failed: {exc}")

    email = (info.get("email") or "").lower()
    if not email:
        return fail("Google did not return an email address")

    user = await memory.get_user_by_email(email)
    if not user:
        role = "admin" if await memory.count_users() == 0 else "viewer"
        user = await memory.create_user(
            email=email,
            name=info.get("name", ""),
            role=role,
            provider="google",
            avatar_url=info.get("picture"),
        )
    await memory.update_user(user["id"], last_login=_now())

    jwt_token = create_access_token(user)
    # Redirect to the frontend with the token; also set a cookie.
    resp = RedirectResponse(url=f"{settings.frontend_base}/?token={jwt_token}")
    resp.set_cookie("access_token", jwt_token, httponly=True, samesite="lax")
    return resp


# --------------------------------------------------------------------------- #
# Admin user management (RBAC)
# --------------------------------------------------------------------------- #


@router.get("/users")
async def list_users(
    _: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    """List all users (admin only)."""
    return ok([_public_user(u) for u in await memory.list_users()])


@router.patch("/users/{user_id}/role")
async def set_role(
    user_id: str,
    body: RoleUpdate,
    _: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Assign a role to a user (admin only)."""
    from core.security import ROLES

    if body.role not in ROLES:
        return fail(f"invalid role; must be one of {ROLES}")
    updated = await memory.update_user(user_id, role=body.role)
    if not updated:
        return fail("user not found")
    return ok(_public_user(updated))


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
