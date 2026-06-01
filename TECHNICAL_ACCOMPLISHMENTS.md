# HR AI Command Center — Backend Technical Accomplishments

A reference for the backend's notable engineering decisions, each **grounded in
the codebase and verified by tests** (169 passed / 3 skipped on `main`). Numbers
quoted below are *measured*, not estimated. Where something is only structurally
guaranteed (not exercised against a live key), it says so — honesty is the point.

**Stack:** FastAPI · async SQLAlchemy Core (SQLite ↔ Postgres) · Pydantic AI ·
LangGraph (in-process) · CrewAI · sentence-transformers / lexical embeddings ·
pgvector (HNSW) / zero-dependency SQLite cosine. Runs end-to-end with **no API
key and no external services**; intelligence is additive, never required.

---

## 1. Counter-Factual Competency — embeddings are blind to negation

**JD:** RAG pipelines, vector search, embedding-based retrieval; assess feasibility.

Pure semantic similarity + keyword matching cannot read grammatical negation. A
résumé stating *"abandoned FastAPI due to scaling issues"* and *"have not built
LangGraph workflows"* still surfaces the high-value tokens, so the
extract-then-embed blend in [`agents/resume_screener_agent.py`](backend/agents/resume_screener_agent.py)
counts them as matched skills.

- **Measured:** that résumé scores **72/100 → "hire"**, with `fastapi` and
  `langgraph` in `matched_skills`.
- **Decision:** rather than fudge the scoring, the failure is encoded as a
  **KNOWN LIMITATION** assertion — `test_KNOWN_LIMITATION_screener_does_not_discount_negative_context`
  in [`tests/test_agentic_behaviors.py`](backend/tests/test_agentic_behaviors.py).
  It asserts the *current* behavior, so adding negation reasoning later **breaks
  the test loudly** instead of silently changing scores.
- **Forward path (scoped, not yet built):** a schema-constrained Pydantic AI
  pass that grades each required skill `demonstrated | aspirational | negated |
  absent` before scoring — explicitly weighed against its added latency/token cost.

> Why it matters: shows how embeddings actually behave under the hood, and an
> eval-discipline-first stance over blind optimism.

## 2. "Availability Bias" in the RandomForest attrition model

**JD:** Harden POCs into production-grade systems with reliability/security.

The Retention agent is a **structured RandomForest over six job metrics**
(tenure, performance, absence, time-since-promotion, salary band, manager rating)
in [`models/attrition_model.py`](backend/models/attrition_model.py) — **no NLP /
sentiment over employee communications**, by deliberate design. Parsing employee
text trains models on hidden proxies for protected classes (age/region/gender) —
a legal/privacy liability the system refuses to take on.

- **Measured trade-off:** the model over-indexes a visible, high-variance one-off
  signal (absence spike → **0.29**) and under-indexes a severe slow-burn profile
  (4-year promotion freeze + declining manager rating → **0.12**). The "quiet
  quitting > loud complaint" intuition does **not** hold in feature-space.
- **Documented:** `test_KNOWN_LIMITATION_attrition_underweights_quiet_disengagement`,
  and surfaced in STATUS so an HR operator never misreads the signal.
- **Related fix:** the `needs_review` gate originally reused the RAG cosine floor
  (0.7) — which this model's output never reaches (~0.45 max) — so high-risk flags
  *never fired*. Replaced with a dedicated, calibrated `attrition_review_threshold`
  (0.35).

> Why it matters: data-science limitations + risk modelling + a protective stance
> on compliance and privacy.

## 3. Schema-constrained classification with Pydantic AI

**JD:** Multi-agent workflows (LangGraph/CrewAI); build backend APIs.

Triage originally string-scraped a free-form CrewAI answer (`if cat in out`) — a
line like *"this is not a POLICY issue"* trips the substring match. Refactored
([`agents/triage_agent.py`](backend/agents/triage_agent.py)) to a **Pydantic AI**
agent with a `Literal`-typed result:

```python
class TriageDecision(BaseModel):
    category: Literal["BENEFITS","POLICY","ONBOARDING","PERFORMANCE","COMPLIANCE","URGENT"]
    confidence: float = Field(ge=0, le=1)
    rationale: str
```

The model is **type-system-constrained** — it cannot return an arbitrary string
or a category outside the matrix; the validated `confidence` + `rationale` are
captured straight into the audit schema (and surfaced as a UI gauge). The
keyword classifier remains the zero-key fallback, so CI/demo are deterministic.

- **Honest scope:** the schema constraint makes an *invalid category structurally
  impossible*; it does not eliminate model-content error, and the live path isn't
  exercised in CI (no key). Verified: schema rejects a bad category, factory
  builds, triage falls back without a key — [`tests/test_llm_factory.py`](backend/tests/test_llm_factory.py).

> Why it matters: type-safe, predictable, production-ready code boundaries at the
> inference edge.

## 4. Protecting the ephemeral BYOK security posture (instead of adding a queue)

**JD:** Harden POCs with reliability/security/scalability; build backend APIs.

The product promise is **key ephemerality** — a visitor's API key is *never*
written to disk, DB, or logs. The standard scale answer (offload heavy parsing to
Celery/Redis) **breaks that promise**: a detached worker needs the key persisted
somewhere reachable, and request-bound `contextvars` don't cross process
boundaries.

Defended by **containment, not persistence**:
- Request-scoped key in a `contextvars.ContextVar`, bound by ASGI middleware and
  cleared in `finally` ([`core/runtime_key.py`](backend/core/runtime_key.py)).
- A unified **request-scoped provider factory** —
  `AnthropicModel(provider=AnthropicProvider(api_key=effective_api_key()))` —
  the only per-request key path in pydantic-ai 1.104 (verified by
  [`tests/test_pydantic_ai_probe.py`](backend/tests/test_pydantic_ai_probe.py));
  no network on construct, so the key stays on the single request frame
  ([`core/llm_factory.py`](backend/core/llm_factory.py)).
- **Cost/DoS guards inside the request frame:** classifier input capped at
  **4,000 chars**, validation self-heal capped at **`retries=1`** (not the default
  3–4, which appends the error trace and resubmits the full payload → token
  inflation), and a wall-clock timeout.

This explicitly **declines the distributed-queue shortcut** to keep the
zero-persistence guarantee — a deliberate threat-modelled trade-off, documented
as such. (Encrypting keys at rest for background workers was also evaluated and
**rejected** for the same reason.)

> Why it matters: reframes a "missing" feature as an intentional security defense;
> threat modelling over the easy shortcut.

## 5. False-positive urgency + dual-label override telemetry

**JD:** Logging, tracing, monitoring for production reliability.

The keyword triage path can't separate genuine urgency from emotional decoration:
a routine question wrapped in *"URGENT!! NEED ANSWER ASAP!!"* escalates to URGENT
(measured: calm→`POLICY`, panicked→`URGENT`). For HR this *errs toward safety* —
but it inflates the escalation rate.

Handled without corrupting the metric loop:
- A human can **Re-route** a misrouted case to a real queue
  (`PATCH /cases/{id}/reroute`, closed-enum → 422 on a bad queue). This writes an
  **immutable `triage_override` audit row** (`from_category → to_queue`, actor,
  reason) — so **Triage Override Rate** is a pure `COUNT … GROUP BY` over the
  audit log, never an agent-stored number.
- **Dual-label state:** the original *machine* classification is **never
  overwritten**; the UI shows the AI category badge **and** a "Manual → <queue>"
  tag (drawer + table row) with a "kept for drift tracking" note.
- Capture is append-only and human-facing only: the retention-feedback ledger
  ([`api/routes/feedback.py`](backend/api/routes/feedback.py)) records
  accept/reject decisions but is **deliberately not** fed back to steer the
  model — that would optimise a confounded proxy and amplify bias.

> Why it matters: the link between frontend telemetry, backend audit, and the
> day-to-day reality of human-in-the-loop systems.

---

## The RAG / retrieval pipeline (semantics · chunks · vector DB · pipelines)

The Policy Q&A path is a full retrieval pipeline with graceful degradation:

- **One datastore, backend-selected** — [`services/rag.py`](backend/services/rag.py)
  `active_backend()` picks **pgvector** (Postgres, HNSW cosine,
  [`services/pgvector_store.py`](backend/services/pgvector_store.py)) → Qdrant if
  pinned → **zero-dependency SQLite cosine**
  ([`services/local_vector_store.py`](backend/services/local_vector_store.py)) by
  default. Ingest / retrieve / delete all route through the same selector, so
  *what gets embedded is what gets searched.*
- **Structure-aware chunking** — [`pipelines/ingestion.py`](backend/pipelines/ingestion.py)
  splits on paragraph boundaries, **packs paragraphs** up to `chunk_size` words
  (carrying `overlap` for continuity), and **word-windows** any oversized
  paragraph — never one giant block that dilutes retrieval or overflows a prompt.
- **Hybrid recall** — `retrieve()` widens the candidate net then applies a
  **structural title-match boost** so a short, keyword-style query ("equal
  opportunity") surfaces the right document even when raw cosine is low — *without*
  lowering the grounding floor used for synthesis.
- **Context-or-null synthesis** — [`pipelines/rag_pipeline.py`](backend/pipelines/rag_pipeline.py)
  answers **only** from retrieved chunks at `temperature=0`; below `GROUNDING_FLOOR`
  it returns the verbatim excerpt, and with no relevant chunk it **refuses**
  ("…don't cover that") instead of fabricating. Every answer carries a structured
  `mode` (`llm` / `grounded_excerpt` / `no_context` / `llm_error`) so the UI can't
  let a deterministic excerpt pose as LLM reasoning.
- **Agentic, bounded self-correction** — [`agents/policy_resolver.py`](backend/agents/policy_resolver.py)
  is an in-process LangGraph loop `retrieve → grade → reformulate → retry`, hard-
  capped (`MAX_ATTEMPTS`) and timeout-wrapped, that degrades to a single
  deterministic pass on failure. **In-process, not a distributed event bus** — a
  deliberate "right-sized" choice that keeps the laptop/zero-service guarantee.
- **Negative-space guarantee (verified):** "policy on charging personal electric
  unicycles in the server room" → `no_context`, conf 0.0, no fabricated rule
  (`test_negative_space_refuses_instead_of_fabricating`).

## Audit log as the single source of truth

Every agent action → one immutable row in [`core/memory.py`](backend/core/memory.py).
`/metrics` and Analytics are **pure queries** (`COUNT … GROUP BY`): actions-by-agent,
case-status mix, auto-resolution / escalation / **triage-override** rates,
resume-screens, policy-queries. No agent computes a metric. Schema upgrades use an
idempotent additive `_backfill_columns` (`ALTER TABLE … ADD COLUMN`, nullable-only,
SQLite + Postgres) instead of shipping a migration framework into a zero-dep demo.

## Verification posture

- **169 passed, 3 skipped** (optional pgvector integration). CI: ruff + black + eslint.
- **Behavioral evals** ([`tests/test_agentic_behaviors.py`](backend/tests/test_agentic_behaviors.py))
  grade *behavior*, not schema: 2 guarantees (negative-space refusal,
  register-invariant compliance escalation) + 4 **documented limitations** asserted
  as current behavior so a future fix breaks loudly.
- **Framework probe** ([`tests/test_pydantic_ai_probe.py`](backend/tests/test_pydantic_ai_probe.py))
  pins pydantic-ai 1.104's key/retry mechanics and caught a silent `chat_agent`
  regression (the old `AnthropicModel(api_key=…)` was rejected by 1.104, degrading
  chat to fallback even with a key — now fixed via the shared factory).

## Honest open items

- **Model EOL:** the default `claude-sonnet-4-20250514` reaches EOL 2026-06-15 —
  documented in `.env(.production).example`; left unchanged (a newer model than the
  alternatives, and no unverified id is shipped into core).
- **Live LLM path not CI-verified:** schema-constraint, gating, BYOK isolation, and
  fallback are all tested; an actual keyed round-trip is the one thing the suite
  can't cover without a key.
- **Screener negation** and **attrition feature re-weighting** are tracked
  limitations, not silent debt.
