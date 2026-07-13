"""Manager-controlled AI runtime settings with encrypted credential handling."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.responses import ok
from core.config import settings as env_settings
from core.runtime_settings import runtime_settings
from core.security import require_role

router = APIRouter(prefix="/settings", tags=["settings"])

Provider = Literal["", "anthropic", "fireworks", "amd_vllm", "deterministic"]


class RuntimeSettingsUpdate(BaseModel):
    """Validated operator settings payload; provider keys are never echoed."""

    provider: Provider | None = None
    selected_model: str | None = Field(default=None, max_length=255)
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=64, le=4096)
    reasoning_effort: float | None = Field(default=None, ge=0.0, le=1.0)
    daily_budget_usd: float | None = Field(default=None, ge=0.0, le=1_000_000.0)
    caching_enabled: bool | None = None
    batch_processing_enabled: bool | None = None
    pii_redaction_enabled: bool | None = None
    human_review_required: bool | None = None
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False


class ConnectionTestRequest(BaseModel):
    """Provider connection probe payload; the key is used only for this request."""

    provider: Provider
    model: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=500)


def _env_key(provider: str) -> str:
    """Read an environment-managed key for connection testing."""
    if provider == "anthropic":
        return env_settings.anthropic_api_key
    if provider == "fireworks":
        return env_settings.fireworks_api_key
    if provider == "amd_vllm":
        return env_settings.amd_vllm_api_key
    return ""


async def _probe(provider: str, key: str) -> tuple[bool, str]:
    """Perform a no-token model-list probe against the selected provider."""
    if provider in {"", "deterministic"}:
        return True, "deterministic local runtime is available"
    if not key:
        return False, "no API key is configured"
    try:
        if provider == "anthropic":
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=key, timeout=6.0, max_retries=0)
            try:
                await client.models.list(limit=1)
            finally:
                await client.close()
            return True, "provider accepted the connection"

        import httpx

        headers = {"Authorization": f"Bearer {key}"}
        if provider == "fireworks":
            url = f"{env_settings.fireworks_base_url.rstrip('/')}/models"
        else:
            url = f"{env_settings.amd_vllm_base_url.rstrip('/')}/models"
        if not url or url == "/models":
            return False, "provider base URL is not configured"
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(url, headers=headers)
        if response.status_code in {401, 403}:
            return False, "provider rejected the key"
        if response.status_code >= 400:
            return False, "provider connection returned an error"
        return True, "provider accepted the connection"
    except Exception:  # noqa: BLE001 - network details stay server-side
        return False, "provider is unreachable from this runtime"


@router.get("")
async def get_settings(_: dict[str, Any] = Depends(require_role("manager"))) -> dict[str, Any]:
    """Return current non-secret AI controls and masked key status."""
    await runtime_settings.load()
    return ok(runtime_settings.public())


@router.put("")
async def update_settings(
    body: RuntimeSettingsUpdate,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Persist validated AI controls and optionally encrypt one provider key."""
    values = body.model_dump(exclude_none=True, exclude={"api_key", "clear_api_key"})
    if body.provider == "deterministic":
        values["selected_model"] = ""
    result = await runtime_settings.save(values, api_key=body.api_key, clear_key=body.clear_api_key)
    return ok(result)


@router.post("/reset")
async def reset_settings(_: dict[str, Any] = Depends(require_role("manager"))) -> dict[str, Any]:
    """Restore safe defaults and erase operator-managed encrypted keys."""
    return ok(await runtime_settings.reset())


@router.post("/test-connection")
async def test_connection(
    body: ConnectionTestRequest,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Measure a no-token provider handshake without persisting the supplied key."""
    await runtime_settings.load()
    started = time.perf_counter()
    key = body.api_key or runtime_settings.api_key_for(body.provider) or _env_key(body.provider)
    valid, detail = await _probe(body.provider, key)
    return ok(
        {
            "provider": body.provider or "deterministic",
            "model": body.model or runtime_settings.selected_model() or None,
            "valid": valid,
            "detail": detail,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "persisted": False,
        }
    )
