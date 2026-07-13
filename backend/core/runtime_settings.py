"""Durable operator controls projected into synchronous AI request paths."""

from __future__ import annotations

import json
import os
from asyncio import Lock
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.memory import memory
from core.secret_store import decrypt_api_keys, encrypt_api_keys

MODEL_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "accounts/fireworks/models/kimi-k2p6",
        "label": "Kimi K2.6 (Serverless)",
        "family": "Kimi",
    },
    {
        "id": "accounts/fireworks/models/gemma-4-26b-a4b-it",
        "label": "Gemma 4 26B (Deploy-on-Demand)",
        "family": "Gemma",
    },
    {
        "id": "accounts/fireworks/models/kimi-k2p7-code",
        "label": "Kimi K2.7 Code (Serverless)",
        "family": "Kimi",
    },
)

DEFAULTS: dict[str, Any] = {
    "provider": "",
    "selected_model": "",
    "temperature": 0.2,
    "max_tokens": 1000,
    "reasoning_effort": 0.3,
    "daily_budget_usd": 0.0,
    "caching_enabled": True,
    "batch_processing_enabled": False,
    "pii_redaction_enabled": True,
    "human_review_required": True,
}


class RuntimeSettings:
    """Own the process-local snapshot and its encrypted database projection."""

    def __init__(self) -> None:
        """Initialise safe defaults without touching the database."""
        self._values = dict(DEFAULTS)
        self._api_keys: dict[str, str] = {}
        self._loaded = False
        self._active = False
        self._lock = Lock()

    async def load(self) -> dict[str, Any]:
        """Load the persisted operator settings once, preserving env defaults."""
        async with self._lock:
            if self._loaded:
                return self.public()
            row = await memory.get_runtime_settings()
            if row:
                try:
                    payload = json.loads(row.get("payload") or "{}")
                    self._values.update({key: payload[key] for key in DEFAULTS if key in payload})
                except (TypeError, ValueError):
                    pass
                self._api_keys = decrypt_api_keys(row.get("encrypted_api_keys"))
                self._active = True
            self._discard_unconfigured_selected_model()
            self._loaded = True
            return self.public()

    def _configured_models(self) -> list[str]:
        """Return deployment-allowlisted model IDs without exposing secrets."""
        raw = os.environ.get("ALLOWED_MODELS", settings.allowed_models)
        return list(dict.fromkeys(value.strip() for value in raw.split(",") if value.strip()))

    def model_options(self) -> list[dict[str, Any]]:
        """Return catalog entries annotated with live allow-list availability."""
        configured = self._configured_models()
        entries = list(MODEL_CATALOG)
        for model_id in configured:
            if not any(item["id"] == model_id for item in entries):
                entries.append(
                    {"id": model_id, "label": model_id.rsplit("/", 1)[-1], "family": "Configured"}
                )
        return [{**item, "live_allowed": item["id"] in configured} for item in entries]

    def _discard_unconfigured_selected_model(self) -> None:
        """Drop stale saved model IDs that are no longer deployment-allowlisted."""
        configured = self._configured_models()
        selected = str(self._values.get("selected_model") or "")
        if configured and selected and selected not in configured:
            self._values["selected_model"] = ""

    def public(self) -> dict[str, Any]:
        """Return settings safe for the browser, never plaintext credentials."""
        provider = self.provider()
        configured_env = {
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY", settings.anthropic_api_key)),
            "fireworks": bool(os.environ.get("FIREWORKS_API_KEY", settings.fireworks_api_key)),
            "amd_vllm": bool(os.environ.get("AMD_VLLM_API_KEY", settings.amd_vllm_api_key)),
        }
        key_status = {}
        for name in ("anthropic", "fireworks", "amd_vllm"):
            key = self._api_keys.get(name, "")
            env_key = configured_env[name]
            key_status[name] = {
                "configured": bool(key or env_key),
                "source": "settings" if key else ("environment" if env_key else "none"),
                "masked": f"••••{key[-4:]}" if key else ("environment-managed" if env_key else ""),
            }
        return {
            **self._values,
            "provider": provider,
            "api_keys": key_status,
            "models": self.model_options(),
            "updated_at": self._values.get("updated_at"),
        }

    def provider(self) -> str:
        """Return the selected provider or the deployment environment provider."""
        return str(
            self._values.get("provider")
            or os.environ.get("LLM_PROVIDER", settings.llm_provider)
            or "deterministic"
        )

    def selected_model(self) -> str:
        """Return the operator-selected model, if any."""
        return str(self._values.get("selected_model") or "")

    @property
    def loaded(self) -> bool:
        """Whether the persisted snapshot has been loaded for this process."""
        return self._loaded

    @property
    def active(self) -> bool:
        """Whether an operator save/reset should override environment defaults."""
        return self._active

    def value(self, name: str, fallback: Any = None) -> Any:
        """Read one runtime setting synchronously from the loaded snapshot."""
        return self._values.get(name, fallback)

    def api_key_for(self, provider: str) -> str:
        """Return a persisted provider key, if one exists in process memory."""
        return self._api_keys.get(provider, "")

    async def save(
        self, values: dict[str, Any], api_key: str | None = None, clear_key: bool = False
    ) -> dict[str, Any]:
        """Validate-free persistence primitive used by the API route."""
        async with self._lock:
            self._values.update({key: values[key] for key in DEFAULTS if key in values})
            self._discard_unconfigured_selected_model()
            provider = str(self._values.get("provider") or "")
            if clear_key and provider:
                self._api_keys.pop(provider, None)
            if api_key and provider:
                self._api_keys[provider] = api_key
            self._values["updated_at"] = datetime.now(timezone.utc).isoformat()
            await memory.save_runtime_settings(self._values, encrypt_api_keys(self._api_keys))
            self._loaded = True
            self._active = True
            return self.public()

    async def reset(self) -> dict[str, Any]:
        """Restore defaults and remove all operator-managed encrypted keys."""
        async with self._lock:
            self._values = dict(DEFAULTS)
            self._api_keys = {}
            self._values["updated_at"] = datetime.now(timezone.utc).isoformat()
            await memory.save_runtime_settings(self._values, encrypt_api_keys({}))
            self._loaded = True
            self._active = True
            return self.public()


runtime_settings = RuntimeSettings()
