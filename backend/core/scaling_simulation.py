"""Deterministic GPU scaling projection for the Docker Compose demo path."""

from __future__ import annotations

import math
from typing import Any


def project_gpu_replicas(
    *,
    current_replicas: int,
    queue_depth: int,
    p95_latency_ms: float,
    gpu_utilization_percent: float,
    min_replicas: int = 1,
    max_replicas: int = 8,
    target_queue_per_replica: int = 8,
) -> dict[str, Any]:
    """Project replicas from supplied metrics without claiming live telemetry."""
    if min_replicas < 1 or max_replicas < min_replicas:
        raise ValueError("replica bounds are invalid")
    if not min_replicas <= current_replicas <= max_replicas:
        raise ValueError("current_replicas must be within the configured bounds")
    if queue_depth < 0 or p95_latency_ms < 0:
        raise ValueError("queue depth and latency cannot be negative")
    if not 0 <= gpu_utilization_percent <= 100:
        raise ValueError("gpu utilization must be between 0 and 100")
    if target_queue_per_replica < 1:
        raise ValueError("target_queue_per_replica must be positive")

    desired = current_replicas
    reasons: list[str] = []
    if queue_depth:
        queue_target = math.ceil(queue_depth / target_queue_per_replica)
        if queue_target > desired:
            desired = queue_target
            reasons.append("queue depth exceeds the per-replica target")
    if p95_latency_ms >= 2000:
        desired = max(desired, current_replicas + 1)
        reasons.append("p95 latency is at or above 2000 ms")
    if gpu_utilization_percent >= 90:
        desired = max(desired, current_replicas + 1)
        reasons.append("GPU utilization is at or above 90%")
    if queue_depth == 0 and p95_latency_ms < 800 and gpu_utilization_percent < 30:
        desired = min(desired, current_replicas - 1)
        reasons.append("queue is empty and measured pressure is low")

    desired = max(min_replicas, min(max_replicas, desired))
    action = "hold"
    if desired > current_replicas:
        action = "scale_out"
    elif desired < current_replicas:
        action = "scale_in"
    if not reasons:
        reasons.append("inputs remain inside the demo policy thresholds")

    return {
        "simulated": True,
        "source": "operator-supplied projection inputs; not live cluster telemetry",
        "inputs": {
            "current_replicas": current_replicas,
            "queue_depth": queue_depth,
            "p95_latency_ms": p95_latency_ms,
            "gpu_utilization_percent": gpu_utilization_percent,
        },
        "policy": {
            "min_replicas": min_replicas,
            "max_replicas": max_replicas,
            "target_queue_per_replica": target_queue_per_replica,
        },
        "recommendation": {
            "action": action,
            "desired_replicas": desired,
            "reasons": reasons,
        },
    }
