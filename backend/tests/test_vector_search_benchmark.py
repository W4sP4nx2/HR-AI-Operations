"""Tests for the bounded exact-vector benchmark gate."""

from scripts.benchmark_vector_search import run_benchmark


def test_vector_search_benchmark_reports_scope_and_correctness():
    report = run_benchmark(
        rows=64,
        dimension=16,
        queries=3,
        warmup=1,
        top_k_count=5,
        max_memory_mb=4,
        seed=7,
    )

    assert report["shape"]["top_k"] == 5
    assert report["latency_ms"]["p95"] >= 0
    assert report["correctness"]["max_abs_error"] <= 1e-4
    assert report["correctness"]["indices_match"] is True
    assert "database I/O" in report["scope"]
