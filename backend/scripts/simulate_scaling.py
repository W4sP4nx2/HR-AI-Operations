"""Print a clearly labeled scaling projection for the Compose demo path."""

from __future__ import annotations

import argparse
import json

from core.scaling_simulation import project_gpu_replicas


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate AMD inference scaling")
    parser.add_argument("--current-replicas", type=int, default=1)
    parser.add_argument("--queue-depth", type=int, required=True)
    parser.add_argument("--p95-ms", type=float, required=True)
    parser.add_argument("--gpu-utilization", type=float, required=True)
    parser.add_argument("--min-replicas", type=int, default=1)
    parser.add_argument("--max-replicas", type=int, default=8)
    args = parser.parse_args()
    result = project_gpu_replicas(
        current_replicas=args.current_replicas,
        queue_depth=args.queue_depth,
        p95_latency_ms=args.p95_ms,
        gpu_utilization_percent=args.gpu_utilization,
        min_replicas=args.min_replicas,
        max_replicas=args.max_replicas,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
