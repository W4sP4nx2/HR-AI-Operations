"""Certify zero-spend inference cost controls without a provider key.

This is an operator-facing evidence command. It performs no network I/O and
does not instantiate a provider client. The goal is to prove the governance
layer can reject, route, cache, attribute, and benchmark spend deterministically
before anyone spends real Fireworks or AMD/vLLM credits.

Usage:
  python -m scripts.certify_cost_controls --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class GateResult:
    name: str
    ok: bool
    detail: str
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@contextmanager
def _temporary_env(**updates: str):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _gate(name: str, func: Callable[[], tuple[bool, str, dict[str, Any]]]) -> GateResult:
    try:
        ok, detail, evidence = func()
        return GateResult(name=name, ok=ok, detail=detail, evidence=evidence)
    except Exception as exc:  # noqa: BLE001 - certification must report all failures
        return GateResult(
            name=name,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            evidence={},
        )


def run_certification() -> dict[str, Any]:
    """Run all no-key cost-control gates and return a machine-readable verdict."""
    gates = [
        _gate("oversized_prompt_rejection", _oversized_prompt_rejection),
        _gate("prohibited_model_rejection", _prohibited_model_rejection),
        _gate("pii_preflight_detection", _pii_preflight_detection),
        _gate("routing_accuracy", _routing_accuracy),
        _gate("cache_determinism", _cache_determinism),
        _gate("cost_math_accuracy", _cost_math_accuracy),
        _gate("benchmark_isolation", _benchmark_isolation),
        _gate("benchmark_reproducibility", _benchmark_reproducibility),
    ]
    ok = all(gate.ok for gate in gates)
    return {
        "certification": "zero_spend_cost_controls",
        "ok": ok,
        "network_required": False,
        "provider_key_required": False,
        "gate_count": len(gates),
        "passed_count": sum(1 for gate in gates if gate.ok),
        "gates": [gate.as_dict() for gate in gates],
    }


def _oversized_prompt_rejection() -> tuple[bool, str, dict[str, Any]]:
    from core.fireworks import build_chat_body

    with _temporary_env(ALLOWED_MODELS="tenant/fast-8b"):
        try:
            build_chat_body(
                model_id="tenant/fast-8b",
                messages=[{"role": "user", "content": "token " * 20_000}],
                max_tokens=64,
            )
        except ValueError as exc:
            ok = "Prompt exceeds budget" in str(exc)
            return ok, str(exc), {"provider_client_constructed": False}
    return False, "oversized prompt was not rejected", {"provider_client_constructed": False}


def _prohibited_model_rejection() -> tuple[bool, str, dict[str, Any]]:
    from core.fireworks import build_chat_body

    with _temporary_env(ALLOWED_MODELS="tenant/fast-8b"):
        try:
            build_chat_body(
                model_id="tenant/unapproved-70b",
                messages=[{"role": "user", "content": "hello"}],
            )
        except ValueError as exc:
            ok = "ALLOWED_MODELS" in str(exc)
            return ok, str(exc), {"allowed_models": ["tenant/fast-8b"]}
    return False, "unapproved model was not rejected", {"allowed_models": ["tenant/fast-8b"]}


def _pii_preflight_detection() -> tuple[bool, str, dict[str, Any]]:
    from core.fireworks_certifier import FireworksOutputCertifier

    result = FireworksOutputCertifier().certify(
        '{"answer":"Employee SSN 123-45-6789","confidence":0.9}',
        {
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["answer", "confidence"],
                "additionalProperties": False,
            },
            "require_pii_free": True,
        },
    )
    violations = getattr(result, "violations", [])
    redaction_count = int(getattr(result, "redaction_count", 0))
    ok = getattr(result, "is_valid", True) is False and "pii_detected" in violations
    return (
        ok,
        "PII detected before provider invocation" if ok else "PII was not blocked",
        {"violations": violations, "redaction_count": redaction_count},
    )


def _routing_accuracy() -> tuple[bool, str, dict[str, Any]]:
    from core.cost_router import CostRouter

    economy = CostRouter.classify(
        "What are office hours?",
        allowed_models=["tenant/fast-8b", "tenant/reasoning-70b"],
    )
    premium = CostRouter.classify(
        "Explain termination process for protected class",
        allowed_models=["tenant/fast-8b", "tenant/reasoning-70b"],
    )
    fallback = CostRouter.classify(
        "What are office hours?",
        allowed_models=["tenant/reasoning-70b"],
    )
    ok = (
        economy.tier == "economy"
        and economy.selected_model == "tenant/fast-8b"
        and premium.tier == "premium"
        and premium.selected_model == "tenant/reasoning-70b"
        and fallback.selected_model == "tenant/reasoning-70b"
    )
    return (
        ok,
        "router selects cheapest sufficient allowlisted tier" if ok else "router mismatch",
        {
            "economy": economy.__dict__,
            "premium": premium.__dict__,
            "fallback_without_8b": fallback.__dict__,
        },
    )


def _cache_determinism() -> tuple[bool, str, dict[str, Any]]:
    from services.semantic_cache import HRSemanticCache, context_hash

    cache = HRSemanticCache(maxsize=4, ttl_seconds=1)
    query = "What are OFFICE hours?"
    context_v1 = context_hash("policy", "v1")
    context_v2 = context_hash("policy", "v2")
    key_a = cache.key_for(query, context_v1)
    key_b = cache.key_for("what are office hours", context_v1)
    cache.set(query, context_v1, {"answer": "9-5"})
    same_context_hit = cache.get("what are office hours", context_v1)
    changed_context_miss = cache.get("what are office hours", context_v2)
    ok = key_a == key_b and same_context_hit == {"answer": "9-5"} and changed_context_miss is None
    return (
        ok,
        "cache key is normalized and policy-context sensitive" if ok else "cache mismatch",
        {
            "key": key_a,
            "context_hash_v1": context_v1,
            "context_hash_v2": context_v2,
            "same_context_hit": same_context_hit is not None,
            "changed_context_miss": changed_context_miss is None,
        },
    )


def _cost_math_accuracy() -> tuple[bool, str, dict[str, Any]]:
    from core.cost_attribution import estimate_cost_usd

    estimate = estimate_cost_usd("standard", input_tokens=500, output_tokens=200)
    ok = estimate.cost_usd == 0.00063 and estimate.cost_per_1k == 0.0009
    return (
        ok,
        "cost estimate matches manual linear calculation" if ok else "cost math drift",
        {
            "tier": estimate.tier,
            "input_tokens": estimate.input_tokens,
            "output_tokens": estimate.output_tokens,
            "cost_per_1k": estimate.cost_per_1k,
            "cost_usd": estimate.cost_usd,
        },
    )


def _benchmark_isolation() -> tuple[bool, str, dict[str, Any]]:
    from scripts.benchmark_cost_controls import run_ab_benchmark

    baseline = run_ab_benchmark(
        disable_cache=True,
        disable_router=True,
        disable_prefilter=True,
    )
    ok = (
        baseline["cost_reduction"] == 0
        and baseline["controlled"]["provider_calls"] == baseline["uncontrolled"]["provider_calls"]
    )
    return (
        ok,
        "disabled controls return to baseline" if ok else "disabled controls still save cost",
        {
            "cost_reduction": baseline["cost_reduction"],
            "controlled_provider_calls": baseline["controlled"]["provider_calls"],
            "uncontrolled_provider_calls": baseline["uncontrolled"]["provider_calls"],
        },
    )


def _benchmark_reproducibility() -> tuple[bool, str, dict[str, Any]]:
    from scripts.benchmark_cost_controls import run_ab_benchmark

    runs = [run_ab_benchmark() for _ in range(3)]
    reductions = [float(run["cost_reduction"]) for run in runs]
    quality_deltas = [float(run["quality_delta"]) for run in runs]
    variance = max(reductions) - min(reductions)
    ok = variance < 0.02 and all(delta < 0.05 for delta in quality_deltas)
    return (
        ok,
        "benchmark is reproducible with stable quality proxy" if ok else "benchmark unstable",
        {
            "cost_reductions": reductions,
            "quality_deltas": quality_deltas,
            "reduction_variance": round(variance, 6),
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    result = run_certification()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"[{status}] zero-spend cost-control certification")
        for gate in result["gates"]:
            marker = "PASS" if gate["ok"] else "FAIL"
            print(f"[{marker}] {gate['name']}: {gate['detail']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
