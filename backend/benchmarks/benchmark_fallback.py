"""Measure deterministic fallback latency without network calls or model downloads."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
from pathlib import Path
from typing import Callable

from core.embeddings import _hash_embed
from models.naive_baselines import triage_keyword_baseline


def _measure(operation: Callable[[], object], iterations: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        operation()
    samples_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        operation()
        samples_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(samples_ms)
    p95_index = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    return {
        "iterations": iterations,
        "median_ms": round(statistics.median(ordered), 6),
        "p95_ms": round(ordered[p95_index], 6),
        "max_ms": round(max(ordered), 6),
    }


def benchmark(iterations: int = 1000, warmup: int = 100) -> dict[str, object]:
    """Return named-machine latency evidence for deterministic fallback operations."""
    if iterations < 1 or warmup < 0:
        raise ValueError("iterations must be positive and warmup non-negative")
    ticket = "Urgent safety issue and harassment complaint requiring immediate help"
    policy_text = (
        "Remote work policy employees may work remotely three days per week "
        "with manager approval and documented security controls."
    )
    return {
        "environment": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "gpu_used": False,
            "network_used": False,
        },
        "triage_keyword": _measure(
            lambda: triage_keyword_baseline.predict(ticket),
            iterations,
            warmup,
        ),
        "hash_embedding": _measure(
            lambda: _hash_embed(policy_text),
            iterations,
            warmup,
        ),
        "claim_policy": (
            "These are local fallback measurements only. Do not compare them with "
            "Fireworks or AMD GPU latency unless both paths are measured in the same run."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = benchmark(args.iterations, args.warmup)
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
