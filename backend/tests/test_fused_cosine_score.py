"""Correctness oracle for the fused cosine kernel.

Run this exact file again on the AMD/ROCm instance. Locally it normally checks
the torch fallback against the torch reference; on a GPU it checks the compiled
Triton kernel against that independent reference.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch", reason="optional GPU kernel dependency is not installed")

from kernels.fused_cosine_score import active_backend, fused_cosine_score, top_k  # noqa: E402

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def naive_reference(query: torch.Tensor, candidates: torch.Tensor) -> torch.Tensor:
    return torch.nn.functional.cosine_similarity(query.unsqueeze(0), candidates, dim=1)


def test_matches_reference_small_case():
    """The simplest possible case you can check by hand: 3 candidates, dim 4."""
    query = torch.tensor([1.0, 0.0, 0.0, 0.0], device=DEVICE)
    candidates = torch.tensor(
        [
            [1.0, 0.0, 0.0, 0.0],  # identical to query -> score should be 1.0
            [0.0, 1.0, 0.0, 0.0],  # orthogonal -> score should be 0.0
            [-1.0, 0.0, 0.0, 0.0],  # opposite -> score should be -1.0
        ],
        device=DEVICE,
    )
    scores = fused_cosine_score(query, candidates)
    expected = torch.tensor([1.0, 0.0, -1.0], device=DEVICE)
    assert torch.allclose(scores, expected, atol=1e-5), scores


def test_matches_reference_random_case():
    """Compare a larger randomized case to the readable PyTorch reference."""
    torch.manual_seed(0)
    query = torch.randn(384, device=DEVICE)
    candidates = torch.randn(200, 384, device=DEVICE)

    fused = fused_cosine_score(query, candidates)
    reference = naive_reference(query, candidates)
    assert torch.allclose(fused, reference, atol=1e-4), (fused - reference).abs().max()
    assert active_backend(query) == ("triton" if torch.cuda.is_available() else "torch")


def test_top_k_returns_highest_scores_in_order():
    scores = torch.tensor([0.1, 0.9, 0.5, 0.3, 0.7])
    values, indices = top_k(scores, k=3)
    assert torch.allclose(values, torch.tensor([0.9, 0.7, 0.5]))
    assert indices.tolist() == [1, 4, 2]


def test_top_k_handles_k_larger_than_n():
    """Clamp k when there are fewer candidates than requested."""
    scores = torch.tensor([0.4, 0.8])
    values, indices = top_k(scores, k=10)
    assert values.shape[0] == 2
    assert indices.shape[0] == 2


def test_empty_candidates_return_empty_scores():
    query = torch.ones(7, device=DEVICE)
    candidates = torch.empty(0, 7, device=DEVICE)
    assert fused_cosine_score(query, candidates).shape == (0,)


def test_non_contiguous_inputs_match_reference():
    query = torch.randn(34, device=DEVICE)[::2]
    candidates = torch.randn(23, 34, device=DEVICE)[:, ::2]
    assert not query.is_contiguous()
    assert not candidates.is_contiguous()
    assert torch.allclose(
        fused_cosine_score(query, candidates),
        naive_reference(query, candidates),
        atol=1e-4,
    )


def test_tail_dimension_larger_than_smallest_tile():
    torch.manual_seed(4)
    query = torch.randn(769, device=DEVICE)
    candidates = torch.randn(33, 769, device=DEVICE)
    assert torch.allclose(
        fused_cosine_score(query, candidates),
        naive_reference(query, candidates),
        atol=1e-4,
    )


def test_large_dimension_matches_reference():
    torch.manual_seed(5)
    query = torch.randn(2_048, device=DEVICE)
    candidates = torch.randn(17, 2_048, device=DEVICE)
    assert torch.allclose(
        fused_cosine_score(query, candidates),
        naive_reference(query, candidates),
        atol=1e-4,
    )


def test_mismatched_dtype_is_rejected():
    query = torch.ones(4, dtype=torch.float32)
    candidates = torch.ones(2, 4, dtype=torch.float64)
    with pytest.raises(ValueError, match="share a dtype"):
        fused_cosine_score(query, candidates)


@pytest.mark.parametrize("dtype", [torch.float16, torch.bfloat16, torch.float32])
def test_supported_dtypes_match_reference_on_cpu(dtype):
    if torch.cuda.is_available():
        pytest.skip("dtype portability is exercised by the GPU benchmark matrix")
    query = torch.randn(64, dtype=dtype)
    candidates = torch.randn(9, 64, dtype=dtype)
    tolerance = 2e-2 if dtype in (torch.float16, torch.bfloat16) else 1e-4
    assert torch.allclose(
        fused_cosine_score(query, candidates).float(),
        naive_reference(query, candidates).float(),
        atol=tolerance,
        rtol=tolerance,
    )
