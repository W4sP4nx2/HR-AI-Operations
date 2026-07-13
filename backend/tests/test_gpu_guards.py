"""GPU integration and benchmark safety gates."""

from __future__ import annotations


def test_gpu_kernel_disabled_by_default():
    from services.gpu_vector_scoring import eligibility

    result = eligibility(1_000_000)
    assert result.eligible is False
    assert "ENABLE_GPU_KERNELS" in result.reason


def test_benchmark_allocation_estimate_grows_with_matrix_shape():
    from benchmarks.benchmark_kernels import _estimated_bytes

    small = _estimated_bytes(32, 256, 2)
    large = _estimated_bytes(100_000, 1_024, 4)
    assert 0 < small < large
    assert large > 100_000 * 1_024 * 4
