"""Strict opt-in bridge from local vector search to the fused GPU kernel."""

from __future__ import annotations

from dataclasses import dataclass

from core.config import settings


@dataclass(frozen=True)
class GPUKernelEligibility:
    eligible: bool
    reason: str


def eligibility(corpus_size: int) -> GPUKernelEligibility:
    """Check every pre-launch gate without hiding a later kernel failure."""
    if not settings.enable_gpu_kernels:
        return GPUKernelEligibility(False, "ENABLE_GPU_KERNELS is false")
    if corpus_size < settings.gpu_kernel_min_corpus:
        return GPUKernelEligibility(False, "corpus is below GPU_KERNEL_MIN_CORPUS")
    if settings.gpu_kernel_measured_speedup < settings.gpu_kernel_min_speedup:
        return GPUKernelEligibility(False, "measured speedup is below the integration gate")
    try:
        import torch

        from kernels.fused_cosine_score import active_backend
    except ImportError:
        return GPUKernelEligibility(False, "torch or Triton kernel package is unavailable")
    if not torch.cuda.is_available():
        return GPUKernelEligibility(False, "CUDA/ROCm device is unavailable")
    probe = torch.empty(1, device="cuda")
    if active_backend(probe) != "triton":
        return GPUKernelEligibility(False, "Triton backend is unavailable")
    return GPUKernelEligibility(True, "all GPU kernel gates passed")


def score_candidates(query: list[float], candidates: list[list[float]]) -> list[float]:
    """Score on GPU; launch/compile/OOM errors intentionally propagate."""
    import torch

    from kernels.fused_cosine_score import fused_cosine_score

    query_tensor = torch.tensor(query, device="cuda", dtype=torch.float32)
    candidate_tensor = torch.tensor(candidates, device="cuda", dtype=torch.float32)
    return fused_cosine_score(query_tensor, candidate_tensor).cpu().tolist()
