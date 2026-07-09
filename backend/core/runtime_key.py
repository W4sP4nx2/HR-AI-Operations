"""Request-scoped LLM key (Bring-Your-Own-Key) — ephemeral, never persisted.

A visitor can try the hosted demo with *their own* API key by sending it in a
request header. The key lives only for the lifetime of that request, in a
``contextvars.ContextVar`` bound to the ASGI task — it is **never written to the
database, the audit log, or any file**, and is cleared when the request ends.

LLM call-sites read :func:`effective_api_key` (request key → else the server's
configured key → else empty), so they transparently use the visitor's key when
present and otherwise fall back to the deterministic, no-key baseline.

``contextvars`` propagate across ``asyncio.to_thread`` (PEP 567), so the synth /
classifier calls that agents offload to threads still see the request key.
"""

from __future__ import annotations

import contextvars
import os

from core.config import settings

_request_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_api_key", default=None
)


def set_request_api_key(key: str | None) -> contextvars.Token:
    """Bind a key to the current request context; returns a reset token."""
    return _request_api_key.set(key or None)


def reset_request_api_key(token: contextvars.Token) -> None:
    """Clear the request key (call in a ``finally`` so it never leaks)."""
    _request_api_key.reset(token)


def request_api_key() -> str | None:
    """The caller-supplied key for this request, if any (no server fallback)."""
    return _request_api_key.get()


def effective_api_key() -> str:
    """The key LLM call-sites should use: request key, else the server's, else ''."""
    return _request_api_key.get() or server_api_key()


def llm_provider() -> str:
    """Configured LLM provider, read live so harness-injected env wins."""
    return (os.environ.get("LLM_PROVIDER") or settings.llm_provider or "").strip().lower()


def server_api_key() -> str:
    """Server-owned key for the configured provider."""
    if llm_provider() == "fireworks":
        return os.environ.get("FIREWORKS_API_KEY", settings.fireworks_api_key)
    if llm_provider() == "amd_vllm":
        return os.environ.get("AMD_VLLM_API_KEY", settings.amd_vllm_api_key)
    return os.environ.get("ANTHROPIC_API_KEY", settings.anthropic_api_key)


def llm_config_issues() -> list[str]:
    """Non-secret provider configuration problems visible in health/startup logs."""
    provider = llm_provider()
    if provider == "fireworks":
        issues: list[str] = []
        if not looks_like_key(server_api_key()):
            issues.append("FIREWORKS_API_KEY is missing or malformed")
        if not os.environ.get("FIREWORKS_BASE_URL", settings.fireworks_base_url).strip():
            issues.append("FIREWORKS_BASE_URL is missing")
        if not os.environ.get("ALLOWED_MODELS", settings.allowed_models).strip():
            issues.append("ALLOWED_MODELS is missing")
        return issues
    if provider == "amd_vllm":
        issues = []
        if not looks_like_key(server_api_key()):
            issues.append("AMD_VLLM_API_KEY is missing or malformed")
        if not os.environ.get("AMD_VLLM_BASE_URL", settings.amd_vllm_base_url).strip():
            issues.append("AMD_VLLM_BASE_URL is missing")
        if not os.environ.get("ALLOWED_MODELS", settings.allowed_models).strip():
            issues.append("ALLOWED_MODELS is missing")
        return issues
    if provider not in ("", "anthropic"):
        return [f"LLM_PROVIDER '{provider}' is unsupported"]
    return []


def looks_like_key(value: str | None) -> bool:
    """Cheap, provider-agnostic sanity check (avoid treating junk as a key)."""
    return bool(value) and len(value) >= 16 and " " not in value


def llm_active() -> bool:
    """Whether a live LLM call should be made for the current request.

    True when a usable key exists AND either the visitor supplied their own key
    (they opted into the spend, so it overrides ``MOCK_LLM``/``DEMO_MODE`` cost
    guards) or the server is configured for live calls. False → deterministic
    baseline. This is the single gate every LLM call-site checks.
    """
    rk = request_api_key()
    if rk is not None:  # BYOK: visitor opted in — but only if it's plausibly a key
        return looks_like_key(rk)

    provider = llm_provider()
    if provider in ("fireworks", "amd_vllm"):
        # Provider-scored/self-hosted paths must not be silently short-circuited
        # by local showcase flags. Their required environment must be explicit.
        return not llm_config_issues()

    if not server_api_key():
        return False
    return not (settings.mock_llm or settings.demo_mode)
