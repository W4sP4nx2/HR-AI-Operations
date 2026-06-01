"""Request-scoped Pydantic AI model factory (Anthropic) — BYOK-safe.

One place that turns *this request's* effective API key into a Pydantic AI model,
used by both the chat assistant and the triage classifier.

Why a fresh provider per call: in pydantic-ai 1.104 ``AnthropicModel`` has **no**
``api_key`` argument (and ``model_settings`` carries inference params, not
credentials), so the only correct way to inject a dynamic key is
``AnthropicModel(name, provider=AnthropicProvider(api_key=key))``. Construction
makes **no network call**, so building one per request is cheap and keeps the
BYOK key bound to the single request frame — verified by
``tests/test_pydantic_ai_probe.py``.
"""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.runtime_key import effective_api_key, llm_active


def anthropic_model_for_key(api_key: str | None) -> Any | None:
    """Build an ``AnthropicModel`` bound to ``api_key`` (or ``None`` if unusable).

    Returns ``None`` when there is no key or pydantic-ai isn't installed, so every
    caller has a single, uniform "no live model → fall back deterministically"
    signal.
    """
    if not api_key:
        return None
    try:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
    except Exception:  # noqa: BLE001 — optional dep absent → caller falls back
        return None
    return AnthropicModel(settings.claude_model, provider=AnthropicProvider(api_key=api_key))


def get_request_scoped_anthropic_model() -> Any | None:
    """The model to use for the current request, honoring BYOK + the gate.

    ``None`` → make **no** live LLM call (use the deterministic baseline). Honors
    ``llm_active`` (MOCK_LLM / DEMO_MODE / BYOK opt-in) and reads the request-scoped
    key, so a visitor's key never leaks past their request and the server key is
    never used when gating says otherwise.
    """
    if not llm_active():
        return None
    return anthropic_model_for_key(effective_api_key())
