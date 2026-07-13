"""Fused cosine similarity with a CPU-safe PyTorch fallback.

The Triton path is selected only for CUDA tensors. PyTorch uses the ``cuda``
device API for both NVIDIA CUDA and AMD ROCm builds, so the same check works on
an MI300X host.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

try:
    import triton
    import triton.language as tl
except ImportError:  # Triton is intentionally optional for local CPU development.
    triton = None
    tl = None


if triton is not None:

    @triton.autotune(
        configs=[
            triton.Config({"BLOCK_D": 256, "ROWS_PER_PROGRAM": 1}, num_warps=4),
            triton.Config({"BLOCK_D": 256, "ROWS_PER_PROGRAM": 2}, num_warps=4),
            triton.Config({"BLOCK_D": 512, "ROWS_PER_PROGRAM": 2}, num_warps=4),
            triton.Config({"BLOCK_D": 512, "ROWS_PER_PROGRAM": 4}, num_warps=8),
            triton.Config({"BLOCK_D": 1024, "ROWS_PER_PROGRAM": 4}, num_warps=8),
            triton.Config({"BLOCK_D": 1024, "ROWS_PER_PROGRAM": 8}, num_warps=8),
            triton.Config({"BLOCK_D": 2048, "ROWS_PER_PROGRAM": 1}, num_warps=8),
            triton.Config({"BLOCK_D": 2048, "ROWS_PER_PROGRAM": 2}, num_warps=8),
        ],
        key=["candidate_count", "dimension"],
    )
    @triton.jit
    def _fused_cosine_kernel(
        query_ptr,
        candidates_ptr,
        scores_ptr,
        query_inv_norm_ptr,
        candidate_stride,
        candidate_count,
        dimension: tl.constexpr,
        eps: tl.constexpr,
        BLOCK_D: tl.constexpr,
        ROWS_PER_PROGRAM: tl.constexpr,
    ):
        rows = tl.program_id(0) * ROWS_PER_PROGRAM + tl.arange(0, ROWS_PER_PROGRAM)
        dimensions = tl.arange(0, BLOCK_D)
        dot = tl.zeros((ROWS_PER_PROGRAM,), dtype=tl.float32)
        candidate_square = tl.zeros((ROWS_PER_PROGRAM,), dtype=tl.float32)

        for dimension_start in range(0, dimension, BLOCK_D):
            dimension_offsets = dimension_start + dimensions
            dimension_mask = dimension_offsets < dimension
            query = tl.load(
                query_ptr + dimension_offsets,
                mask=dimension_mask,
                other=0.0,
            ).to(tl.float32)
            candidate_mask = (rows[:, None] < candidate_count) & dimension_mask[None, :]
            candidate = tl.load(
                candidates_ptr + rows[:, None] * candidate_stride + dimension_offsets[None, :],
                mask=candidate_mask,
                other=0.0,
            ).to(tl.float32)
            dot += tl.sum(candidate * query[None, :], axis=1)
            candidate_square += tl.sum(candidate * candidate, axis=1)

        query_inv_norm = tl.load(query_inv_norm_ptr)
        candidate_norm = tl.maximum(tl.sqrt(candidate_square), eps)
        scores = dot * query_inv_norm / candidate_norm
        tl.store(scores_ptr + rows, scores, mask=rows < candidate_count)


def _validate_inputs(query: torch.Tensor, candidates: torch.Tensor) -> None:
    if query.ndim != 1:
        raise ValueError(f"query must be one-dimensional, got shape {tuple(query.shape)}")
    if candidates.ndim != 2:
        raise ValueError(f"candidates must be two-dimensional, got shape {tuple(candidates.shape)}")
    if query.shape[0] != candidates.shape[1]:
        raise ValueError(
            "query and candidate dimensions must match: "
            f"{query.shape[0]} != {candidates.shape[1]}"
        )
    if query.device != candidates.device:
        raise ValueError(
            f"query and candidates must share a device: {query.device} != {candidates.device}"
        )
    if query.dtype != candidates.dtype:
        raise ValueError(
            f"query and candidates must share a dtype: {query.dtype} != {candidates.dtype}"
        )
    if not query.is_floating_point() or not candidates.is_floating_point():
        raise TypeError("query and candidates must use floating-point dtypes")


def active_backend(query: torch.Tensor) -> str:
    """Return the implementation that would process ``query``."""
    if triton is not None and query.is_cuda:
        return "triton"
    return "torch"


def fused_cosine_score(query: torch.Tensor, candidates: torch.Tensor) -> torch.Tensor:
    """Return one cosine-similarity score for each candidate vector."""
    _validate_inputs(query, candidates)

    if candidates.shape[0] == 0:
        return torch.empty(0, device=candidates.device, dtype=torch.float32)

    if active_backend(query) == "torch":
        return F.cosine_similarity(query.unsqueeze(0), candidates, dim=1)

    contiguous_query = query.contiguous()
    contiguous_candidates = candidates.contiguous()
    query_float = contiguous_query.float()
    query_inv_norm = torch.reciprocal(torch.clamp(torch.linalg.vector_norm(query_float), min=1e-8))
    scores = torch.empty(
        contiguous_candidates.shape[0],
        device=contiguous_candidates.device,
        dtype=torch.float32,
    )
    dimension = contiguous_candidates.shape[1]

    def grid(meta):
        return (triton.cdiv(contiguous_candidates.shape[0], meta["ROWS_PER_PROGRAM"]),)

    _fused_cosine_kernel[grid](
        contiguous_query,
        contiguous_candidates,
        scores,
        query_inv_norm,
        contiguous_candidates.stride(0),
        contiguous_candidates.shape[0],
        dimension=dimension,
        eps=1e-8,
    )
    return scores


def top_k(scores: torch.Tensor, k: int) -> tuple[torch.Tensor, torch.Tensor]:
    """Return up to ``k`` scores and indices, ordered from highest to lowest."""
    if scores.ndim != 1:
        raise ValueError(f"scores must be one-dimensional, got shape {tuple(scores.shape)}")
    if k < 0:
        raise ValueError("k must be non-negative")
    return torch.topk(scores, k=min(k, scores.numel()), largest=True, sorted=True)
