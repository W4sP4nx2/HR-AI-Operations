# Showcase Readiness

_Reviewed: 2026-07-09. This is a release-readiness view, not a live status page._

## Current judgment

The project is suitable for a technical showcase with seeded or synthetic data.
It is not represented as an enterprise HR system of record or as proof of
production scale.

## Ready

- The full application works without a model key through deterministic paths.
- Fireworks online and Batch paths use injected hosts and allowlisted models.
- Batch jobs expose an asynchronous `PENDING` state instead of appearing stuck.
- Postgres + pgvector is the production retrieval path.
- Human approvals, PII controls, RBAC modes and audit evidence are visible.
- AMD/vLLM, Kubernetes and Triton artifacts are clearly separated from measured
  runtime claims.
- Docker images and manifests are checked for `linux/amd64` compatibility.

## Evidence still required for stronger claims

- A credentialed Fireworks smoke test against the actual evaluation endpoint.
- AMD runtime logs from named hardware.
- Kernel and end-to-end benchmarks with full reproducibility metadata.
- Live multi-pod and load-test results before claiming production scale.
- Organization-specific legal, privacy, bias and model validation before real
  employee data is used.

## Showcase rules

1. Use seeded or synthetic data.
2. Label open-access personas as advisory.
3. Call deterministic output a fallback, not model inference.
4. Call scaling projections simulated until backed by telemetry.
5. Do not claim AMD execution from a manifest alone.
6. Keep adverse employment outcomes under qualified human review.

Run [OPEN_SOURCE_LAUNCH.md](./OPEN_SOURCE_LAUNCH.md) before pushing or recording
the showcase.
