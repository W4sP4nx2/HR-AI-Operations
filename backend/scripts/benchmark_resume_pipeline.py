"""Benchmark local resume parsing without model or network calls.

This reports measured parser latency for a named fixture directory. It does
not claim Fireworks latency, OCR throughput, or end-to-end hiring throughput;
those require named hardware, provider settings, and representative fixtures.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.resume_pipeline import ResumeParserPipeline  # noqa: E402


def benchmark(directory: Path, *, max_files: int = 1000) -> dict[str, object]:
    parser = ResumeParserPipeline()
    paths = sorted(path for path in directory.iterdir() if path.is_file())[:max_files]
    latencies_ms: list[float] = []
    parsed = 0
    skipped: list[dict[str, str]] = []
    for path in paths:
        started = time.perf_counter()
        try:
            parser.parse(path.read_bytes(), path.name)
            parsed += 1
        except Exception as exc:  # noqa: BLE001 - benchmark reports fixture failures
            skipped.append({"file": path.name, "error": str(exc)})
        finally:
            latencies_ms.append((time.perf_counter() - started) * 1000)
    ordered = sorted(latencies_ms)
    return {
        "directory": str(directory),
        "files_seen": len(paths),
        "parsed": parsed,
        "skipped": skipped,
        "latency_ms": {
            "p50": round(statistics.median(ordered), 3) if ordered else None,
            "p95": (
                round(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)], 3) if ordered else None
            ),
            "max": round(max(ordered), 3) if ordered else None,
        },
        "model_calls": 0,
        "network_calls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--max-files", type=int, default=1000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        print(f"directory not found: {args.directory}", file=sys.stderr)
        return 1
    result = benchmark(args.directory, max_files=max(1, args.max_files))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        latency = result["latency_ms"]
        print(
            f"parsed={result['parsed']}/{result['files_seen']} "
            f"p50_ms={latency['p50']} p95_ms={latency['p95']} max_ms={latency['max']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
