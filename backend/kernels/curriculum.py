"""Progressive Triton kernels with PyTorch fallbacks for local development."""

from __future__ import annotations

import torch

try:
    import triton
    import triton.language as tl

    _TRITON_AVAILABLE = True
except ImportError:  # Triton is optional on CPU-only development machines.
    triton = None
    tl = None
    _TRITON_AVAILABLE = False


def active_backend(tensor: torch.Tensor) -> str:
    """Return the implementation that would process ``tensor``."""
    return "triton" if _TRITON_AVAILABLE and tensor.is_cuda else "torch"


def _require_float(tensor: torch.Tensor, name: str) -> None:
    if not tensor.is_floating_point():
        raise TypeError(f"{name} must use a floating-point dtype")


def _require_pair(x: torch.Tensor, y: torch.Tensor, *, same_shape: bool = True) -> None:
    _require_float(x, "x")
    _require_float(y, "y")
    if x.device != y.device:
        raise ValueError(f"tensors must share a device: {x.device} != {y.device}")
    if x.dtype != y.dtype:
        raise ValueError(f"tensors must share a dtype: {x.dtype} != {y.dtype}")
    if same_shape and x.shape != y.shape:
        raise ValueError(f"tensor shapes must match: {tuple(x.shape)} != {tuple(y.shape)}")


if _TRITON_AVAILABLE:

    @triton.autotune(
        configs=[
            triton.Config({"BLOCK_SIZE": 256}, num_warps=4),
            triton.Config({"BLOCK_SIZE": 512}, num_warps=4),
            triton.Config({"BLOCK_SIZE": 1024}, num_warps=8),
            triton.Config({"BLOCK_SIZE": 2048}, num_warps=8),
        ],
        key=["n"],
    )
    @triton.jit
    def _vector_add_kernel(x_ptr, y_ptr, out_ptr, n, BLOCK_SIZE: tl.constexpr):
        offsets = tl.program_id(0) * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
        mask = offsets < n
        x = tl.load(x_ptr + offsets, mask=mask)
        y = tl.load(y_ptr + offsets, mask=mask)
        tl.store(out_ptr + offsets, x + y, mask=mask)


def vector_add(x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    """Return the elementwise sum of two equal-shaped tensors."""
    _require_pair(x, y)
    if active_backend(x) == "torch":
        return x + y

    x_contiguous = x.contiguous()
    y_contiguous = y.contiguous()
    out = torch.empty_like(x_contiguous)
    n = x_contiguous.numel()

    def grid(meta):
        return (triton.cdiv(n, meta["BLOCK_SIZE"]),)

    _vector_add_kernel[grid](x_contiguous, y_contiguous, out, n)
    return out.reshape(x.shape)


def achieved_bandwidth_gb_s(
    n_elements: int,
    dtype_bytes: int,
    elapsed_seconds: float,
) -> float:
    """Calculate effective bandwidth for two reads and one write per element."""
    if n_elements < 0 or dtype_bytes <= 0:
        raise ValueError("n_elements must be non-negative and dtype_bytes must be positive")
    if elapsed_seconds <= 0:
        return 0.0
    return (3 * n_elements * dtype_bytes / elapsed_seconds) / 1e9


def fuse_resume_field_embeddings(
    skills_emb: torch.Tensor,
    experience_emb: torch.Tensor,
    education_emb: torch.Tensor,
    weights: tuple[float, float, float] = (0.5, 0.35, 0.15),
) -> torch.Tensor:
    """Combine independently embedded resume sections into one weighted vector."""
    _require_pair(skills_emb, experience_emb)
    _require_pair(skills_emb, education_emb)
    if len(weights) != 3:
        raise ValueError("weights must contain skills, experience, and education values")

    skills_weight, experience_weight, education_weight = weights
    combined = vector_add(
        skills_emb * skills_weight,
        experience_emb * experience_weight,
    )
    return vector_add(combined, education_emb * education_weight)


if _TRITON_AVAILABLE:

    @triton.autotune(
        configs=[
            triton.Config({"BLOCK_D": 256}, num_warps=4),
            triton.Config({"BLOCK_D": 512}, num_warps=4),
            triton.Config({"BLOCK_D": 1024}, num_warps=8),
        ],
        key=["dim"],
    )
    @triton.jit
    def _bias_add_kernel(
        x_ptr, bias_ptr, out_ptr, n_rows, dim: tl.constexpr, BLOCK_D: tl.constexpr
    ):
        row = tl.program_id(0)
        offsets = tl.arange(0, BLOCK_D)
        for dimension_start in range(0, dim, BLOCK_D):
            dimension_offsets = dimension_start + offsets
            mask = dimension_offsets < dim
            x = tl.load(x_ptr + row * dim + dimension_offsets, mask=mask)
            bias = tl.load(bias_ptr + dimension_offsets, mask=mask)
            tl.store(out_ptr + row * dim + dimension_offsets, x + bias, mask=mask)


def bias_add(x: torch.Tensor, bias: torch.Tensor) -> torch.Tensor:
    """Broadcast a one-dimensional bias across a two-dimensional tensor."""
    _require_pair(x, bias, same_shape=False)
    if x.ndim != 2 or bias.ndim != 1 or x.shape[1] != bias.shape[0]:
        raise ValueError(
            f"expected x [N, D] and bias [D], got {tuple(x.shape)} and {tuple(bias.shape)}"
        )
    if active_backend(x) == "torch":
        return x + bias

    x_contiguous = x.contiguous()
    bias_contiguous = bias.contiguous()
    rows, dimension = x_contiguous.shape
    out = torch.empty_like(x_contiguous)
    _bias_add_kernel[(rows,)](
        x_contiguous,
        bias_contiguous,
        out,
        rows,
        dimension,
    )
    return out


if _TRITON_AVAILABLE:

    @triton.jit
    def _residual_add_kernel(
        x_ptr,
        sublayer_ptr,
        out_ptr,
        alpha,
        n,
        BLOCK_SIZE: tl.constexpr,
    ):
        offsets = tl.program_id(0) * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
        mask = offsets < n
        x = tl.load(x_ptr + offsets, mask=mask)
        sublayer = tl.load(sublayer_ptr + offsets, mask=mask)
        tl.store(out_ptr + offsets, x + alpha * sublayer, mask=mask)


def residual_add(
    x: torch.Tensor,
    sublayer_out: torch.Tensor,
    alpha: float = 1.0,
    block_size: int = 1024,
) -> torch.Tensor:
    """Return ``x + alpha * sublayer_out``."""
    _require_pair(x, sublayer_out)
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if active_backend(x) == "torch":
        return x + alpha * sublayer_out

    x_contiguous = x.contiguous()
    sublayer_contiguous = sublayer_out.contiguous()
    out = torch.empty_like(x_contiguous)
    n = x_contiguous.numel()
    _residual_add_kernel[(triton.cdiv(n, block_size),)](
        x_contiguous,
        sublayer_contiguous,
        out,
        alpha,
        n,
        BLOCK_SIZE=block_size,
    )
    return out.reshape(x.shape)


if _TRITON_AVAILABLE:

    @triton.jit
    def _weight_update_kernel(weight_ptr, grad_ptr, learning_rate, n, BLOCK_SIZE: tl.constexpr):
        offsets = tl.program_id(0) * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
        mask = offsets < n
        weight = tl.load(weight_ptr + offsets, mask=mask)
        grad = tl.load(grad_ptr + offsets, mask=mask)
        tl.store(weight_ptr + offsets, weight - learning_rate * grad, mask=mask)


def weight_update_(
    weight: torch.Tensor,
    grad: torch.Tensor,
    lr: float,
    block_size: int = 1024,
) -> torch.Tensor:
    """Apply an in-place SGD update and return ``weight``."""
    _require_pair(weight, grad)
    if not weight.is_contiguous():
        raise ValueError("weight must be contiguous for an in-place update")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if active_backend(weight) == "torch":
        weight.add_(grad, alpha=-lr)
        return weight

    grad_contiguous = grad.contiguous()
    n = weight.numel()
    _weight_update_kernel[(triton.cdiv(n, block_size),)](
        weight,
        grad_contiguous,
        lr,
        n,
        BLOCK_SIZE=block_size,
    )
    return weight


if _TRITON_AVAILABLE:

    @triton.autotune(
        configs=[
            triton.Config({"BLOCK_D": 256}, num_warps=4),
            triton.Config({"BLOCK_D": 512}, num_warps=4),
            triton.Config({"BLOCK_D": 1024}, num_warps=8),
        ],
        key=["dim"],
    )
    @triton.jit
    def _row_sum_kernel(x_ptr, out_ptr, dim: tl.constexpr, BLOCK_D: tl.constexpr):
        row = tl.program_id(0)
        offsets = tl.arange(0, BLOCK_D)
        total = 0.0
        for dimension_start in range(0, dim, BLOCK_D):
            dimension_offsets = dimension_start + offsets
            x = tl.load(
                x_ptr + row * dim + dimension_offsets,
                mask=dimension_offsets < dim,
                other=0.0,
            )
            total += tl.sum(x, axis=0)
        tl.store(out_ptr + row, total)


def row_sum(x: torch.Tensor) -> torch.Tensor:
    """Reduce each row of a two-dimensional tensor to one sum."""
    _require_float(x, "x")
    if x.ndim != 2:
        raise ValueError(f"x must be two-dimensional, got shape {tuple(x.shape)}")
    if active_backend(x) == "torch":
        return x.sum(dim=1)

    x_contiguous = x.contiguous()
    rows, dimension = x_contiguous.shape
    out = torch.empty(rows, device=x.device, dtype=x.dtype)
    _row_sum_kernel[(rows,)](
        x_contiguous,
        out,
        dimension,
    )
    return out


if _TRITON_AVAILABLE:

    @triton.autotune(
        configs=[
            triton.Config({"BLOCK_TILE": 1024}, num_warps=4),
            triton.Config({"BLOCK_TILE": 2048}, num_warps=8),
            triton.Config({"BLOCK_TILE": 4096}, num_warps=8),
        ],
        key=["n", "CHUNK_SIZE"],
    )
    @triton.jit
    def _partial_sum_kernel(
        x_ptr,
        partials_ptr,
        n,
        CHUNK_SIZE: tl.constexpr,
        BLOCK_TILE: tl.constexpr,
    ):
        chunk_start = tl.program_id(0) * CHUNK_SIZE
        offsets = tl.arange(0, BLOCK_TILE)
        total = 0.0
        for tile_start in range(0, CHUNK_SIZE, BLOCK_TILE):
            indices = chunk_start + tile_start + offsets
            in_chunk = tile_start + offsets < CHUNK_SIZE
            values = tl.load(
                x_ptr + indices,
                mask=(indices < n) & in_chunk,
                other=0.0,
            ).to(tl.float32)
            total += tl.sum(values, axis=0)
        tl.store(partials_ptr + tl.program_id(0), total)


def partial_sums(x: torch.Tensor, block_size: int = 4096) -> torch.Tensor:
    """Reduce a flat tensor into one float32 partial sum per block."""
    _require_float(x, "x")
    if x.ndim != 1:
        raise ValueError(f"x must be one-dimensional, got shape {tuple(x.shape)}")
    if block_size <= 0 or block_size & (block_size - 1):
        raise ValueError("block_size must be a positive power of two")
    if x.numel() == 0:
        return torch.empty(0, device=x.device, dtype=torch.float32)

    block_count = (x.numel() + block_size - 1) // block_size
    if active_backend(x) == "torch":
        return torch.stack(
            [chunk.to(torch.float32).sum() for chunk in x.contiguous().split(block_size)]
        )

    x_contiguous = x.contiguous()
    partials = torch.empty(block_count, device=x.device, dtype=torch.float32)
    _partial_sum_kernel[(block_count,)](
        x_contiguous,
        partials,
        x_contiguous.numel(),
        CHUNK_SIZE=block_size,
    )
    return partials


def multi_pass_sum(x: torch.Tensor, block_size: int = 4096) -> torch.Tensor:
    """Reduce an arbitrarily long vector by repeatedly combining block sums."""
    _require_float(x, "x")
    if x.ndim != 1:
        raise ValueError(f"x must be one-dimensional, got shape {tuple(x.shape)}")
    if x.numel() == 0:
        return torch.zeros((), device=x.device, dtype=torch.float32)

    partials = x
    while partials.numel() > 1:
        partials = partial_sums(partials, block_size=block_size)
    return partials[0]


def two_pass_sum(x: torch.Tensor, block_size: int = 4096) -> torch.Tensor:
    """Compatibility name; inputs up to ``block_size**2`` finish in two passes."""
    return multi_pass_sum(x, block_size=block_size)


if _TRITON_AVAILABLE:

    @triton.autotune(
        configs=[
            triton.Config(
                {"BLOCK_M": 32, "BLOCK_N": 32, "BLOCK_K": 32, "GROUP_M": 4},
                num_warps=4,
                num_stages=2,
            ),
            triton.Config(
                {"BLOCK_M": 64, "BLOCK_N": 64, "BLOCK_K": 32, "GROUP_M": 8},
                num_warps=4,
                num_stages=3,
            ),
            triton.Config(
                {"BLOCK_M": 64, "BLOCK_N": 128, "BLOCK_K": 64, "GROUP_M": 8},
                num_warps=8,
                num_stages=3,
            ),
            triton.Config(
                {"BLOCK_M": 128, "BLOCK_N": 64, "BLOCK_K": 64, "GROUP_M": 8},
                num_warps=8,
                num_stages=4,
            ),
        ],
        key=["rows", "columns", "inner"],
    )
    @triton.jit
    def _matmul_kernel(
        a_ptr,
        b_ptr,
        c_ptr,
        rows,
        columns,
        inner,
        stride_am,
        stride_ak,
        stride_bk,
        stride_bn,
        stride_cm,
        stride_cn,
        BLOCK_M: tl.constexpr,
        BLOCK_N: tl.constexpr,
        BLOCK_K: tl.constexpr,
        GROUP_M: tl.constexpr,
    ):
        program_id = tl.program_id(0)
        programs_m = tl.cdiv(rows, BLOCK_M)
        programs_n = tl.cdiv(columns, BLOCK_N)
        programs_per_group = GROUP_M * programs_n
        group_id = program_id // programs_per_group
        first_program_m = group_id * GROUP_M
        group_size_m = tl.minimum(programs_m - first_program_m, GROUP_M)
        program_m = first_program_m + (program_id % programs_per_group) % group_size_m
        program_n = (program_id % programs_per_group) // group_size_m

        offsets_m = program_m * BLOCK_M + tl.arange(0, BLOCK_M)
        offsets_n = program_n * BLOCK_N + tl.arange(0, BLOCK_N)
        offsets_k = tl.arange(0, BLOCK_K)
        accumulator = tl.zeros((BLOCK_M, BLOCK_N), dtype=tl.float32)

        for k_start in range(0, inner, BLOCK_K):
            a = tl.load(
                a_ptr + offsets_m[:, None] * stride_am + (offsets_k[None, :] + k_start) * stride_ak,
                mask=(offsets_m[:, None] < rows) & (offsets_k[None, :] + k_start < inner),
                other=0.0,
            )
            b = tl.load(
                b_ptr + (offsets_k[:, None] + k_start) * stride_bk + offsets_n[None, :] * stride_bn,
                mask=(offsets_k[:, None] + k_start < inner) & (offsets_n[None, :] < columns),
                other=0.0,
            )
            accumulator += tl.dot(a, b)

        output_mask = (offsets_m[:, None] < rows) & (offsets_n[None, :] < columns)
        tl.store(
            c_ptr + offsets_m[:, None] * stride_cm + offsets_n[None, :] * stride_cn,
            accumulator,
            mask=output_mask,
        )


def matmul(
    a: torch.Tensor,
    b: torch.Tensor,
) -> torch.Tensor:
    """Multiply two matrices using a readable, untuned tiled kernel."""
    _require_pair(a, b, same_shape=False)
    if a.ndim != 2 or b.ndim != 2:
        raise ValueError("a and b must both be two-dimensional")
    if a.shape[1] != b.shape[0]:
        raise ValueError(f"inner dimensions must match: {a.shape[1]} != {b.shape[0]}")
    if active_backend(a) == "torch":
        return a @ b

    rows, inner = a.shape
    columns = b.shape[1]
    out = torch.empty((rows, columns), device=a.device, dtype=torch.float32)

    def grid(meta):
        return (triton.cdiv(rows, meta["BLOCK_M"]) * triton.cdiv(columns, meta["BLOCK_N"]),)

    _matmul_kernel[grid](
        a,
        b,
        out,
        rows,
        columns,
        inner,
        a.stride(0),
        a.stride(1),
        b.stride(0),
        b.stride(1),
        out.stride(0),
        out.stride(1),
    )
    return out
