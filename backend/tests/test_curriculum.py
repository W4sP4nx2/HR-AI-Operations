"""Correctness tests for the kernel curriculum on CPU and AMD/ROCm."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch", reason="optional GPU curriculum dependency is not installed")

import kernels.curriculum as curriculum  # noqa: E402
from kernels.curriculum import (  # noqa: E402
    achieved_bandwidth_gb_s,
    active_backend,
    bias_add,
    fuse_resume_field_embeddings,
    matmul,
    multi_pass_sum,
    partial_sums,
    residual_add,
    row_sum,
    two_pass_sum,
    vector_add,
    weight_update_,
)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _tensor(data) -> torch.Tensor:
    return torch.tensor(data, dtype=torch.float32, device=DEVICE)


def test_vector_add_small():
    x = _tensor([1.0, 2.0, 3.0])
    y = _tensor([10.0, 20.0, 30.0])
    assert torch.allclose(vector_add(x, y), _tensor([11.0, 22.0, 33.0]))


def test_vector_add_random_matches_torch():
    torch.manual_seed(0)
    x = torch.randn(2000, device=DEVICE)
    y = torch.randn(2000, device=DEVICE)
    assert torch.allclose(vector_add(x, y), x + y, atol=1e-5)
    assert active_backend(x) == ("triton" if torch.cuda.is_available() else "torch")


def test_bias_add_broadcasts_correctly():
    x = torch.zeros(3, 4, device=DEVICE)
    bias = _tensor([1.0, 2.0, 3.0, 4.0])
    out = bias_add(x, bias)
    for row in out:
        assert torch.allclose(row, bias)


def test_residual_add_default_alpha_is_plain_sum():
    x = _tensor([1.0, 1.0])
    sublayer = _tensor([2.0, 3.0])
    assert torch.allclose(residual_add(x, sublayer), _tensor([3.0, 4.0]))


def test_residual_add_scales_sublayer_by_alpha():
    x = _tensor([1.0, 1.0])
    sublayer = _tensor([2.0, 3.0])
    assert torch.allclose(residual_add(x, sublayer, alpha=0.5), _tensor([2.0, 2.5]))


def test_weight_update_matches_manual_sgd_step():
    weight = _tensor([1.0, 2.0, 3.0])
    grad = _tensor([0.1, 0.1, 0.1])
    expected = weight - 0.5 * grad
    weight_update_(weight, grad, lr=0.5)
    assert torch.allclose(weight, expected)


def test_row_sum_matches_torch():
    torch.manual_seed(0)
    x = torch.randn(50, 128, device=DEVICE)
    assert torch.allclose(row_sum(x), x.sum(dim=1), atol=1e-4)


def test_partial_sums_exposes_each_first_pass_block():
    x = torch.ones(10_000, device=DEVICE)
    partials = partial_sums(x, block_size=4096)
    assert partials.shape == (3,)
    assert torch.equal(partials, _tensor([4096.0, 4096.0, 1808.0]))


def test_partial_sums_empty_input_has_no_phantom_block():
    partials = partial_sums(torch.empty(0, device=DEVICE), block_size=4096)
    assert partials.shape == (0,)


def test_multi_pass_sum_boundaries():
    for size in (0, 4096, 4097, 10_000):
        x = torch.ones(size, device=DEVICE)
        assert multi_pass_sum(x, block_size=4096).item() == float(size)


def test_two_pass_sum_matches_torch_with_derived_error_bound():
    torch.manual_seed(0)
    x = torch.randn(10_000, device=DEVICE)
    actual = two_pass_sum(x, block_size=4096)
    reference = x.to(torch.float64).sum()

    # Each pass uses a tree reduction. Bound accumulated float32 rounding by
    # gamma_k * sum(abs(x)), where k covers both reduction-tree depths.
    reduction_depth = 12 + 2  # log2(4096) plus log2(next_power_of_two(3)).
    unit_roundoff = torch.finfo(torch.float32).eps / 2
    gamma = reduction_depth * unit_roundoff / (1 - reduction_depth * unit_roundoff)
    error_bound = gamma * x.abs().to(torch.float64).sum()
    assert (actual.to(torch.float64) - reference).abs() <= error_bound


def test_kernel_launch_failure_is_not_silently_replaced_by_torch(monkeypatch):
    class FailingKernel:
        def __getitem__(self, grid):
            def launch(*args, **kwargs):
                raise RuntimeError("simulated GPU launch failure")

            return launch

    monkeypatch.setattr(curriculum, "active_backend", lambda tensor: "triton")
    monkeypatch.setattr(curriculum, "_vector_add_kernel", FailingKernel(), raising=False)

    x = torch.ones(3)
    with pytest.raises(RuntimeError, match="simulated GPU launch failure"):
        curriculum.vector_add(x, x)


def test_matmul_small_identity():
    a = torch.eye(4, device=DEVICE)
    b = torch.arange(16.0, device=DEVICE).reshape(4, 4)
    assert torch.allclose(matmul(a, b), b, atol=1e-4)


def test_matmul_random_matches_torch():
    torch.manual_seed(0)
    a = torch.randn(37, 53, device=DEVICE)
    b = torch.randn(53, 29, device=DEVICE)
    assert torch.allclose(matmul(a, b), a @ b, atol=1e-3)


def test_achieved_bandwidth_is_pure_arithmetic_no_gpu_needed():
    gb_s = achieved_bandwidth_gb_s(
        n_elements=1000,
        dtype_bytes=4,
        elapsed_seconds=0.001,
    )
    expected_bytes = 3 * 1000 * 4
    assert gb_s == expected_bytes / 0.001 / 1e9


def test_achieved_bandwidth_zero_time_is_safe():
    assert achieved_bandwidth_gb_s(1000, 4, 0.0) == 0.0


def test_fuse_resume_field_embeddings_matches_manual_weighted_sum():
    skills = _tensor([1.0, 0.0])
    experience = _tensor([0.0, 1.0])
    education = _tensor([1.0, 1.0])
    out = fuse_resume_field_embeddings(
        skills,
        experience,
        education,
        weights=(0.5, 0.3, 0.2),
    )
    expected = skills * 0.5 + experience * 0.3 + education * 0.2
    assert torch.allclose(out, expected, atol=1e-5)
