# Portable GPU Optimization

The production-first optimization is bounded embedding and SQL batching. Triton
kernels remain optional until named-hardware benchmarks prove end-to-end value.

## Current status

| Item | Status | Evidence |
|---|---|---|
| Batch embedding | Implemented | `Embedder.embed_batch`, batching tests |
| Bounded SQL vector writes | Implemented | pgvector/local stores, `[2,2,1]` test |
| Ingestion/retrieval metrics | Implemented | Prometheus counters/histograms |
| Fused cosine row tiling | Implemented, GPU verification pending | CPU oracle + cloud harness |
| Query norm reuse | Implemented | one norm per fused call |
| Reduction/bias/row autotune candidates | Implemented, untuned | no speed claim |
| Grouped/autotuned matmul candidates | Implemented, untuned | no speed claim |
| Local GPU retrieval bridge | Guarded, disabled | six pre-launch gates |
| AMD benchmark | Not run | requires provisioned ROCm host |
| NVIDIA benchmark | Not run | requires provisioned CUDA host |

## Product path

Policy ingestion now:

1. chunks a document;
2. calls `embed_batch()` with `EMBEDDING_BATCH_SIZE`;
3. preserves input/vector ordering with strict zip checks;
4. writes rows in `VECTOR_WRITE_BATCH_SIZE` groups;
5. records embedding duration/count and vector-write duration/count.

Useful PromQL:

```promql
sum(rate(hrcc_embedding_chunks_total[5m]))
sum(rate(hrcc_embedding_batch_duration_seconds_sum[5m]))
  / clamp_min(sum(rate(hrcc_embedding_batch_duration_seconds_count[5m])), 1)
histogram_quantile(0.95, sum by (le, backend) (rate(hrcc_retrieval_duration_seconds_bucket[5m])))
```

pgvector HNSW remains the production retrieval engine. Batch optimization helps
both local embeddings and remote Fireworks embedding calls without requiring a
GPU in the application container.

## Fused cosine launch geometry

The Triton kernel uses:

- one program for a tile of candidate rows;
- dimension tiles of 256, 512, 1024, or 2048;
- 1, 2, 4, or 8 rows per program;
- 4 or 8 warps;
- a loop across the complete logical dimension.

Because the kernel loops across dimension tiles, a 256 tile cannot truncate a
384- or 769-dimensional vector. Query inverse norm is computed once per call;
candidate dot products and norms remain fused. Autotuning selects a candidate
per `(candidate_count, dimension)` on the actual device.

These configurations are hypotheses, not recommendations. Register pressure,
occupancy, cache behavior, and backend compiler quality must be measured.
AMD Instinct targets used by the proposed hipVS experiment use a 64-thread
wavefront, but Triton's `num_warps` remains a compiler launch parameter rather
than proof of wavefront optimization. Do not add or pitch a boolean
`AMD_WAVEFRONT_OPTIMIZED` flag; publish compiler metadata and named-hardware
benchmark JSON instead.

## Curriculum kernels

- `vector_add`: block/warp autotuning retained.
- `bias_add` and `row_sum`: dimension-tile and warp candidates loop over the full
  dimension.
- `partial_sums`: 1024/2048/4096 reduction tiles within the requested logical
  chunk, so block-boundary semantics remain stable.
- `matmul`: grouped M-major mapping with 32/64/128 M/N candidates, 32/64 K,
  4/8 warps, and 2-4 stages.

No curriculum kernel is used by pgvector, resume scoring, or normal laptop RAG.

## Benchmark harness

Run only on GPU hosts:

```bash
cd backend
python -m benchmarks.benchmark_kernels \
  --rows 10000 --dim 384 --dtype fp32 \
  --output benchmark-mi300x.json

python -m benchmarks.benchmark_kernels \
  --matrix --max-gpu-memory-mb 2048 \
  --output benchmark-full.json
```

The harness refuses CPU execution before tensor allocation, skips unsupported
BF16, caps estimated memory, and records:

- device name, Torch version, CUDA/HIP version, memory;
- Triton and PyTorch p50/p95;
- p50 speedup and effective GB/s;
- peak allocated GPU memory;
- maximum absolute error.

Matrix: rows `32, 256, 1K, 10K, 100K`; dimensions
`256, 384, 512, 768, 1024, 2048`; dtypes FP16/BF16/FP32.

## Integration gate

Local GPU vector scoring remains off unless all conditions hold:

1. `ENABLE_GPU_KERNELS=true`;
2. corpus is at least `GPU_KERNEL_MIN_CORPUS` (default 10,000);
3. `GPU_KERNEL_MEASURED_SPEEDUP >= GPU_KERNEL_MIN_SPEEDUP` (default 1.5);
4. Torch is installed;
5. CUDA/ROCm is available;
6. Triton is the active backend.

If a pre-launch condition fails, local CPU scoring is selected. Once GPU launch
starts, compile/launch/OOM errors propagate and are never replaced silently.
This bridge is local-vector-only and is never used for a single resume/JD pair.

## Results

No performance result is published yet.

| Hardware | Software | Shape/dtype | PyTorch p50/p95 | Triton p50/p95 | Speedup | Error | Peak memory |
|---|---|---|---|---|---:|---:|---:|
| AMD | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| NVIDIA | Pending | Pending | Pending | Pending | Pending | Pending | Pending |

Populate this table only from committed benchmark JSON produced on named
hardware. Kernel-only speedup does not authorize integration; repeat an
end-to-end policy retrieval/load benchmark before setting the measured-speedup
environment variable.
