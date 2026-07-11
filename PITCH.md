# Project Pitch

![HR AI Command Center governance command center hero](./docs/assets/hr-command-center-hero-raster.png)

## One sentence

**HR AI Command Center is an open-source control plane where specialized agents
act, policy evidence grounds their work, and governance keeps sensitive HR
decisions human-reviewed and auditable.**

## The problem

HR automation often separates action from evidence and oversight. A chatbot can
answer a question but cannot safely coordinate a case, pause an onboarding
workflow, show why a resume score changed, or leave an audit trail that an
operator can inspect.

## The product

One application coordinates five workload shapes:

| Workload | Product value | Safety boundary |
|---|---|---|
| Ticket triage | Routes routine and urgent work | Urgent cases escalate to a person |
| Policy Q&A | Answers from versioned policy evidence | Missing or weak evidence triggers review |
| Resume screening | Compares skills and experience to a role | Decision support; never auto-rejects |
| Onboarding | Runs a stateful checklist | Sensitive steps pause for approval |
| Attrition advisory | Surfaces retention risk factors | Starts a conversation; never a punitive verdict |

The durable FastAPI/Postgres control plane works without a model. Fireworks
online inference handles interactive work, Fireworks Batch handles asynchronous
bulk work, and an optional AMD ROCm/vLLM path supports self-hosted inference.
Provider hosts and models are injected and allowlisted.

## Why it is technically interesting

- Typed agent contracts and provider-neutral model routing.
- Postgres + pgvector retrieval with grounded citations.
- Deterministic fallbacks that preserve workflow behavior without hiding model
  unavailability.
- Human checkpoints, PII controls, RBAC modes and append-only audit evidence.
- Visible asynchronous Batch lifecycle rather than fake synchronous progress.
- Portable PyTorch plus optional Triton kernels governed by named-hardware
  correctness and end-to-end performance gates.
- Docker Compose for the evaluation path; Fireworks Serverless for hosted
  inference; Kubernetes is future-state work, not a hackathon dependency.

## AMD and Fireworks evidence boundary

The architecture includes a pinned AMD ROCm/vLLM image, `linux/amd64`
manifests, GPU device mappings and runtime health evidence. Those artifacts show
deployment readiness. Only logs and benchmarks captured on named AMD hardware
prove actual AMD execution or performance.

Fireworks compatibility is proven structurally and by mocked request contracts
in CI. A credentialed smoke test against the injected evaluation endpoint is
still required before claiming live provider compatibility.

## What to show

1. Enter the open-access sandbox without credentials and choose a seeded persona.
2. Ask a policy question and inspect its evidence.
3. Triage an urgent case and show human escalation.
4. Submit or inspect a Fireworks Batch job in visible `PENDING` state.
5. Pause onboarding for approval, then show the audit record.
6. Close on the platform risk-control diagram and the evidence boundary.

## Honest stage

This is a technical showcase and reference implementation, not an enterprise HR
system of record. Tenant isolation, enterprise identity, distributed runtime
state, organization-specific validation and production SLO evidence remain
future work.

See [README.md](./README.md) for current capability status and
[OPEN_SOURCE_LAUNCH.md](./OPEN_SOURCE_LAUNCH.md) for the release gate.
