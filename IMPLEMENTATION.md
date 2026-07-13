# Implementation Guide

This is the engineering map for the current application. Product truth and
capability status live in [README.md](./README.md); product boundaries live in
[PRODUCT.md](./PRODUCT.md); operational detail lives in
[PLATFORM_OPERATIONS.md](./PLATFORM_OPERATIONS.md).

## System shape

| Layer | Current implementation | Boundary |
|---|---|---|
| Product UI | Next.js 16 operator console and employee assistant | Open access is for seeded evaluation; enforced deployments require auth |
| Workflow API | FastAPI routes, agent registry, cases, approvals and audit | Durable state remains usable without model inference |
| Agent layer | Triage, policy Q&A, resume screening, onboarding and attrition advisory | Typed outputs, bounded tools and human escalation |
| Retrieval | Postgres + pgvector HNSW by default | Qdrant and local stores are optional development paths |
| Inference | Deterministic fallback, Fireworks online/Batch, optional AMD/vLLM | Hosts and model IDs are injected; allowlists prevent model bypass |
| Acceleration | Portable PyTorch plus optional Triton kernels | Integration requires named-hardware correctness and end-to-end speed evidence |

## Runtime modes

1. **Zero-secret evaluation:** deterministic workflows, seeded data and no model
   spend.
2. **Fireworks online:** allowlisted interactive inference through
   `FIREWORKS_BASE_URL`.
3. **Fireworks Batch:** asynchronous bulk work with visible `PENDING` state and
   polling.
4. **AMD/vLLM:** self-hosted OpenAI-compatible inference through an injected
   endpoint; the supplied overlay targets a pinned AMD ROCm image.

None of these modes changes the governance contract: sensitive outcomes remain
advisory, reviewable and auditable.

## Engineering priorities

### Current release gate

- Keep all provider construction behind `backend/core/llm_factory.py`.
- Keep pgvector HNSW as the default production retrieval backend.
- Preserve CPU-only development and explicit deterministic fallbacks.
- Validate typed agent contracts, negative cases and route behavior.
- Keep deployment and performance claims tied to checkable evidence.

### Next measured work

- Run the AMD kernel and vLLM suites on named ROCm hardware.
- Record hardware, software, shape, dtype, p50/p95, numerical error and memory.
- Run a credentialed Fireworks smoke test outside CI.
- Add end-to-end retrieval quality and browser workflow evaluation.

### Deferred until justified

- Multi-tenant isolation and enterprise identity.
- Distributed queues, rate limits and WebSocket fan-out.
- Managed Kubernetes and autoscaling based on live telemetry.
- Fine-tuning, reranking or additional model providers without a measured need.

## Where to continue

- Product workflows: [USECASES.md](./USECASES.md)
- Agent contracts: [AGENT_PLAYBOOK.md](./AGENT_PLAYBOOK.md)
- Model lifecycle: [GENAI_LIFECYCLE.md](./GENAI_LIFECYCLE.md)
- GPU criteria: [GPU_OPTIMIZATION.md](./GPU_OPTIMIZATION.md)
- Deployment: [DEPLOYMENT.md](./DEPLOYMENT.md)
- Pre-push checks: [OPEN_SOURCE_LAUNCH.md](./OPEN_SOURCE_LAUNCH.md)
