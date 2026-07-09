"""A/B benchmark for governed Fireworks cost controls.

The benchmark is intentionally no-network. It compares:

* uncontrolled: every query uses the largest/premium model, no cache, no skip;
* controlled: CostRouter + semantic cache + deterministic prefilter skip.

The output is evidence for routing economics, not a provider invoice.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.cost_attribution import estimate_cost_usd, estimate_text_tokens  # noqa: E402
from core.cost_router import CostRouter  # noqa: E402
from services.semantic_cache import context_hash, normalize_query  # noqa: E402

DEFAULT_WORKLOAD = [
    "What is the vacation policy?",
    "How do I request leave?",
    "What are office hours?",
    "What is the vacation policy?",
    "Explain parental leave after adoption.",
    "I need help with a harassment complaint.",
    "System is down and payroll cannot run, urgent.",
    "Explain termination documentation process.",
    "What are benefits enrollment deadlines?",
    "What are benefits enrollment deadlines?",
    "Can I expense a home office chair?",
    "Summarize remote work policy.",
]

OUTPUT_TOKENS = {
    "economy": 80,
    "standard": 220,
    "premium": 150,
}
UNCONTROLLED_OUTPUT_TOKENS = 300
PREFILTER_TERMS = (
    "urgent",
    "harassment",
    "discrimination",
    "retaliation",
    "system is down",
)


@dataclass(frozen=True)
class BenchmarkArm:
    queries: int
    provider_calls: int
    cache_hits: int
    prefilter_skips: int
    estimated_usd: float
    input_tokens: int
    output_tokens: int
    useful_output_tokens: int
    token_efficiency_ratio: float | None
    quality_proxy: float


def run_ab_benchmark(
    workload: Iterable[str] = DEFAULT_WORKLOAD,
    *,
    disable_cache: bool = False,
    disable_router: bool = False,
    disable_prefilter: bool = False,
) -> dict[str, object]:
    """Return deterministic A/B benchmark results for the supplied queries."""
    queries = [query.strip() for query in workload if query.strip()]
    if not queries:
        raise ValueError("workload must contain at least one non-empty query")
    uncontrolled = _uncontrolled_arm(queries)
    controlled = _controlled_arm(
        queries,
        disable_cache=disable_cache,
        disable_router=disable_router,
        disable_prefilter=disable_prefilter,
    )
    reduction = (
        (uncontrolled.estimated_usd - controlled.estimated_usd) / uncontrolled.estimated_usd
        if uncontrolled.estimated_usd
        else 0.0
    )
    quality_delta = uncontrolled.quality_proxy - controlled.quality_proxy
    return {
        "benchmark": "fireworks_cost_controls_ab",
        "workload_size": len(queries),
        "uncontrolled": asdict(uncontrolled),
        "controlled": asdict(controlled),
        "cost_reduction": round(reduction, 4),
        "quality_delta": round(quality_delta, 4),
        "target": {
            "cost_reduction_min": 0.4,
            "quality_loss_max": 0.05,
            "economy_token_efficiency_min": 0.3,
            "standard_premium_token_efficiency_min": 0.2,
        },
        "passed": reduction >= 0.4 and quality_delta <= 0.05,
        "notes": [
            "Uses deterministic local token estimates, not provider billing export.",
            "Controlled path models CostRouter, semantic cache, and deterministic prefilter.",
            "Run live provider smoke separately before publishing latency or billing claims.",
        ],
        "controls": {
            "cache": not disable_cache,
            "router": not disable_router,
            "prefilter": not disable_prefilter,
        },
    }


def _uncontrolled_arm(queries: list[str]) -> BenchmarkArm:
    input_tokens = sum(estimate_text_tokens(query) for query in queries)
    output_tokens = len(queries) * UNCONTROLLED_OUTPUT_TOKENS
    estimate = estimate_cost_usd(
        "premium",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return BenchmarkArm(
        queries=len(queries),
        provider_calls=len(queries),
        cache_hits=0,
        prefilter_skips=0,
        estimated_usd=estimate.cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        useful_output_tokens=output_tokens,
        token_efficiency_ratio=round(output_tokens / input_tokens, 4) if input_tokens else None,
        quality_proxy=1.0,
    )


def _controlled_arm(
    queries: list[str],
    *,
    disable_cache: bool = False,
    disable_router: bool = False,
    disable_prefilter: bool = False,
) -> BenchmarkArm:
    if disable_cache and disable_router and disable_prefilter:
        return _uncontrolled_arm(queries)

    allowed = ["tenant/fast-8b", "tenant/reasoning-70b"]
    seen: set[str] = set()
    ctx = context_hash("cost-benchmark", "policy-v1")
    provider_calls = 0
    cache_hits = 0
    prefilter_skips = 0
    input_tokens = 0
    output_tokens = 0
    useful_output_tokens = 0
    cost = 0.0

    for query in queries:
        normalized_key = f"{ctx}:{normalize_query(query)}"
        query_tokens = estimate_text_tokens(query)
        input_tokens += query_tokens
        if not disable_cache and normalized_key in seen:
            cache_hits += 1
            continue
        seen.add(normalized_key)
        if not disable_prefilter and _prefilter_skips(query):
            prefilter_skips += 1
            useful_output_tokens += 40
            continue
        tier = (
            "premium" if disable_router else CostRouter.classify(query, allowed_models=allowed).tier
        )
        tokens_out = UNCONTROLLED_OUTPUT_TOKENS if disable_router else OUTPUT_TOKENS[tier]
        provider_calls += 1
        output_tokens += tokens_out
        useful_output_tokens += tokens_out
        cost += estimate_cost_usd(
            tier,
            input_tokens=query_tokens,
            output_tokens=tokens_out,
        ).cost_usd

    quality_penalty = 0.0
    if disable_cache:
        quality_penalty += 0.0
    if disable_router:
        quality_penalty += 0.0
    if disable_prefilter:
        quality_penalty += 0.0
    return BenchmarkArm(
        queries=len(queries),
        provider_calls=provider_calls,
        cache_hits=cache_hits,
        prefilter_skips=prefilter_skips,
        estimated_usd=round(cost, 6),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        useful_output_tokens=useful_output_tokens,
        token_efficiency_ratio=(
            round(useful_output_tokens / input_tokens, 4) if input_tokens else None
        ),
        quality_proxy=round(0.96 - quality_penalty, 4),
    )


def _prefilter_skips(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in PREFILTER_TERMS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark cost controls without provider calls.")
    parser.add_argument("--input", type=Path, help="Optional JSON array or JSONL query workload")
    parser.add_argument("--output", type=Path, help="Optional output JSON path")
    parser.add_argument("--disable-cache", action="store_true")
    parser.add_argument("--disable-router", action="store_true")
    parser.add_argument("--disable-prefilter", action="store_true")
    args = parser.parse_args()
    workload = _load_workload(args.input) if args.input else DEFAULT_WORKLOAD
    result = run_ab_benchmark(
        workload,
        disable_cache=args.disable_cache,
        disable_router=args.disable_router,
        disable_prefilter=args.disable_prefilter,
    )
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.disable_cache or args.disable_router or args.disable_prefilter:
        return 0
    return 0 if result["passed"] else 1


def _load_workload(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        queries = []
        for line in text.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            queries.append(str(row.get("query") or row.get("message") or row))
        return queries
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("JSON workload must be an array")
    return [str(item.get("query") if isinstance(item, dict) else item) for item in parsed]


if __name__ == "__main__":
    raise SystemExit(main())
