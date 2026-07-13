"""BYOK key verification — a fast pre-flight check against the provider.

The dashboard hits this the moment a visitor saves their key on the Launchpad so
the pulse indicator can mean **"verified and authenticating"**, not merely
"well-formed". The key is read from the request-scoped contextvar (set by the
``_byok_key`` middleware from the ``X-Client-LLM-Key`` header) — it is never
taken from the body, never logged, never persisted.

Verification is a cheap, no-token-spend model-list request against the configured
provider with a short timeout. Outcomes:
  * ``verified``     — provider accepted the key,
  * ``rejected``     — provider rejected it (bad/expired key),
  * ``malformed``    — fails a basic format check (don't even call out),
  * ``missing``      — no key on the request,
  * ``unverifiable`` — provider unreachable / SDK absent (network, offline demo).
  * ``unsupported``  — the active route uses a private service credential rather
    than a visitor-owned hosted-provider key (currently AMD/vLLM).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter

from api.responses import ok
from core.config import settings
from core.runtime_key import byok_supported, llm_provider, looks_like_key, request_api_key

router = APIRouter(prefix="/byok", tags=["byok"])


def _verify_sync(key: str) -> dict[str, Any]:
    """Blocking provider check (runs in a thread). Never raises."""
    provider = llm_provider()
    if not byok_supported():
        return {
            "valid": False,
            "status": "unsupported",
            "provider": provider,
            "detail": "browser BYOK is disabled for the private AMD/vLLM service route",
        }
    if provider == "fireworks":
        base_url = os.environ.get("FIREWORKS_BASE_URL", settings.fireworks_base_url).rstrip("/")
        if not base_url:
            return {
                "valid": False,
                "status": "unverifiable",
                "provider": provider,
                "detail": "base URL missing",
            }
        try:
            import httpx

            resp = httpx.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=6.0,
            )
            if resp.status_code < 400:
                return {
                    "valid": True,
                    "status": "verified",
                    "provider": provider,
                    "detail": "key accepted by provider",
                }
            if resp.status_code in (401, 403):
                return {
                    "valid": False,
                    "status": "rejected",
                    "provider": provider,
                    "detail": "provider rejected the key",
                }
            return {
                "valid": False,
                "status": "unverifiable",
                "provider": provider,
                "detail": "provider unreachable",
            }
        except Exception:  # noqa: BLE001
            return {
                "valid": False,
                "status": "unverifiable",
                "provider": provider,
                "detail": "provider unreachable",
            }

    try:
        import anthropic
    except Exception:  # noqa: BLE001 - SDK not installed in the lean image
        return {
            "valid": False,
            "status": "unverifiable",
            "provider": provider or "anthropic",
            "detail": "verification unavailable",
        }
    try:
        client = anthropic.Anthropic(api_key=key, timeout=6.0, max_retries=0)
        client.models.list()  # GET /v1/models — auth-checked, no token spend
        return {
            "valid": True,
            "status": "verified",
            "provider": provider or "anthropic",
            "detail": "key accepted by provider",
        }
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__.lower()
        # Distinguish "the provider said no" from "we couldn't reach the provider".
        if "auth" in name or "permission" in name or "401" in str(exc) or "403" in str(exc):
            return {
                "valid": False,
                "status": "rejected",
                "provider": provider or "anthropic",
                "detail": "provider rejected the key",
            }
        return {
            "valid": False,
            "status": "unverifiable",
            "provider": provider or "anthropic",
            "detail": "provider unreachable",
        }


@router.get("/verify")
async def verify() -> dict[str, Any]:
    """Verify the request's BYOK key against the provider (no body, header only)."""
    key = request_api_key()
    provider = llm_provider() or "anthropic"
    if not byok_supported():
        return ok(
            {
                "valid": False,
                "status": "unsupported",
                "provider": provider,
                "detail": "browser BYOK is disabled for the private AMD/vLLM service route",
            }
        )
    if not key:
        return ok(
            {
                "valid": False,
                "status": "missing",
                "provider": provider,
                "detail": "no key supplied",
            }
        )
    if not looks_like_key(key):
        return ok(
            {
                "valid": False,
                "status": "malformed",
                "provider": provider,
                "detail": "key format looks invalid",
            }
        )
    result = await asyncio.to_thread(_verify_sync, key)
    return ok(result)
