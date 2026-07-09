"""Pure Fireworks workload planning and request-building helpers.

The module deliberately performs no network I/O. It lets CI validate routing,
structured-output, vision, batch, and scale-up contracts without an API key.
Live client construction remains centralized in :mod:`core.llm_factory`.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from core.config import settings

ServingMode = Literal["serverless", "batch", "dedicated"]

RESUME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": ["string", "null"]},
        "email": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "start_date": {"type": ["string", "null"]},
                    "end_date": {"type": ["string", "null"]},
                    "summary": {"type": ["string", "null"]},
                },
                "required": ["company", "title", "start_date", "end_date", "summary"],
                "additionalProperties": False,
            },
        },
        "education": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "name",
        "email",
        "phone",
        "skills",
        "experience",
        "education",
        "warnings",
    ],
    "additionalProperties": False,
}

USE_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "policy_qa",
        "mode": "serverless",
        "capabilities": ["embeddings", "prompt_cache", "tool_calling", "streaming"],
        "success": "grounded answer with policy citations and confidence",
    },
    {
        "id": "case_triage",
        "mode": "serverless",
        "capabilities": ["structured_output", "tool_calling"],
        "success": "schema-valid category, owner, priority, and rationale",
    },
    {
        "id": "resume_parsing",
        "mode": "serverless",
        "capabilities": ["vision", "structured_output"],
        "success": "field-level F1 measured against a governed golden set",
    },
    {
        "id": "bulk_resume_processing",
        "mode": "batch",
        "capabilities": ["vision", "structured_output", "prompt_cache"],
        "success": "complete JSONL results plus separately reviewed error rows",
    },
    {
        "id": "agent_evaluation",
        "mode": "batch",
        "capabilities": ["structured_output", "prompt_cache"],
        "success": "quality, bias, cost, and latency gates pass before promotion",
    },
    {
        "id": "fine_tuned_hr_extraction",
        "mode": "dedicated",
        "capabilities": ["lora", "autoscaling", "version_pinning"],
        "success": "governed baseline uplift justifies training and serving cost",
    },
)


def configured_models() -> list[str]:
    """Return the injected model allow-list without exposing any secret."""
    raw = os.environ.get("ALLOWED_MODELS", settings.allowed_models)
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def validate_model(model_id: str) -> str:
    """Require a non-empty model id from the deployment allow-list."""
    models = configured_models()
    if not models:
        raise RuntimeError("ALLOWED_MODELS is empty or unset")
    if model_id not in models:
        raise ValueError("model_id is not present in ALLOWED_MODELS")
    return model_id


def affinity_token(session_id: str | None) -> str | None:
    """Return a stable, non-PII cache-affinity token for one chat/session."""
    normalized = (session_id or "").strip()
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"hrcc-{digest[:32]}"


def client_headers(session_id: str | None) -> dict[str, str]:
    """Build optional Fireworks cache-locality headers."""
    token = affinity_token(session_id)
    return {"x-session-affinity": token} if token else {}


def choose_serving_mode(
    *,
    asynchronous: bool = False,
    custom_or_fine_tuned_model: bool = False,
    requires_reserved_capacity: bool = False,
) -> ServingMode:
    """Select the least complex Fireworks serving mode that meets the workload."""
    if asynchronous:
        return "batch"
    if custom_or_fine_tuned_model or requires_reserved_capacity:
        return "dedicated"
    return "serverless"


def build_chat_body(
    *,
    model_id: str,
    messages: Sequence[Mapping[str, Any]],
    max_tokens: int = 600,
    temperature: float = 0.0,
    schema_name: str | None = None,
    json_schema: Mapping[str, Any] | None = None,
    session_id: str | None = None,
    service_tier: Literal["standard", "priority"] = "standard",
    top_k: int | None = None,
    top_p: float | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    allowed_tool_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build a bounded OpenAI-compatible Fireworks chat request body."""
    from core.cost_guard import TokenBudgetGuard

    validate_model(model_id)
    if not messages:
        raise ValueError("messages must not be empty")
    if not 1 <= max_tokens <= 4096:
        raise ValueError("max_tokens must be between 1 and 4096")
    if not 0.0 <= temperature <= 1.0:
        raise ValueError("temperature must be between 0 and 1")
    if top_k is not None and not 0 <= top_k <= 100:
        raise ValueError("top_k must be between 0 and 100")
    if top_p is not None and not 0.0 <= top_p <= 1.0:
        raise ValueError("top_p must be between 0 and 1")
    if bool(schema_name) != bool(json_schema):
        raise ValueError("schema_name and json_schema must be supplied together")
    _validate_static_context_first(messages)
    budget = TokenBudgetGuard(
        max_input_tokens=settings.max_llm_input_tokens,
        max_output_tokens=settings.max_llm_output_tokens,
    ).validate_messages([dict(message) for message in messages], max_output_tokens=max_tokens)

    body: dict[str, Any] = {
        "model": model_id,
        "messages": [dict(message) for message in messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body["x_preflight_budget"] = {
        "input_tokens": budget.input_tokens,
        "estimated_total_tokens": budget.estimated_total_tokens,
    }
    affinity = affinity_token(session_id)
    if affinity:
        body["user"] = affinity
    if service_tier == "priority":
        body["service_tier"] = "priority"
    if top_k is not None:
        body["top_k"] = top_k
    if top_p is not None:
        body["top_p"] = top_p
    pruned_tools = prune_tool_schemas(tools or (), allowed_tool_names)
    if pruned_tools:
        body["tools"] = pruned_tools
    if json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": dict(json_schema)},
        }
    return body


def _validate_static_context_first(messages: Sequence[Mapping[str, Any]]) -> None:
    """Keep cacheable static context first for Fireworks prompt caching."""
    system_index = next(
        (index for index, message in enumerate(messages) if message.get("role") == "system"),
        None,
    )
    if system_index is not None and system_index != 0:
        raise ValueError("system prompt must be first for prompt-cache locality")


def prune_tool_schemas(
    tools: Sequence[Mapping[str, Any]],
    allowed_tool_names: Sequence[str] | None,
) -> list[dict[str, Any]]:
    """Remove unused OpenAI-compatible tool schemas before a request is built."""
    allowed = {name.strip() for name in (allowed_tool_names or []) if name.strip()}
    pruned: list[dict[str, Any]] = []
    for tool in tools:
        name = _tool_schema_name(tool)
        if allowed and name not in allowed:
            continue
        pruned.append(dict(tool))
    return pruned


def _tool_schema_name(tool: Mapping[str, Any]) -> str:
    function = tool.get("function")
    if isinstance(function, Mapping) and isinstance(function.get("name"), str):
        return function["name"]
    name = tool.get("name")
    return name if isinstance(name, str) else ""


def build_resume_vision_body(
    *,
    model_id: str,
    image_urls: Sequence[str],
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build a schema-constrained VLM request for converted resume pages."""
    if not image_urls:
        raise ValueError("at least one converted resume page is required")
    if len(image_urls) > 30:
        raise ValueError("Fireworks vision requests support at most 30 images")
    if any(not (url.startswith("data:image/") or url.startswith("https://")) for url in image_urls):
        raise ValueError("images must use HTTPS URLs or data:image URLs")
    if any(url.startswith("data:image/") and ";base64," not in url for url in image_urls):
        raise ValueError("data:image URLs must contain base64-encoded image data")
    base64_bytes = sum(len(url) for url in image_urls if url.startswith("data:image/"))
    if base64_bytes >= 10 * 1024 * 1024:
        raise ValueError("base64 image payload must remain below 10MB")

    content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": url}} for url in image_urls
    ]
    content.append(
        {
            "type": "text",
            "text": (
                "Extract this resume into JSON matching the supplied schema. "
                "Use null for unreadable scalar fields and record uncertainty in warnings."
            ),
        }
    )
    return build_chat_body(
        model_id=model_id,
        messages=[{"role": "user", "content": content}],
        max_tokens=1800,
        temperature=0.0,
        schema_name="ResumeExtraction",
        json_schema=RESUME_SCHEMA,
        session_id=session_id,
        top_k=20,
    )


def build_batch_jsonl(
    records: Iterable[Mapping[str, Any]],
    *,
    model_id: str,
    system_prompt: str,
    max_tokens: int = 800,
) -> str:
    """Build Fireworks-compatible JSONL for offline document/evaluation jobs."""
    validate_model(model_id)
    lines: list[str] = []
    seen: set[str] = set()
    for record in records:
        custom_id = str(record.get("custom_id", "")).strip()
        prompt = str(record.get("prompt", "")).strip()
        if not custom_id or not prompt:
            raise ValueError("each batch record needs custom_id and prompt")
        if custom_id in seen:
            raise ValueError(f"duplicate custom_id: {custom_id}")
        seen.add(custom_id)
        body = build_chat_body(
            model_id=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        # The Batch job selects the model; each dataset row contains only the
        # per-request parameters described by the Fireworks JSONL contract.
        body.pop("model", None)
        body.pop("x_preflight_budget", None)
        lines.append(json.dumps({"custom_id": custom_id, "body": body}, separators=(",", ":")))
    return "\n".join(lines) + ("\n" if lines else "")


def is_scale_up_response(status_code: int, payload: Mapping[str, Any]) -> bool:
    """Identify the dedicated-deployment scale-from-zero response."""
    error = payload.get("error")
    nested_code = error.get("code") if isinstance(error, Mapping) else None
    return status_code == 503 and (
        nested_code == "DEPLOYMENT_SCALING_UP" or payload.get("code") == "DEPLOYMENT_SCALING_UP"
    )


def is_scale_up_exception(exc: BaseException) -> bool:
    """Identify an OpenAI-compatible exception caused by scale-from-zero."""
    status_code = getattr(exc, "status_code", 0)
    body = getattr(exc, "body", {})
    if isinstance(body, Mapping) and is_scale_up_response(status_code, body):
        return True
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", 0) != 503:
        return False
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - error parsing must never hide the original error
        return False
    return isinstance(payload, Mapping) and is_scale_up_response(503, payload)


def scale_up_delays(
    retries: int,
    *,
    initial_seconds: float = 5.0,
    multiplier: float = 1.5,
    cap_seconds: float = 60.0,
) -> list[float]:
    """Return bounded exponential delays for a queue worker retry policy."""
    if retries < 0 or initial_seconds <= 0 or multiplier < 1 or cap_seconds <= 0:
        raise ValueError("invalid retry policy")
    delays: list[float] = []
    delay = initial_seconds
    for _ in range(retries):
        delays.append(min(delay, cap_seconds))
        delay = min(delay * multiplier, cap_seconds)
    return delays


def fireworks_manifest() -> dict[str, Any]:
    """Return a secret-free implementation and scaling manifest."""
    from core.a2a_envelope import telemetry_snapshot
    from core.cost_attribution import cost_attribution_snapshot
    from core.gpu_status import gpu_status_snapshot
    from core.observability import policy_cache_snapshot
    from core.runtime_key import llm_active, llm_config_issues, llm_provider
    from services.fireworks_batch import batch_config_status, batch_status_view

    models = configured_models()
    return {
        "vision": (
            "Fireworks is the accelerated inference plane for grounded HR agents; "
            "the application remains the policy, workflow, audit, and human-approval plane."
        ),
        "configuration": {
            "provider": llm_provider(),
            "live_enabled": llm_active(),
            "issues": llm_config_issues(),
            "base_url_configured": bool(
                os.environ.get("FIREWORKS_BASE_URL", settings.fireworks_base_url).strip()
            ),
            "allowed_model_count": len(models),
            "credentials_exposed": False,
        },
        "runtime": {
            "online_default": settings.fireworks_serving_mode,
            "bulk_default": "batch",
            "reserved_or_custom_default": "dedicated",
            "request_retries": settings.fireworks_max_retries,
            "session_affinity": settings.fireworks_session_affinity,
            "structured_output_certifier": "core.fireworks_certifier.FireworksOutputCertifier",
            "deterministic_fallback": True,
            "batch": batch_config_status(),
        },
        "runtime_telemetry": {
            "certifier_active": True,
            "last_100_certifications": telemetry_snapshot(100),
            **cost_attribution_snapshot(),
            "policy_cache": policy_cache_snapshot(),
            "amd_gpu_status": gpu_status_snapshot(),
            "cost_router": {
                "enabled": True,
                "model_selection": "ALLOWED_MODELS only",
                "tiers": ["economy", "standard", "premium"],
            },
        },
        "batch_async_contract": {
            "reference": batch_status_view({"state": "JOB_STATE_PENDING"}),
            "poll_seconds": 10,
            "pending_warning_after_minutes": 30,
            "operator_note": (
                "Pending is an expected asynchronous queue state, not a failed request. "
                "Verify model support, dataset validity, quota, and job age before escalation."
            ),
        },
        "use_cases": [dict(use_case) for use_case in USE_CASES],
        "promotion_gates": [
            "golden-set quality beats the deterministic or prompted baseline",
            "bias and safety tests pass",
            "p95 latency and cost per completed workflow meet budget",
            "human approval remains mandatory for adverse employment decisions",
            "fine-tuning starts only after prompt and retrieval baselines plateau",
        ],
        "gpu_boundary": {
            "application_kernels": "optional and benchmark-gated",
            "production_retrieval": "pgvector",
            "inference_acceleration": "Fireworks-managed unless a measured local path wins",
        },
    }
