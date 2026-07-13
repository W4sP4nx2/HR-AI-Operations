"""Deterministic cost attribution for governed inference paths.

This is not a provider bill. It is a local, auditable estimate that lets the
dashboard show whether routing, cache hits, and deterministic skips are reducing
avoidable model calls before real billing exports are connected.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Any

from core.config import settings
from core.cost_guard import TokenBudgetGuard

COST_PER_1K_TOKENS = {
    "economy": 0.0002,
    "standard": 0.0009,
    "premium": 0.0009,
}

_LOCK = Lock()
_PROVIDER_USAGE: dict[str, dict[str, int]] = defaultdict(
    lambda: {
        "requests": 0,
        "prompt_tokens": 0,
        "cached_prompt_tokens": 0,
        "completion_tokens": 0,
    }
)
_LEDGER: dict[str, dict[str, float | int]] = defaultdict(
    lambda: {
        "queries": 0,
        "provider_calls": 0,
        "cache_hits": 0,
        "prefilter_skips": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "useful_output_tokens": 0,
        "total_usd": 0.0,
    }
)


@dataclass(frozen=True)
class CostEstimate:
    tier: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_per_1k: float


def estimate_cost_usd(
    tier: str,
    *,
    input_tokens: int,
    output_tokens: int,
) -> CostEstimate:
    """Estimate provider spend for one request from local token counts."""
    normalized_tier = tier if tier in COST_PER_1K_TOKENS else "standard"
    cost_per_1k = COST_PER_1K_TOKENS[normalized_tier]
    safe_input = max(0, int(input_tokens))
    safe_output = max(0, int(output_tokens))
    return CostEstimate(
        tier=normalized_tier,
        input_tokens=safe_input,
        output_tokens=safe_output,
        cost_usd=round(((safe_input + safe_output) / 1000.0) * cost_per_1k, 6),
        cost_per_1k=cost_per_1k,
    )


def estimate_text_tokens(text: str) -> int:
    """Use the same local estimator as TokenBudgetGuard."""
    return TokenBudgetGuard().estimate_text_tokens(text)


def estimate_payload_tokens(payload: dict[str, Any]) -> int:
    """Estimate input tokens without retaining raw payload content."""
    messages = [{"role": "user", "content": str(value)} for value in payload.values()]
    return TokenBudgetGuard().estimate_messages(messages)


def record_cost_event(
    *,
    tier: str,
    input_tokens: int,
    output_tokens: int = 0,
    useful_output_tokens: int | None = None,
    provider_call: bool = True,
    cache_hit: bool = False,
    prefilter_skip: bool = False,
) -> CostEstimate:
    """Record one governed inference decision and return its cost estimate."""
    normalized_tier = tier if tier in COST_PER_1K_TOKENS else "standard"
    billable = provider_call and not cache_hit and not prefilter_skip
    estimate = estimate_cost_usd(
        normalized_tier,
        input_tokens=input_tokens if billable else 0,
        output_tokens=output_tokens if billable else 0,
    )
    useful = max(
        0, int(useful_output_tokens if useful_output_tokens is not None else output_tokens)
    )
    with _LOCK:
        row = _LEDGER[normalized_tier]
        row["queries"] += 1
        row["provider_calls"] += 1 if provider_call else 0
        row["cache_hits"] += 1 if cache_hit else 0
        row["prefilter_skips"] += 1 if prefilter_skip else 0
        row["input_tokens"] += max(0, int(input_tokens))
        row["output_tokens"] += max(0, int(output_tokens))
        row["useful_output_tokens"] += useful
        row["total_usd"] = round(float(row["total_usd"]) + estimate.cost_usd, 6)
    return estimate


def record_provider_usage(
    *,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_prompt_tokens: int = 0,
) -> None:
    """Record token counts returned by the provider without inventing a dollar bill.

    The ledger deliberately stores only aggregate counts keyed by model id. Raw
    prompts, API keys, request bodies, and response text never enter telemetry.
    """
    model = model_id.strip() or "unknown"
    with _LOCK:
        row = _PROVIDER_USAGE[model]
        row["requests"] += 1
        row["prompt_tokens"] += max(0, int(prompt_tokens))
        row["cached_prompt_tokens"] += min(
            max(0, int(cached_prompt_tokens)), max(0, int(prompt_tokens))
        )
        row["completion_tokens"] += max(0, int(completion_tokens))


def provider_usage_snapshot() -> dict[str, Any]:
    """Return provider-observed token totals, separately from local estimates."""
    with _LOCK:
        models = {model: dict(values) for model, values in _PROVIDER_USAGE.items()}
    return {
        "source": "provider_response_usage",
        "requests": sum(int(row["requests"]) for row in models.values()),
        "prompt_tokens": sum(int(row["prompt_tokens"]) for row in models.values()),
        "cached_prompt_tokens": sum(
            int(row["cached_prompt_tokens"]) for row in models.values()
        ),
        "completion_tokens": sum(int(row["completion_tokens"]) for row in models.values()),
        "rated_cost_usd": None,
        "models": models,
        "note": "Token counts come from provider responses; rated cost requires a billing export.",
    }


def cost_attribution_snapshot() -> dict[str, Any]:
    """Return dashboard-ready cost and efficiency counters."""
    with _LOCK:
        rows = {tier: dict(values) for tier, values in _LEDGER.items()}

    cost_attribution: dict[str, dict[str, float | int | None]] = {}
    total_queries = 0
    total_cache_hits = 0
    total_prefilter_skips = 0
    total_input = 0
    total_useful = 0
    for tier in ("economy", "standard", "premium"):
        row = rows.get(
            tier,
            {
                "queries": 0,
                "provider_calls": 0,
                "cache_hits": 0,
                "prefilter_skips": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "useful_output_tokens": 0,
                "total_usd": 0.0,
            },
        )
        queries = int(row["queries"])
        total_usd = round(float(row["total_usd"]), 6)
        input_tokens = int(row["input_tokens"])
        useful_output_tokens = int(row["useful_output_tokens"])
        cost_attribution[tier] = {
            "queries": queries,
            "provider_calls": int(row["provider_calls"]),
            "total_usd": total_usd,
            "avg_per_query": round(total_usd / queries, 6) if queries else 0.0,
            "input_tokens": input_tokens,
            "output_tokens": int(row["output_tokens"]),
            "token_efficiency_ratio": (
                round(useful_output_tokens / input_tokens, 4) if input_tokens else None
            ),
        }
        total_queries += queries
        total_cache_hits += int(row["cache_hits"])
        total_prefilter_skips += int(row["prefilter_skips"])
        total_input += input_tokens
        total_useful += useful_output_tokens

    snapshot = {
        "cost_attribution": cost_attribution,
        "cache_hit_rate": round(total_cache_hits / total_queries, 4) if total_queries else None,
        "prefilter_skip_rate": (
            round(total_prefilter_skips / total_queries, 4) if total_queries else None
        ),
        "token_efficiency_ratio": round(total_useful / total_input, 4) if total_input else None,
        "estimation": {
            "type": "local_estimate",
            "currency": "USD",
            "rates_per_1k_tokens": dict(COST_PER_1K_TOKENS),
            "billing_export_connected": False,
        },
    }
    snapshot["budget_circuit_breaker"] = budget_circuit_breaker_snapshot(snapshot)
    return snapshot


def budget_circuit_breaker_snapshot(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return whether estimated spend has crossed the configured local threshold."""
    total_usd = 0.0
    if snapshot is None:
        with _LOCK:
            total_usd = sum(float(row["total_usd"]) for row in _LEDGER.values())
    else:
        cost_rows = snapshot.get("cost_attribution", {})
        if isinstance(cost_rows, dict):
            for row in cost_rows.values():
                if isinstance(row, dict):
                    total_usd += float(row.get("total_usd") or 0.0)
    from core.runtime_settings import runtime_settings

    configured_budget = (
        runtime_settings.value("daily_budget_usd", settings.daily_inference_budget_usd)
        if runtime_settings.active
        else settings.daily_inference_budget_usd
    )
    threshold = max(0.0, float(configured_budget))
    active = bool(threshold and total_usd >= threshold)
    return {
        "active": active,
        "estimated_spend_usd": round(total_usd, 6),
        "daily_threshold_usd": threshold,
        "forced_tier": "economy" if active else None,
        "cache_ttl_seconds": (
            max(settings.semantic_cache_ttl, settings.circuit_breaker_cache_ttl_seconds)
            if active
            else settings.semantic_cache_ttl
        ),
    }


def reset_cost_attribution() -> None:
    """Clear the process-local ledger for tests."""
    with _LOCK:
        _LEDGER.clear()
        _PROVIDER_USAGE.clear()
