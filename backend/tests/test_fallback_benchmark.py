"""Deterministic fallback benchmark contract tests."""

from __future__ import annotations

from benchmarks.benchmark_fallback import benchmark


def test_fallback_benchmark_is_measured_and_claim_bounded():
    report = benchmark(iterations=5, warmup=1)
    assert report["environment"]["gpu_used"] is False
    assert report["environment"]["network_used"] is False
    for operation in ("triage_keyword", "hash_embedding"):
        assert report[operation]["iterations"] == 5
        assert report[operation]["median_ms"] >= 0
        assert report[operation]["p95_ms"] >= report[operation]["median_ms"]
    assert "same run" in report["claim_policy"]
