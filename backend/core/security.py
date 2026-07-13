"""Authentication, RBAC and JWT helpers.

Roles (ascending privilege)::

    viewer   read-only: dashboards, cases, audit, chat
    manager  + operate agents, cases, analytics, approvals and policies
    admin    + manage users and roles, delete data

``require_role(min_role)`` returns a FastAPI dependency that enforces the
hierarchy. When ``settings.auth_enforce`` is False (default for zero-secret
demos) identity is still attached when a token is present, but missing/blocked
identities are allowed through as an anonymous ``viewer`` so the app stays fully
usable. Set ``AUTH_ENFORCE=true`` (and a real ``JWT_SECRET``) in production.
"""

from __future__ import annotations

import time
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status

from core.config import settings
from core.memory import memory

# Role hierarchy → privilege level.
ROLES = ["viewer", "manager", "admin"]
_ROLE_LEVEL = {r: i for i, r in enumerate(ROLES)}

ANONYMOUS: dict[str, Any] = {
    "id": "anon",
    "email": "anonymous@local",
    "name": "Anonymous",
    "role": "viewer",
    "provider": "none",
}


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt.

    bcrypt only considers the first 72 bytes, so we truncate explicitly (this
    avoids the ValueError newer bcrypt raises on longer inputs).
    """
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def create_access_token(user: dict[str, Any]) -> str:
    """Mint a signed JWT for a user record."""
    now = int(time.time())
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "role": user["role"],
        "name": user.get("name", ""),
        "iat": now,
        "exp": now + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT; return the claims or None if invalid."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:  # noqa: BLE001
        return None


def _extract_token(request: Request) -> str | None:
    """Pull a bearer token from the Authorization header or an access cookie."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("access_token")


async def get_current_user(request: Request) -> dict[str, Any]:
    """Resolve the current user from the request.

    Returns the live user record when a valid token maps to an existing account.
    Falls back to the anonymous viewer when no/invalid token is present (so the
    app is usable without auth in dev). Raises 401 only when enforcement is on
    and the token is present but invalid.
    """
    token = _extract_token(request)
    if not token:
        if settings.auth_enforce:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            )
        return ANONYMOUS

    claims = decode_token(token)
    if not claims:
        if settings.auth_enforce:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or expired token",
            )
        return ANONYMOUS

    user = await memory.get_user(claims.get("sub", ""))
    if not user:
        # Token valid but user gone; treat as anonymous unless enforcing.
        if settings.auth_enforce:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown user")
        return ANONYMOUS
    # Production safety gate: demo personas (minted by /auth/demo/switch in
    # advisory mode) must NEVER authenticate against an enforced instance, even
    # if the row/token still exists. Mock identities are a demo-only construct.
    if settings.auth_enforce and user.get("provider") == "demo":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="demo accounts are not accepted when AUTH_ENFORCE is on",
        )
    return user


def require_role(min_role: str):
    """Return a dependency enforcing a minimum role.

    Args:
        min_role: One of ``viewer``/``manager``/``admin``.

    When ``settings.auth_enforce`` is False the check is advisory (anonymous is
    allowed); when True, insufficient privilege raises 403.
    """
    threshold = _ROLE_LEVEL[min_role]

    async def _dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        level = _ROLE_LEVEL.get(user.get("role", "viewer"), 0)
        if level < threshold:
            if settings.auth_enforce:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"requires '{min_role}' role or higher",
                )
            # advisory mode: allow but record nothing extra
        return user

    return _dep


def has_role(user: dict[str, Any], min_role: str) -> bool:
    """Return True if ``user`` meets the minimum role (ignores enforcement)."""
    return _ROLE_LEVEL.get(user.get("role", "viewer"), 0) >= _ROLE_LEVEL[min_role]
