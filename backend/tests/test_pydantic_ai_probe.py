"""Probe: how does the *installed* Pydantic AI version take a dynamic BYOK key?

This answers the migration's one risky assumption before any classifier code is
written (the "verify the gotcha first" approach). It is CI-safe: it only
*constructs* objects and introspects signatures — it never makes a network call
and needs no real API key.

Findings (pydantic-ai-slim 1.104.0), asserted below so a version bump that
changes them fails loudly:

  1. ``model_settings={'api_key': ...}`` does NOT work — ``ModelSettings`` holds
     only inference params (max_tokens, temperature, timeout, …), not credentials.
  2. The dynamic key goes through a **per-request instance wrapper**:
     ``AnthropicModel(name, provider=AnthropicProvider(api_key=key))``.
     Construction makes no network call, so it is cheap to build per request.
  3. Typed output (``Agent(model, output_type=<BaseModel with Literal>)``) is
     supported → the classifier is schema-constrained, not string-scraped.
  4. The validation-retry loop (the token-cost risk) is bounded: both
     ``Agent(retries=...)`` and ``Agent.run(..., retries=...)`` exist, and
     ``run(model=...)`` lets one shared agent take a per-request BYOK model.
"""

from __future__ import annotations

import inspect
from typing import Literal

import pytest
from pydantic import BaseModel

pytest.importorskip("pydantic_ai")  # skip cleanly if the optional dep is absent

from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.models.anthropic import AnthropicModel  # noqa: E402
from pydantic_ai.providers.anthropic import AnthropicProvider  # noqa: E402
from pydantic_ai.settings import ModelSettings  # noqa: E402

_FAKE_KEY = "fixture-anthropic-key-not-real"


def test_api_key_is_not_a_model_setting() -> None:
    """The model_settings={'api_key': ...} hypothesis is invalid — credentials
    are not inference settings."""
    assert "api_key" not in getattr(ModelSettings, "__annotations__", {})


def test_dynamic_key_via_provider_wrapper_constructs_without_network() -> None:
    """The supported path: build a provider with the key, no network on construct."""
    model = AnthropicModel(
        "claude-sonnet-4-20250514", provider=AnthropicProvider(api_key=_FAKE_KEY)
    )
    assert isinstance(model, AnthropicModel)


def test_typed_output_agent_is_schema_constrained() -> None:
    """A Literal-typed result model can be wired as the agent's output type."""

    class TriageDecision(BaseModel):
        category: Literal["BENEFITS", "POLICY", "ONBOARDING", "PERFORMANCE", "COMPLIANCE", "URGENT"]
        confidence: float
        rationale: str

    model = AnthropicModel(
        "claude-sonnet-4-20250514", provider=AnthropicProvider(api_key=_FAKE_KEY)
    )
    agent = Agent(model, output_type=TriageDecision)
    assert agent is not None


def test_retry_loop_is_bounded() -> None:
    """Retry knobs exist so the validation self-heal can't multiply tokens unchecked."""
    assert "retries" in inspect.signature(Agent.__init__).parameters
    run_params = inspect.signature(Agent.run).parameters
    assert "retries" in run_params  # cap per-call self-heal
    assert "model" in run_params  # one agent + per-request BYOK model override


def test_legacy_chat_agent_api_key_kwarg_is_unsupported() -> None:
    """Regression note: the current chat_agent passes AnthropicModel(api_key=...),
    which 1.104.0 rejects — so that path silently degrades. The migration's
    per-request provider helper should replace it."""
    with pytest.raises(TypeError):
        AnthropicModel("claude-sonnet-4-20250514", api_key=_FAKE_KEY)
