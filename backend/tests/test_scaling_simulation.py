"""Tests for the explicitly simulated Docker Compose scaling projection."""

from __future__ import annotations

import pytest

from core.scaling_simulation import project_gpu_replicas


def test_projection_scales_out_under_queue_pressure():
    result = project_gpu_replicas(
        current_replicas=1,
        queue_depth=25,
        p95_latency_ms=2400,
        gpu_utilization_percent=94,
    )
    assert result["simulated"] is True
    assert result["recommendation"]["action"] == "scale_out"
    assert result["recommendation"]["desired_replicas"] == 4
    assert "not live cluster telemetry" in result["source"]


def test_projection_scales_in_only_when_pressure_is_low():
    result = project_gpu_replicas(
        current_replicas=3,
        queue_depth=0,
        p95_latency_ms=400,
        gpu_utilization_percent=20,
    )
    assert result["recommendation"] == {
        "action": "scale_in",
        "desired_replicas": 2,
        "reasons": ["queue is empty and measured pressure is low"],
    }


def test_projection_validates_operator_inputs():
    with pytest.raises(ValueError, match="utilization"):
        project_gpu_replicas(
            current_replicas=1,
            queue_depth=0,
            p95_latency_ms=100,
            gpu_utilization_percent=101,
        )
