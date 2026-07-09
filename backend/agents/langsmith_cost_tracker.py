"""Optional LangSmith cost attribution for governed agent steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

COST_PER_1K_TOKENS = {
    "economy": 0.0002,
    "standard": 0.0009,
    "premium": 0.0009,
}


@dataclass(frozen=True)
class CostAttribution:
    tier: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cost_per_1k: float


def estimate_cost_usd(tier: str, tokens_in: int, tokens_out: int) -> CostAttribution:
    """Return deterministic approximate spend for one agent step."""
    normalized_tier = tier if tier in COST_PER_1K_TOKENS else "standard"
    cost_per_1k = COST_PER_1K_TOKENS[normalized_tier]
    total_tokens = max(0, tokens_in) + max(0, tokens_out)
    return CostAttribution(
        tier=normalized_tier,
        tokens_in=max(0, tokens_in),
        tokens_out=max(0, tokens_out),
        cost_usd=round((total_tokens / 1000) * cost_per_1k, 6),
        cost_per_1k=cost_per_1k,
    )


class CostAwareTracer:
    """Best-effort LangSmith bridge; never required for local/no-key tests."""

    def trace_agent_step(
        self,
        *,
        name: str,
        query: str,
        tier: str,
        tokens_in: int,
        tokens_out: int,
        metadata: dict[str, Any] | None = None,
    ) -> CostAttribution:
        attribution = estimate_cost_usd(tier, tokens_in, tokens_out)
        trace_name = f"{name}_{attribution.tier}"
        try:
            from langsmith import Client

            Client().create_run(
                name=trace_name,
                run_type="chain",
                inputs={"query": query},
                outputs={
                    "cost_usd": attribution.cost_usd,
                    "tier": attribution.tier,
                },
                metadata={
                    "tokens_in": attribution.tokens_in,
                    "tokens_out": attribution.tokens_out,
                    "cost_per_1k": attribution.cost_per_1k,
                    "tier": attribution.tier,
                    **(metadata or {}),
                },
            )
        except Exception:  # noqa: BLE001 - cost telemetry cannot break product flow
            pass
        return attribution
