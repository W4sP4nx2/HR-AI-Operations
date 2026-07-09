"""GPU-only Triton versus PyTorch cosine benchmark.

This script refuses CPU execution and bounds requested allocation before creating
tensors. Results are evidence only for the named hardware printed in the report.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

ROWS = (32, 256, 1_000, 10_000, 100_000)
DIMENSIONS = (256, 384, 512, 768, 1_024, 2_048)
DTYPES = ("fp16", "bf16", "fp32")


def _dtype(name: str, torch):
    return {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[name]


def _estimated_bytes(rows: int, dimension: int, dtype_bytes: int) -> int:
    """Query + candidates + two score vectors + modest comparison overhead."""
    tensor_bytes = (rows * dimension + dimension) * dtype_bytes
    return 2 * tensor_bytes + 2 * rows * 4


def _hardware(torch) -> dict[str, Any]:
    props = torch.cuda.get_device_properties(0)
    return {
        "device": torch.cuda.get_device_name(0),
        "total_memory_bytes": int(props.total_memory),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "hip": torch.version.hip,
    }


def benchmark_case(rows: int, dimension: int, dtype_name: str, max_bytes: int) -> dict[str, Any]:
    import torch
    import torch.nn.functional as functional
    import triton

    from kernels.fused_cosine_score import active_backend, fused_cosine_score

    dtype = _dtype(dtype_name, torch)
    bytes_required = _estimated_bytes(rows, dimension, torch.tensor([], dtype=dtype).element_size())
    if bytes_required > max_bytes:
        return {
            "rows": rows,
            "dimension": dimension,
            "dtype": dtype_name,
            "status": "skipped",
            "reason": f"estimated allocation {bytes_required} exceeds cap {max_bytes}",
        }
    if dtype is torch.bfloat16 and not torch.cuda.is_bf16_supported():
        return {
            "rows": rows,
            "dimension": dimension,
            "dtype": dtype_name,
            "status": "skipped",
            "reason": "bf16 unsupported on this device",
        }

    query = torch.randn(dimension, device="cuda", dtype=dtype)
    candidates = torch.randn(rows, dimension, device="cuda", dtype=dtype)
    if active_backend(query) != "triton":
        raise RuntimeError("CUDA/ROCm exists but the Triton backend is not active")

    reference = functional.cosine_similarity(query.unsqueeze(0), candidates, dim=1)
    fused = fused_cosine_score(query, candidates)
    max_error = float((fused.float() - reference.float()).abs().max().item())

    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    fused_p50, fused_p95 = triton.testing.do_bench(
        lambda: fused_cosine_score(query, candidates),
        quantiles=[0.5, 0.95],
    )
    torch_p50, torch_p95 = triton.testing.do_bench(
        lambda: functional.cosine_similarity(query.unsqueeze(0), candidates, dim=1),
        quantiles=[0.5, 0.95],
    )
    peak_memory = int(torch.cuda.max_memory_allocated())
    bytes_moved = (rows * dimension + dimension) * query.element_size() + rows * 4
    return {
        "rows": rows,
        "dimension": dimension,
        "dtype": dtype_name,
        "status": "ok",
        "triton_p50_ms": round(float(fused_p50), 6),
        "triton_p95_ms": round(float(fused_p95), 6),
        "torch_p50_ms": round(float(torch_p50), 6),
        "torch_p95_ms": round(float(torch_p95), 6),
        "speedup_p50": round(float(torch_p50 / fused_p50), 4),
        "effective_gb_s_p50": round(bytes_moved / (float(fused_p50) / 1000) / 1e9, 4),
        "peak_gpu_memory_bytes": peak_memory,
        "max_abs_error": max_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", action="store_true", help="run the full guarded matrix")
    parser.add_argument("--rows", type=int, default=5_000)
    parser.add_argument("--dim", type=int, default=384)
    parser.add_argument("--dtype", choices=DTYPES, default="fp32")
    parser.add_argument("--max-gpu-memory-mb", type=int, default=2_048)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        import torch
        import triton  # noqa: F401
    except ImportError as exc:
        print(f"GPU benchmark unavailable: {exc}")
        return 2
    if not torch.cuda.is_available():
        print("Refusing CPU execution: run this benchmark on a CUDA/ROCm GPU host.")
        return 2

    cases = (
        itertools.product(ROWS, DIMENSIONS, DTYPES)
        if args.matrix
        else [(args.rows, args.dim, args.dtype)]
    )
    max_bytes = args.max_gpu_memory_mb * 1024 * 1024
    results: list[dict[str, Any]] = []
    for rows, dimension, dtype_name in cases:
        try:
            results.append(benchmark_case(rows, dimension, dtype_name, max_bytes))
        except Exception as exc:  # keep the matrix useful while exposing failures
            results.append(
                {
                    "rows": rows,
                    "dimension": dimension,
                    "dtype": dtype_name,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    report = {
        "hardware": _hardware(torch),
        "integration_gate": {
            "minimum_end_to_end_speedup": 1.5,
            "note": "kernel speed alone does not authorize product integration",
        },
        "results": results,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return int(any(result["status"] == "error" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
