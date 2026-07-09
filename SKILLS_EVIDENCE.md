# Engineering Skills Evidence

This document maps project capabilities to inspectable implementation evidence.
Current status belongs in [README.md](./README.md); unsupported claims are
explicitly excluded.

## Generative AI and agents

| Skill | Evidence |
|---|---|
| Typed model output | `backend/agents/contracts.py` and contract tests |
| Multi-agent orchestration | LangGraph workflows, CrewAI agents and Pydantic AI chat |
| Provider routing | `backend/core/llm_factory.py`, role-based allowlisted models |
| Tool use | Policy search, case lookup, triage and attrition tools |
| Structured requests | Fireworks JSON/function-calling contracts and tests |
| Asynchronous inference | Fireworks Batch submit, normalized status and UI polling |
| Safe degradation | Deterministic classifiers, embeddings and explanations |

## Retrieval and data engineering

- Postgres + pgvector HNSW is the default production RAG backend.
- Policy ingestion extracts, chunks, embeds and records document metadata.
- Retrieval returns cited evidence and confidence for policy synthesis.
- Local and Qdrant adapters remain optional development paths.
- Embedding dimensions are discovered from the configured provider rather than
  assumed.

## ML lifecycle and evaluation

- The attrition advisory wraps a scikit-learn model with explicit features,
  synthetic-data limitations and human-review output.
- Deterministic baselines have documented discard criteria.
- Agent contracts, golden cases, security behavior and compliance checks run in
  CI.
- Feedback is collected as evidence; it does not automatically retrain or steer
  production models.

## GPU and performance engineering

- Portable PyTorch references exist for every optional Triton kernel.
- Correctness tests include tail shapes and block-boundary cases.
- GPU fallback is selected before launch; runtime compile, launch, OOM and
  numerical failures are not swallowed.
- The AMD deployment path uses a pinned ROCm/vLLM image and explicit GPU devices.
- No performance claim is published without named hardware, software versions,
  shape, dtype, p50/p95, numerical error and memory evidence.

## Infrastructure and operations

- FastAPI and Next.js images target `linux/amd64`.
- Docker Compose is the default evaluation path.
- Kubernetes, HPA, GitOps and observability manifests are production templates,
  not evidence of live scale.
- Scaling projections are labeled simulated.
- Provider bypass, manifests, tests, frontend build, documentation and secret
  checks are part of the release process.

## Product and governance

- Open-access evaluation requires no login and uses seeded advisory personas.
- Enforced deployments apply RBAC to navigation and API actions.
- PII controls, human approvals and audit evidence are first-class workflows.
- Resume and attrition outputs are decision support, never autonomous adverse
  actions.

The project demonstrates production-shaped engineering judgment by keeping the
model useful but subordinate to durable state, evidence and human authority.
