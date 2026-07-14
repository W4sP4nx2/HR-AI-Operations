# Govern.ai production agent platform contract

Status: design-approved Phase 1 contract, 2026-07-14

This document is the implementation target for large-resume processing,
evidence-first chat, governed agents, and the command center. It is deliberately
provider-neutral: Fireworks AI and AMD hardware + vLLM serving Gemma are separate
products behind the same typed gateway, not the same runtime.

## Nail in the head

The legacy product path is a synchronous demo path. It flattens a resume into a
20,000-character string, runs parsing/scoring/enrichment in one request, trusts
browser-supplied chat history, and treats SQLite/runtime schema creation as a
production persistence strategy. That is why large documents and live chatbot
failure modes are not reliable under real concurrency.

Phase 1 separates the system into:

```text
Supabase Auth + PostgreSQL/pgvector + Storage
        |
        v
tenant-scoped API -> durable Postgres jobs -> bounded workers
        |                       |
        v                       v
evidence-first chat       page/chunk resume analysis
        |                       |
        +-----------> typed agent gates/certification
                                    |
                                    v
                        human approval or committed result
                                    |
                                    v
                  Ops snapshot -> Realtime deltas -> 3D + 2D UI
```

## Product contracts

### Capacity and SLO baseline

- 100 concurrent chat users.
- 1,000 resumes/day.
- Up to 50 pages or 25 MB per resume.
- Ten concurrent resume jobs per worker pool.
- Chat accepted p95 < 300 ms; first token p95 < 2 s when provider capacity is healthy.
- Resume upload acknowledgement p95 < 500 ms.
- Job/livewire state visible within 2 s.
- Tenant quotas and spend budgets are admission gates, not after-the-fact reports.

### Resume jobs

`POST /resume-jobs` returns `202 Accepted` with a durable `job_id` and status URL.
The upload uses a signed Supabase Storage URL; the API does not buffer the full
document through the agent process.

Required operations:

- `GET /resume-jobs/{job_id}` — state, progress, page coverage, evidence, errors, cost, HITL status.
- `POST /resume-jobs/{job_id}/cancel` — compare-and-set cancellation.
- `POST /resume-jobs/{job_id}/retry` — bounded retry with a new attempt record.
- idempotency key on submission; at-least-once delivery with idempotent handlers.

The pipeline stores a document manifest, extracts pages independently, chunks
with bounded token size/overlap, and merges structured evidence. A completeness
gate blocks fit recommendations when pages are missing, OCR quality is low, or
the parser reports truncation. Partial work is `needs_review`, never a confident
score.

### Chat

Chat sessions are server-owned and tenant/user scoped. The server loads a rolling
summary plus recent turns from PostgreSQL; browser history is a hint, not the
source of truth. Messages require idempotency keys. SSE/WebSocket events carry
`event_id`, `trace_id`, sequence, and schema version so a client can reconnect
without duplicating a model call.

Answers require retrieved policy/workflow evidence, citations, confidence, model
route, and a trace ID. A live provider/tool failure is `unavailable` or
`needs_review`; it is not silently rewritten as a different answer path.

### Agent lifecycle

Every run uses the same typed state machine:

```text
RECEIVED -> VALIDATED -> PLANNED -> RUNNING -> CERTIFIED
                         |                    |
                         v                    v
                      FAILED             HUMAN_REVIEW -> COMMITTED
                         |                    |
                         +-> RETRYABLE   REJECTED/EXPIRED/CANCELLED
```

Agents may autonomously parse, retrieve, classify, score, summarize, draft, and
create an internal review task. Human approval is required for candidate
disposition, onboarding completion, compensation/benefits changes, attrition
interventions, policy publication, and external notifications. Adverse action,
cross-tenant access, audit deletion, and runtime guardrail mutation are
prohibited.

CrewAI is a bounded reasoning adapter. The product orchestrator and PostgreSQL
workflow state own routing, retries, tenancy, budgets, certification, approvals,
and side effects.

### Storage and identity

- Supabase Auth is the identity source.
- `tenant_memberships` and role claims (`viewer`, `manager`, `admin`) are required.
- PostgreSQL RLS protects every tenant-owned table.
- User-facing queries use caller-scoped identity; service-role keys are limited to workers/migrations.
- Original resumes and page artifacts live in private Storage with signed short-lived access and configurable retention (30 days is the initial default).
- Audit/evidence rows contain redacted content and hashes, not unrestricted raw documents.
- Alembic migrations replace runtime `create_all` in production; vector reindex is an explicit migration/job.

### Providers

The model gateway enforces task/tenant allowlists, structured schemas, token and
cost budgets, timeout, retry, circuit-breaker, privacy, and hardware capability.

- Fireworks AI: hosted chat and short structured inference.
- AMD + vLLM + Gemma: separately deployed GPU product for batch/vision/large extraction when runtime evidence is healthy.
- Local/open-source/deterministic: development and no-provider operation, with its own capability label.

After a live call starts, failure is surfaced as a typed recovery state; there is
no silent cross-provider fallback.

### Livewire command center

`GET /ops/overview` is the authoritative tenant-scoped snapshot. It includes
agents, queues, cases, provider/hardware capability, gates, provenance, and
workflow edges. Supabase Realtime publishes ordered state deltas. The 3D scene
and accessible 2D table are projections of the same snapshot; they never infer
health from missing data.

3D is progressive enhancement: reduced motion, no-WebGL, mobile, or render
failure automatically uses the 2D state table. Synthetic fixtures are explicitly
labelled and never presented as live production state.

## Required release gates

- Tenant isolation/RLS and guessed-ID tests.
- Resume parser security: malformed PDFs, decompression bombs, SSRF, PII leakage, prompt injection.
- Resume completeness, extraction quality, bias invariance, cost, and p95 processing tests.
- Chat grounding, citation correctness, no-evidence refusal, tool correctness, resumable stream, and provider-outage tests.
- 100-concurrent-chat and ten-worker resume load tests.
- Idempotency/duplicate suppression and retry-storm tests.
- Human approval, expiry, escalation, and stale-result re-certification tests.
- OpenTelemetry trace/metric coverage without raw PII or secrets.

No AMD performance, Fireworks billing, production compliance, or autonomous HR
decision claim is publishable until its named runtime/evidence gate passes.
