"""Request-scoped Pydantic AI model factory.

Fireworks and self-hosted AMD/vLLM use Pydantic AI's OpenAI-compatible provider.
Provider hosts and model ids are never hardcoded; environment injection is
required for keys, base URLs, and the comma-separated model allow-list.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from core.config import settings
from core.runtime_key import effective_api_key, llm_active, llm_provider
from core.runtime_settings import runtime_settings


def _allowed_models() -> list[str]:
    """Return the harness-injected Fireworks model allow-list."""
    raw = os.environ.get("ALLOWED_MODELS", settings.allowed_models)
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        raise RuntimeError("ALLOWED_MODELS is empty or unset - harness must inject this")
    return models


def _model_size_score(model_id: str) -> float:
    """Best-effort size ranking from an injected model id, with no id assumptions."""
    scores: list[float] = []
    for value, suffix in re.findall(r"(\d+(?:\.\d+)?)\s*([bBmM])", model_id):
        multiplier = 1_000.0 if suffix.lower() == "b" else 1.0
        scores.append(float(value) * multiplier)
    return max(scores, default=0.0)


def pick_model_for_role(role: str, models: list[str]) -> str:
    """Pick a model from ``models`` for ``role`` without assuming literal ids."""
    if not models:
        raise RuntimeError("ALLOWED_MODELS is empty or unset - harness must inject this")

    unique = list(dict.fromkeys(models))
    gemma_model = os.environ.get("FIREWORKS_GEMMA_MODEL", settings.fireworks_gemma_model).strip()
    serving_mode = (
        os.environ.get("FIREWORKS_SERVING_MODE", settings.fireworks_serving_mode).strip().lower()
    )
    if (
        gemma_model in unique
        and serving_mode in {"deploy_on_demand", "dedicated"}
        and any(token in role.lower() for token in ("reason", "vision", "multimodal", "synthesis"))
    ):
        return gemma_model
    if gemma_model in unique and serving_mode == "serverless" and len(unique) > 1:
        unique = [model for model in unique if model != gemma_model]
    selected = runtime_settings.selected_model()
    if runtime_settings.active and selected in unique:
        return selected
    ranked = sorted(enumerate(unique), key=lambda item: (_model_size_score(item[1]), item[0]))
    role_key = role.lower()
    small_roles = ("triage", "classif", "skill", "validator", "fast")
    large_roles = (
        "policy",
        "rag",
        "chat",
        "resume",
        "attrition",
        "retention",
        "synthesis",
    )

    if any(token in role_key for token in small_roles):
        return ranked[0][1] if ranked[0][0] != ranked[-1][0] else unique[0]
    if any(token in role_key for token in large_roles):
        return ranked[-1][1]
    return unique[0]


def fireworks_model_for(
    role: str = "default",
    api_key: str | None = None,
    session_id: str | None = None,
) -> Any:
    """Build a Fireworks OpenAI-compatible Pydantic AI model for ``role``.

    Environment is intentionally strict in submission mode: missing key, base URL
    or allow-list should fail loudly instead of silently drifting to another
    provider or a baked-in model id.
    """
    key = (api_key or os.environ.get("FIREWORKS_API_KEY", settings.fireworks_api_key)).strip()
    base_url = os.environ.get("FIREWORKS_BASE_URL", settings.fireworks_base_url).strip()
    if not key:
        raise RuntimeError("FIREWORKS_API_KEY is empty or unset")
    if not base_url:
        raise RuntimeError("FIREWORKS_BASE_URL is empty or unset")
    model_id = pick_model_for_role(role, _allowed_models())

    try:
        from pydantic_ai.models.openai import OpenAIChatModel
    except ImportError:  # pragma: no cover - compatibility with older pydantic-ai
        from pydantic_ai.models.openai import OpenAIModel as OpenAIChatModel
    from openai import AsyncOpenAI
    from pydantic_ai.providers.openai import OpenAIProvider

    from core.fireworks import client_headers

    headers = client_headers(session_id) if settings.fireworks_session_affinity else {}
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=key,
        max_retries=max(0, settings.fireworks_max_retries),
        default_headers=headers or None,
    )
    provider = OpenAIProvider(openai_client=client)
    return OpenAIChatModel(model_id, provider=provider)


def amd_vllm_model_for(role: str = "default", api_key: str | None = None) -> Any:
    """Build the self-hosted AMD/vLLM model without host or model defaults."""
    key = (api_key or os.environ.get("AMD_VLLM_API_KEY", settings.amd_vllm_api_key)).strip()
    base_url = os.environ.get("AMD_VLLM_BASE_URL", settings.amd_vllm_base_url).strip()
    if not key:
        raise RuntimeError("AMD_VLLM_API_KEY is empty or unset")
    if not base_url:
        raise RuntimeError("AMD_VLLM_BASE_URL is empty or unset")
    model_id = pick_model_for_role(role, _allowed_models())

    try:
        from pydantic_ai.models.openai import OpenAIChatModel
    except ImportError:  # pragma: no cover
        from pydantic_ai.models.openai import OpenAIModel as OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = OpenAIProvider(base_url=base_url, api_key=key)
    return OpenAIChatModel(model_id, provider=provider)


def anthropic_model_for_key(api_key: str | None) -> Any | None:
    """Build an Anthropic model bound to ``api_key`` for legacy/local mode."""
    if not api_key:
        return None
    try:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
    except Exception:  # noqa: BLE001 - optional dep absent -> caller falls back
        return None
    model_id = runtime_settings.selected_model() if runtime_settings.active else ""
    return AnthropicModel(
        model_id or settings.claude_model, provider=AnthropicProvider(api_key=api_key)
    )


def model_for_key(
    api_key: str | None,
    role: str = "default",
    session_id: str | None = None,
) -> Any | None:
    """Build a Pydantic AI model for the configured provider."""
    if not api_key:
        return None
    if llm_provider() == "fireworks":
        return fireworks_model_for(role=role, api_key=api_key, session_id=session_id)
    if llm_provider() == "amd_vllm":
        return amd_vllm_model_for(role=role, api_key=api_key)
    return anthropic_model_for_key(api_key)


def get_request_scoped_model(
    role: str = "default",
    session_id: str | None = None,
) -> Any | None:
    """Return the live model for this request, or ``None`` for deterministic mode."""
    if not llm_active():
        return None
    if session_id is None:
        return model_for_key(effective_api_key(), role=role)
    return model_for_key(effective_api_key(), role=role, session_id=session_id)


def get_request_scoped_anthropic_model() -> Any | None:
    """Backward-compatible alias for older call sites."""
    return get_request_scoped_model()


def crewai_llm_for(role: str = "synthesis", model_id: str | None = None) -> Any:
    """Build CrewAI's OpenAI-compatible adapter through the provider boundary.

    Crew modules receive only this configured ``BaseLLM`` instance. They never
    construct SDK clients, choose arbitrary models, or read provider secrets.
    The same adapter works with Fireworks and a self-hosted AMD/vLLM endpoint.
    """
    if not llm_active():
        raise RuntimeError("live LLM provider is not configured")

    models = _allowed_models()
    selected_model = model_id or pick_model_for_role(role, models)
    if selected_model not in models:
        raise RuntimeError("CrewAI model must be present in ALLOWED_MODELS")

    provider = llm_provider()
    if provider not in {"fireworks", "amd_vllm"}:
        raise RuntimeError("CrewAI live execution requires Fireworks or AMD/vLLM")
    base_url = os.environ.get(
        "FIREWORKS_BASE_URL" if provider == "fireworks" else "AMD_VLLM_BASE_URL",
        settings.fireworks_base_url if provider == "fireworks" else settings.amd_vllm_base_url,
    ).strip()
    if not base_url:
        raise RuntimeError(f"{provider} base URL is empty")

    from crewai import BaseLLM

    class OpenAICompatibleCrewLLM(BaseLLM):
        """CrewAI adapter backed by the centrally configured provider endpoint."""

        def __init__(self, *, model: str, api_key: str, endpoint: str) -> None:
            super().__init__(model=model, temperature=0.0)
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key,
                base_url=endpoint,
                max_retries=max(0, settings.fireworks_max_retries),
                timeout=30.0,
            )

        def call(
            self,
            messages: str | list[dict[str, Any]],
            tools: list[dict[str, Any]] | None = None,
            callbacks: list[Any] | None = None,
            available_functions: dict[str, Any] | None = None,
        ) -> str:
            del callbacks
            normalized = (
                [{"role": "user", "content": messages}]
                if isinstance(messages, str)
                else list(messages)
            )
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": normalized,
                "temperature": self.temperature,
            }
            if tools:
                kwargs["tools"] = tools
            stop = getattr(self, "stop", None)
            if stop:
                kwargs["stop"] = stop
            response = self._client.chat.completions.create(**kwargs)
            _record_response_usage(response, model_id=self.model)
            message = response.choices[0].message
            if message.tool_calls and available_functions:
                normalized.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [item.model_dump() for item in message.tool_calls],
                    }
                )
                for tool_call in message.tool_calls:
                    function = available_functions.get(tool_call.function.name)
                    if function is None:
                        continue
                    arguments = json.loads(tool_call.function.arguments or "{}")
                    result = function(**arguments)
                    normalized.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": str(result),
                        }
                    )
                return self.call(
                    normalized,
                    tools,
                    available_functions=available_functions,
                )
            return message.content or ""

        def supports_function_calling(self) -> bool:
            return True

        def supports_stop_words(self) -> bool:
            return True

        def get_context_window_size(self) -> int:
            return 32_768

    return OpenAICompatibleCrewLLM(
        model=selected_model,
        api_key=effective_api_key(),
        endpoint=base_url,
    )


async def run_fireworks_chat_body(
    body: dict[str, Any],
    *,
    api_key: str | None = None,
    session_id: str | None = None,
) -> str:
    """Execute one prevalidated multimodal/structured Fireworks request."""
    from core.fireworks import client_headers, validate_model

    started_at = time.perf_counter()
    model_id = validate_model(str(body.get("model", "")))
    key = (api_key or effective_api_key()).strip()
    base_url = os.environ.get("FIREWORKS_BASE_URL", settings.fireworks_base_url).strip()
    if llm_provider() != "fireworks":
        raise RuntimeError("multimodal resume parsing requires LLM_PROVIDER=fireworks")
    if not key:
        raise RuntimeError("FIREWORKS_API_KEY is empty or unset")
    if not base_url:
        raise RuntimeError("FIREWORKS_BASE_URL is empty or unset")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=base_url,
        api_key=key,
        max_retries=max(0, settings.fireworks_max_retries),
        default_headers=client_headers(session_id) or None,
    )
    request_body = {**body, "model": model_id}
    request_body.pop("x_preflight_budget", None)
    provider_options = {}
    if "top_k" in request_body:
        provider_options["top_k"] = request_body.pop("top_k")
    if provider_options:
        request_body["extra_body"] = provider_options
    try:
        response = await client.chat.completions.create(**request_body)
    finally:
        await client.close()
    if not response.choices:
        raise RuntimeError("Fireworks returned no completion choices")
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Fireworks returned an empty structured response")
    token_count = _response_token_count(response)
    _record_response_usage(response, model_id=model_id)
    response_format = request_body.get("response_format", {})
    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        from pydantic import ValidationError

        from core.a2a_envelope import build_and_record_envelope
        from core.fireworks_certifier import CertifiedResult, FireworksOutputCertifier

        json_schema = response_format.get("json_schema", {})
        schema = json_schema.get("schema") if isinstance(json_schema, dict) else None
        if not isinstance(schema, dict):
            raise RuntimeError("Fireworks structured request is missing a JSON schema")
        result = FireworksOutputCertifier().certify(
            content,
            {
                "schema": schema,
                "require_pii_free": True,
            },
        )
        if isinstance(result, ValidationError):
            build_and_record_envelope(
                source_agent="fireworks_serverless",
                target_agent="structured_response_consumer",
                certification=CertifiedResult(
                    is_valid=False,
                    cleaned_output="{}",
                    confidence=0.0,
                    violations=["schema_validation_failed"],
                ),
                started_at=started_at,
                token_count=token_count,
                model_id=model_id,
            )
            raise RuntimeError("Fireworks response failed certifier schema validation") from result
        build_and_record_envelope(
            source_agent="fireworks_serverless",
            target_agent="structured_response_consumer",
            certification=result,
            started_at=started_at,
            token_count=token_count,
            model_id=model_id,
        )
        if not isinstance(result, CertifiedResult) or not result.is_valid:
            violations = result.violations if isinstance(result, CertifiedResult) else []
            raise RuntimeError(f"Fireworks response failed certification: {violations}")
    return content


def _response_token_count(response: Any) -> int | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    total = getattr(usage, "total_tokens", None)
    if total is not None:
        return int(total)
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    total = prompt + completion
    return int(total) if total else None


def _record_response_usage(response: Any, *, model_id: str) -> None:
    """Capture provider-returned usage fields without retaining request content."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    details = getattr(usage, "prompt_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
    from core.cost_attribution import record_provider_usage

    record_provider_usage(
        model_id=model_id,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_prompt_tokens=cached,
    )


def run_text_completion(
    prompt: str,
    *,
    role: str = "default",
    system_prompt: str = "",
    max_tokens: int = 600,
    temperature: float = 0.0,
) -> str | None:
    """Run a bounded text completion through the configured live provider."""
    from core.cost_guard import TokenBudgetGuard
    from core.genai_lifecycle import controlled_parameters, transform_fuzzy_input

    if runtime_settings.active:
        max_tokens = min(max_tokens, int(runtime_settings.value("max_tokens", max_tokens)))
        temperature = float(runtime_settings.value("temperature", temperature))
    TokenBudgetGuard(
        max_input_tokens=settings.max_llm_input_tokens,
        max_output_tokens=settings.max_llm_output_tokens,
    ).validate_text(prompt, max_output_tokens=max_tokens)
    model = get_request_scoped_model(role=role)
    if model is None:
        return None
    prepared = transform_fuzzy_input(prompt, role=role)
    parameters = controlled_parameters(
        role,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    try:
        from pydantic_ai import Agent

        agent: Agent[None, str] = Agent(model, system_prompt=system_prompt)
        result = agent.run_sync(
            prepared.text,
            model_settings=parameters,
        )
        return str(result.output)
    except Exception:  # noqa: BLE001 - caller decides the deterministic fallback
        return None
