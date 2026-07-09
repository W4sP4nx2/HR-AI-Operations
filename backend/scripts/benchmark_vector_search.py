"""Benchmark exact cosine top-k scoring on the active Torch/Triton backend."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from pathlib import Path
from typing import Any


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_benchmark(
    *,
    rows: int,
    dimension: int,
    queries: int,
    warmup: int,
    top_k_count: int,
    max_memory_mb: int,
    seed: int,
) -> dict[str, Any]:
    """Measure scoring plus top-k selection without database or network latency."""
    import torch
    import torch.nn.functional as functional

    from kernels.fused_cosine_score import active_backend, fused_cosine_score, top_k

    if min(rows, dimension, queries, top_k_count) < 1 or warmup < 0:
        raise ValueError("rows, dimension, queries and top-k must be positive")
    if top_k_count > rows:
        raise ValueError("top-k cannot exceed rows")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    estimated_bytes = (rows * dimension + dimension + rows) * 4
    cap = max_memory_mb * 1024 * 1024
    if estimated_bytes > cap:
        raise ValueError(f"estimated allocation {estimated_bytes} bytes exceeds cap {cap} bytes")

    generator = torch.Generator(device=device).manual_seed(seed)
    candidates = torch.randn(rows, dimension, generator=generator, device=device)
    query = torch.randn(dimension, generator=generator, device=device)
    backend = active_backend(query)

    def execute() -> tuple[torch.Tensor, torch.Tensor]:
        return top_k(fused_cosine_score(query, candidates), top_k_count)

    for _ in range(warmup):
        execute()
    if device.type == "cuda":
        torch.cuda.synchronize()

    samples_ms: list[float] = []
    for _ in range(queries):
        query.normal_(generator=generator)
        started = time.perf_counter_ns()
        values, indices = execute()
        if device.type == "cuda":
            torch.cuda.synchronize()
        samples_ms.append((time.perf_counter_ns() - started) / 1_000_000)

    reference = functional.cosine_similarity(query.unsqueeze(0), candidates, dim=1)
    expected_values, expected_indices = torch.topk(
        reference,
        k=top_k_count,
        largest=True,
        sorted=True,
    )
    max_error = float((values.float() - expected_values.float()).abs().max().item())
    indices_match = bool(torch.equal(indices, expected_indices))
    target_ms = 10.0 if backend == "triton" else 50.0
    p95 = _percentile(samples_ms, 0.95)

    hardware: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device_type": device.type,
        "backend": backend,
    }
    if device.type == "cuda":
        hardware.update(
            {
                "device": torch.cuda.get_device_name(0),
                "cuda": torch.version.cuda,
                "hip": torch.version.hip,
            }
        )

    return {
        "scope": "in-memory exact cosine scoring plus top-k; excludes embedding and database I/O",
        "hardware": hardware,
        "shape": {
            "rows": rows,
            "dimension": dimension,
            "top_k": top_k_count,
            "queries": queries,
            "warmup": warmup,
        },
        "latency_ms": {
            "median": round(statistics.median(samples_ms), 6),
            "p95": round(p95, 6),
            "minimum": round(min(samples_ms), 6),
            "maximum": round(max(samples_ms), 6),
        },
        "correctness": {
            "max_abs_error": max_error,
            "indices_match": indices_match,
        },
        "gate": {
            "target_p95_ms": target_ms,
            "passed": p95 < target_ms and max_error <= 1e-4 and indices_match,
            "hardware_claim": (
                "ROCm/CUDA result" if backend == "triton" else "CPU fallback result"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--dimension", type=int, default=384)
    parser.add_argument("--queries", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-memory-mb", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--enforce-target",
        action="store_true",
        help="exit nonzero when the backend-specific p95/correctness gate fails",
    )
    args = parser.parse_args()

    report = run_benchmark(
        rows=args.rows,
        dimension=args.dimension,
        queries=args.queries,
        warmup=args.warmup,
        top_k_count=args.top_k,
        max_memory_mb=args.max_memory_mb,
        seed=args.seed,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return int(args.enforce_target and not report["gate"]["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
