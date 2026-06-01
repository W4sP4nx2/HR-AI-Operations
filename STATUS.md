# Project Status — HR AI Command Center

_Snapshot: 2026-05-31. Stage: **demo-ready core**. Runs with zero secrets, zero external services._

## TL;DR

A safe, audited AI layer for HR. Five agents + a chat assistant, every action
written to an immutable audit log, all metrics **derived from that log** (never
calculated by agents). Runs end-to-end on a laptop with no API key and no
Postgres/Qdrant — intelligence is additive, not required.

## What works today (verified)

| Capability | State | Notes |
|---|---|---|
| **Policy Q&A (RAG)** | ✅ end-to-end | Zero-dependency cosine retrieval on SQLite **and verified on Postgres+pgvector** (HNSW cosine); synonym-aware lexical embedder; cited answers with clickable source chips in chat. |
| **Triage** | ✅ | Keyword/LLM classify → URGENT escalates to a human, POLICY auto-resolves, all audited. Gateway that creates cases. |
| **Resume Screener** | ✅ + UI | Dedicated panel: paste text **or drag-drop a PDF** (client pre-flight: <2 MB + `%PDF-` magic-byte check, then an engineering status-log spinner) → fit score, advance/don't-advance, matched/missing skills. Demographics blinded before scoring. **Layout-aware PDF extraction** (pypdf layout mode) keeps two-column resumes from scrambling. |
| **Attrition Predictor** | ✅ + UI | Dedicated panel (manager+): six job-signal sliders → advisory risk %, top-risk-factor chart, plain-English explanation. No protected attributes used; advisory-only + human-review framing. |
| **Onboarding** | ✅ backend | LangGraph checkpoint pauses for human approval. |
| **Live metrics** | ✅ | `GET /metrics` queries the audit log + cases (`COUNT … GROUP BY`); Analytics renders it; KPIs refresh every 10s. |
| **Auth + RBAC** | ✅ | viewer→analyst→manager→admin. Demo "View as" role switcher (mints real per-role JWT; disabled when `AUTH_ENFORCE=true`). |
| **Demo UX** | ✅ | **Persona Launchpad** landing (pick a role to enter — no login form), BYOK row surfaced at onboarding, sidebar "View as" for live persona swaps, demo banner + real "N active cases" counter. |

## The audit log is the single source of truth

Every agent action → one immutable audit row. Nothing computes a metric in an
agent; `/metrics` and the Analytics panel are **pure queries**:

- `agent_actions_total`, `actions_by_agent` ← audit `COUNT … GROUP BY agent`
- `active_cases` / `resolved` / `escalations` ← case status counts
- `auto_resolution_rate`, `escalation_rate` ← ratios over those counts
- `resume_screens`, `policy_queries`, `injection_blocks` ← audit by `action_type`

Compliance exports the same log; cases reference it. No interconnection needed.

## Cost & security controls

Defaults are safe; `backend/.env.production.example` is the lock-down overlay
template (copy to `.env.production`, which is git-ignored — only `*.example` env
files are ever committed, so no real key/secret can leak):

- **Cost:** `MOCK_LLM` / `DEMO_MODE` (zero LLM spend), `SEMANTIC_CACHE_TTL=3600`
  (RAG answers cached 1h, now TTL-aware), `POLICY_CACHE_SIZE`.
- **Abuse/DoS:** `RATE_LIMIT_REQUESTS` per-IP rolling window (off by default, on in prod),
  `MAX_UPLOAD_SIZE_MB=10` enforced on every PDF upload.
- **Security:** `AUTH_ENFORCE=true`, `AUTH_OPEN_REGISTRATION=false`, real `JWT_SECRET`,
  `REDACT_PII=true` (PII masked before any write), conservative security headers.

## Tests

`125 passed, 3 skipped` (skips are the optional pgvector integration tests, run when
`RAG_TEST_DSN` is set). Suites: `test_metrics` (triage routing + audit aggregation),
`test_mission_alignment` (one per MISSION principle), `test_eval_goldens` (eval harness,
below), `test_input_shield_byok` (input firewall, ephemeral key incl. "never hits the
audit log", provider verify, demo-token-rejected-under-enforce), and
`test_grounding_guardrails` (context-or-null refusal, domain-bound system prompt,
jailbreak detection). All on the isolated conftest DB. CI runs ruff + black + eslint.

### Evaluation harness (regression guard)

`tests/test_eval_goldens.py` is a small **balanced golden set** built from real
reported failures (`"sdsd"`, `"urgent outage"`) with **code-based graders** (category +
escalation), grading the agent's *output* not its path:
- per-case objective pass/fail (parametrized) — the gate,
- aggregate **pass@1** rate over the set asserted ≥ 90%,
- a **pass^k** consistency check (a clear emergency must classify URGENT every time).

Grows by converting each new user-reported failure into a `Golden` row.

## Component & agent-mapping model

Fleet is a **launcher + status board**, not a replacement for panels: it shows
health/last-run/run-counts and triggers agents (text/PDF/URL). Every agent action
lands in the **Cases ledger + Audit**, and the panels are filtered views of that:

| Agent | Creates case | Primary panel |
|---|---|---|
| Triage | yes (URGENT/POLICY/…) | Cases |
| Resume Screener | yes (`SCREENING`, resolved) | Screener |
| Attrition | yes (`RETENTION`, open if high-risk) | Attrition |
| Onboarding | approval task | Approvals |
| Policy Q&A | no (self-service; Audit only — avoids flooding Cases) | Chat |

## Onboarding flow (no fake login gate)

Demo mode lands on a **persona Launchpad** (`auth/Launchpad.tsx`): pick Employee /
HR Analyst / HR Manager / Admin → it mints a real per-role demo JWT and drops you
straight in. No email/password, no "continue as guest" friction. The **BYOK row**
sits on the same card so evaluators see the zero-retention "use your own key"
sandbox before they enter. Inside, the sidebar **"View as"** switcher swaps personas
in real time; the redundant sidebar "Sign in" button is gone. Enforced (production)
deployments still get the real email/password `LoginScreen` — the Launchpad replaces
the *demo* gate, not real auth.

## Grounding & domain guardrails (anti-hallucination, anti-jailbreak)

For credibility on a public, BYOK-enabled deployment the assistant is bound tightly:

- **Context-or-null grounding.** The RAG synthesis prompt forbids training/general
  knowledge and must answer *only* from retrieved policy chunks; with no relevant
  chunk it replies "The provided policy documents don't cover that" rather than
  inventing one. The LLM is only invoked when a chunk clears a `GROUNDING_FLOOR`
  cosine score (else the verbatim excerpt is shown), and runs at `temperature=0`.
- **Domain-bound system prompt.** The chat agent's system instruction scopes it to
  HR only (declines coding/general queries), refuses attempts to change its role,
  reveal the prompt, or grant approvals, and never uses parametric knowledge for
  policy answers. Layered behind the deterministic `detect_prompt_injection` guard.
- **Surfaced as a feature** — the Launchpad shows a "Strict guardrails active" badge
  (grounded answers · jailbreak-resistant · PII redacted · fully audited).

> Honest limit: cross-cutting questions can still retrieve partial context (vector
> recall gap). The model is instructed to refuse when context is insufficient rather
> than fabricate a link, but retrieval recall itself is best-effort lexical/HNSW.

## Hosting safety (zero committed secrets)

No git repo exists yet, so nothing has leaked. `.gitignore` blocks `*.db`, `.venv`,
`node_modules`, `.next`, all `.env*` **except** `*.example` templates, and the
`.pytest_cache`/`.ruff_cache` artifacts. The production overlay ships as
`.env.production.example` (placeholders only); a real `.env.production` is ignored.
All config (keys, secrets, DB URL) is read from the environment via
`pydantic-settings` — nothing hardcoded. A test (`test_security`) greps the frontend
for real key patterns.

## Least privilege (RBAC)

Sensitive read endpoints are role-gated and **verified at the HTTP layer** under
`AUTH_ENFORCE=true`: an Employee (viewer) JWT gets **403** on `/metrics` (analyst+),
`/audit`, `/audit/export`, `/cases/pending`, `/cases/approvals/history` (manager+);
a manager/admin gets 200; no token → 401. In demo mode (`AUTH_ENFORCE=false`) these
are advisory so the zero-login demo stays fully usable.

**Tiered Fleet (read vs. write) + per-agent trigger authority.** The Fleet panel is
read for anyone who can see it (status, last action, run counts — Analysts keep
operational awareness) but **agent control (triggering) is manager+** in the UI.
Backed by real enforcement: the trigger endpoints (`/agents/{name}/trigger[/upload]`)
gate on **each agent's declared `min_role`** (`contracts.AGENT_SPECS`: Policy Q&A
viewer, Triage/Resume Screener analyst, Onboarding/Attrition manager). Under
`AUTH_ENFORCE` an Analyst can run the Screener but gets **403** on the Attrition
agent — verified at the HTTP layer; so non-admin roles can never drive manager-only
orchestration, even via the raw API.

**Input-matched Fleet cards.** A card's control matches the agent's real input
contract, not a one-size-fits-all chat box: free-text agents (Triage / Resume
Screener / Onboarding) keep the text+PDF Trigger row; **Attrition** (tabular
scikit-learn) shows **"Open Attrition panel →"** (jumps to its 6-slider panel); and
**Policy Q&A** shows **"Open Conversation →"** which switches to the Chat tab and
seeds the input with a template prompt (one-shot, cleared on consume).

**Demo tokens can't leak into production.** `/auth/demo/switch` mints `provider="demo"`
personas only in advisory mode, and `get_current_user` **rejects any `provider="demo"`
token with 401 when `AUTH_ENFORCE=true`** — so a mock persona can never authenticate
against a hardened instance, even if the row/token still exists (regression-tested).
Cross-instance spoofing is independently blocked by the per-deployment `JWT_SECRET`.

## Approval history (from the audit log)

Approve/reject decisions are written as immutable `human_approved` / `human_rejected`
audit rows (with `decided_by_id`, `role`, `reason`). The Approvals panel shows a
**Decision history** table that simply *queries* those rows — no separate table to
keep in sync. This is the audit-log-as-source-of-truth model applied to approvals.

## Short-query retrieval (intent expansion + hybrid title boost)

A shorthand query like "equal opportunity" used to miss a loaded
`equal_opportunity.pdf` and fall to the generic helper. Root cause + fix:
- **Chat fallback router** gated the policy search behind a fixed keyword list, so
  fragments never searched. It now **defaults any unrecognised query to a policy
  search** (intent expansion), with a relevance floor so off-topic input ("hello")
  still gets the capability helper — not a stray policy.
- **Retrieval** widens the candidate net and applies a **structural title-match
  boost**: when a query mostly names a policy by title/filename, that document is
  lifted to a confident score (≈0.95) even if its raw cosine is low — so short
  queries clear the grounding floor without weakening it. Near-zero citations are
  dropped so only relevant sources are shown. (`services/rag.py`, `agents/chat_agent.py`;
  regression tests in `test_short_query_retrieval.py`.)

## Polish pass (reviewer-flagged consistency)

- **Screener math now mutually consistent.** The fit gauge, coverage % and skill
  counts are derived from the same numbers with **half-up rounding** (matches JS
  `Math.round`, no banker's-rounding drift like 62.5%→62%). The reasoning states the
  gauge is a *blend* of semantic similarity and keyword coverage, so 0.66 vs 65 isn't
  mistaken for a mismatch.
- **`prompt()` crash removed.** The Approvals reject flow used `window.prompt()`
  (blocked in sandboxed iframes). Replaced with an **inline reason input** (Confirm/
  Cancel) — verified the full reject lands in the audit-backed history.
- **Structure-aware chunking.** `chunk_text` splits on paragraph boundaries and packs
  to `chunk_size` (word-windowing oversized paragraphs) instead of a blind fixed slice
  — small docs stay one chunk, a long handbook becomes many semantic chunks (never one
  giant block). ("1 chunk" for the tiny seed files is correct: they're < the size cap.)
- **Audit cells truncate reliably** (max-width div + ellipsis + full value on hover),
  so raw JSON payloads no longer blow out the table.

## Defensive local engineering (case study: first-class AI recommendations)

A worked example of choosing the boring, correct design over the impressive-looking
one. The ask: *"auto-attach a policy recommendation to a case before the analyst
sees it."* The tempting answer — a FastAPI `BackgroundTasks` worker that fills the
case in asynchronously — was **rejected** (see `AUTO_RESOLUTION_REVIEW.md`) because
it manufactures three problems we don't have:

- **UI race:** the WebSocket pushes `new_case` instantly; a background fill arrives
  seconds later, so an analyst opening the case in that window sees an empty dossier
  that then pops in — a layout-shift flash-bang.
- **BYOK leak:** background tasks run *after* the response, when the request-scoped
  key contextvar is already reset — so the RAG call would silently fall back to the
  **server key**, violating own-your-data.
- **Swallowed errors:** the proposed task `print`s failures — no audit row, invisible
  in prod.

**The chosen design — synchronous column promotion.** `TriageAgent.run` *already*
computes the RAG answer for a POLICY case (the auto-resolve path). We persist that
existing result as two **first-class, nullable** case columns — `ai_recommendation`
(Text) and `ai_confidence` (Float) — inside the same `create_case` call. The
recommendation is therefore present the instant the case exists: atomic, no race, no
second DB session, no BYOK leak, advisory-only (a human still closes the loop).

**The migration that makes it laptop-safe — `_backfill_columns`.** SQLAlchemy
`metadata.create_all` creates *missing tables* but never **ALTERs an existing one**, so
adding a column to a model leaves older local DBs (and the committed demo `.db`) one
column short — the next insert would 500. Rather than ship Alembic for a zero-dep demo,
`_ensure_schema` runs an idempotent additive backfill: it inspects each live table and
`ALTER TABLE … ADD COLUMN`s any model column that's absent. **Nullable-only**, so
existing rows stay valid and no data is moved or dropped; **dialect-agnostic**, so the
same path upgrades SQLite *and* Postgres; **idempotent**, so it's a no-op once aligned.
Verified against a synthetic pre-migration DB: columns added, legacy rows preserved as
`NULL`, new writes round-trip.

**The product payoff — the Case Drawer is now a metadata inspector, not a text box.**
A magenta **AI recommendation** card renders the answer with a colour-coded
**confidence gauge** and a *Needs review* badge below the 0.7 floor; below it the
**Agent execution trace** is an expandable accordion over the case's immutable audit
rows (agent · action, status dot, timestamp → structured *Category / Why / Recommended
/ Vector recall* on expand). Every value shown is real audit/RAG data — no fabricated
"Input Shield ✓" theatre.

## Agentic policy resolution (in-process, bounded — not an event bus)

The POLICY auto-resolve path is now a **self-correcting agent loop**, not a single
RAG call — `agents/policy_resolver.py` runs a LangGraph state machine:

```
retrieve ─grade─▶ accept   (confidence ≥ floor, or attempts exhausted)
    ▲              │
    └─ reformulate ◀ retry  (low confidence → widen the query, try again)
```

This deliberately answers the "automation vs. agency" question **without** a
distributed event bus / message broker, because that would break the headline
"runs on a laptop, zero external services" guarantee. Instead the agency is:

- **In-process & off the event loop** — invoked via `asyncio.to_thread`, so it
  adds zero infrastructure.
- **Hard-bounded** — `MAX_ATTEMPTS` caps the loop, a wall-clock `TIMEOUT_S` wraps
  it, and any failure degrades to a single deterministic pass. A volatile loop
  can't block the event loop or spin forever — the exact failure mode that would
  otherwise justify decoupling.
- **Routing-contract-preserving** — POLICY still auto-resolves (the metrics tests
  pin `status == "resolved"`). The loop improves the *answer*; it does not hijack
  resolved/escalated routing. (Escalating low-confidence POLICY to a human is a
  separate product decision + test change, not smuggled in here.)
- **Audited at the boundary, not per-node** — the case's audit row gains a compact
  `retrieval_attempts` count (decision context), while the full node-by-node trace
  rides in the returned dossier and renders in the Case Drawer's **Agent execution
  trace** accordion. The immutable compliance ledger stays signal, not node spam.
- **Gracefully degrading** — if LangGraph isn't installed, the identical loop runs
  as plain Python (mirrors `OnboardingAgent`).

Covered by `tests/test_policy_resolver.py` (6 cases: accept-first-pass, bounded
retry, retry-recovers, reformulation, no-LangGraph fallback, timeout→single-pass).

## Retention feedback telemetry — capture, NOT a reward loop (honest by design)

Managers can now accept/reject each retention suggestion (Attrition panel). Those
decisions are captured in an **append-only `agent_feedback` ledger** + an immutable
audit row, and surfaced as human-facing aggregates (`GET /feedback/stats`:
per-driver accepted/rejected/edited + exact acceptance_rate).

What this deliberately is **not**: a closed reward loop. We rejected "record a
reward and dynamically re-prompt future predictions" because in a regulated HR
setting that (a) optimises a confounded proxy — manager click ≠ retention outcome,
(b) amplifies bias into adverse-action-adjacent output (EEOC disparate-impact),
(c) erodes the grounding/determinism (`temperature=0`, context-or-null) and
auditability the system is built on. So: **the agent's recommendations stay
deterministic and grounded; a human reads the "what's working" signal and
decides.** The ledger is immutable by construction (no update/delete path);
`manager_notes` are PII-redacted before insert.

- Endpoints: `POST /feedback` (manager+, `action_taken` is a closed enum → 422 on
  anything else, before the data layer) · `GET /feedback/stats` (analyst+).
- Covered by `tests/test_feedback.py` (append-only, PII-at-rest, exact aggregation,
  422 validation, persist round-trip).

## Onboarding checkpointer (Phase 2) — investigated and DECLINED (minimalist win)

Before adding `langgraph-checkpoint-sqlite`, we traced the actual resume path.
Verdict: **the dependency is not needed.**

- `OnboardingAgent.resume_after_approval` runs **only the post-checkpoint steps**
  (`send_welcome_email`, `notify_manager`) from the **persisted snapshot** in the
  `agent_tasks` row. It does **not** re-invoke the graph and does **not** re-run
  `validate` / `create_accounts` / `assign_training` — so account provisioning is
  **never duplicated on resume**. That is exactly the "targeted execution over the
  task row" pattern a checkpointer would provide, already achieved with a plain
  state snapshot and zero new dependencies.

The investigation did surface (and we fixed) one real gap, without any dependency:

- **Idempotency hardening (atomic compare-and-set).** The old approve/reject path
  was TOCTOU-racy ("list pending, then update"): two *concurrent* approvals could
  both pass the check and both resume. `resolve_agent_task` is now a
  compare-and-set — `UPDATE … WHERE status = 'awaiting_approval'`, returning the
  row only if it transitioned (`rowcount == 1`) and `None` otherwise. The route
  resumes **only** when it wins the CAS, so a double-click or two parallel
  requests can never re-run the workflow's side-effects. Covered by
  `tests/test_cases.py::test_resolve_agent_task_is_atomic_compare_and_set`.

## Attrition × Policy — grounded retention composition (agent composition)

When the Attrition Predictor flags a **high-risk** employee, it now **composes**
with the Policy Q&A engine (`agents/retention_resolver.py`): the top risk
*drivers* are mapped to the relevant HR policy area and looked up via RAG, so a
manager gets **grounded, cited retention options** ("driver: time-since-promotion
→ here's the career-development policy") instead of a bare risk number.

- **Deliberately not a LangGraph state machine** — this is a bounded deterministic
  fan-out (top drivers → policy lookups), not stateful branching. A state graph
  would be ceremony; the right-sized tool is a bounded async composition.
- **Bounded / advisory / non-blocking** — only the top `MAX_FACTORS` drivers,
  each RAG call timeout-wrapped; any failure yields an empty list and never blocks
  or alters the prediction. Audited at the boundary (suggestion count only).
- **Honest grounding** — suggestions are deterministic (driver→action); the policy
  text is real RAG, and a `no_context` result says "no specific policy located"
  rather than inventing one.

**Pre-existing bug fixed along the way:** the attrition `needs_review` gate reused
the RAG cosine floor (`confidence_threshold = 0.7`), but this RandomForest's output
tops out ≈0.45 — so the high-risk flag (and its "open" RETENTION case) **never
fired**. Added a dedicated `attrition_review_threshold` (default 0.35) calibrated
to the model's own range (healthy ≈0.05 … severe ≈0.45). Covered by
`tests/test_retention_resolver.py` (5 cases).

## Resume Screener — two-node timeline cross-validation (fairness-bounded)

The screener now runs a second **in-process LangGraph pipeline**
(`agents/resume_resolver.py`) alongside scoring: `extract → cross_validate`.
It parses explicit employment date ranges and emits **advisory data-integrity
flags** — a range that ends before it begins, a future-dated entry, or one role
wholly inside another (possible concurrency to confirm).

Deliberate, fairness-aware scope (documented, not hidden):

- It **never flags employment gaps** — gap-penalising adversely impacts
  caregiving/medical leave (a protected-class proxy; cf. "blinding ≠ bias-proof").
- It makes **no "inflated qualifications" judgment** — no deterministic check can
  do that honestly. Flags are advisory; they **never change the score**, only set
  `needs_review` for a human.
- The timeline pass runs on the **raw** résumé (blinding scrubs years as an
  age-proxy guard, which the check needs), but **only the flag count** is
  persisted to the audit/case — raw years never enter storage, only the live
  recruiter view. Scoring stays fully blinded.

Surfaced as a "Timeline checks" panel in the Screener (with the gap-exclusion
stated in the UI). Covered by `tests/test_resume_resolver.py` (7 cases incl. an
explicit "gap must NOT be flagged" fairness test).

## Recently fixed

- **Onboarding Phase 2 declined** (resume already replays no prior nodes) +
  **atomic compare-and-set** approval guard closing a concurrent double-approve
  race — see above.
- **Attrition × Policy retention composition** (bounded agent composition; grounded,
  cited, advisory) + fixed the never-firing `needs_review` gate via a dedicated,
  calibrated `attrition_review_threshold` — see above.
- **Resume Screener timeline cross-validation** (two-node LangGraph; advisory,
  fairness-bounded, score-preserving) — see above.
- **Reasoning-mode transparency (anti "mock-leak").** RAG now returns a structured
  `mode` (`llm` / `grounded_excerpt` / `no_context` / `llm_error`) alongside the
  answer; it's persisted on the case (`ai_mode`, additively backfilled) and shown
  as a chip on the recommendation card — **neutral grey for every deterministic /
  fallback mode**, coloured only for true LLM synthesis. A local excerpt can no
  longer be mistaken for elite reasoning. (`_synthesize_answer` kept as a
  string-returning wrapper so the grounding tests are untouched.)
- **Transactional re-index.** `scripts/reindex.py` now **ingests the new vectors
  first** (deterministic chunk ids upsert in place, keeping the doc searchable
  throughout) and only prunes a stale tail *after* a confirmed-successful upsert —
  so an ingest failure can never leave a doc with an empty index.
- **In-process agentic POLICY loop** (retrieve→grade→reformulate, bounded +
  timeout-guarded; trace surfaced in the execution-trace accordion) — see above.
- **First-class AI recommendation on cases** (synchronous column promotion +
  idempotent `_backfill_columns` migration + Case Drawer execution-trace accordion) —
  see the case study above.
- **Self-heal no longer wipes silently.** The destructive `policy_chunks` recreate is
  gated behind `ALLOW_DESTRUCTIVE_REINDEX` (default off): on a dimension mismatch the
  store now logs loudly and **degrades** instead of dropping live embeddings.
  `scripts/reindex.py` is the explicit, **vector-only** recovery tool (re-embeds from
  retained `source_text`; never touches `cases` / `audit` / `users`).
- **Policy ingestion can't starve the audit log.** PDF parse + chunking run via
  `asyncio.to_thread`, so a large upload no longer pins the event loop while concurrent
  chats write their audit rows (complements the existing SQLite WAL + busy-timeout).
- "0 active" counter → real **active-cases** count from the audit-backed metrics.
- **Duplicate seed data** → seeding is idempotent (stable case count across re-runs).
- Analytics **fabricated numbers** (`6m 12s`, `cases*0.4+12`, fake donut) → replaced
  with live audit-derived metrics.
- Resume screener skill extraction (was leaking punctuation/filler as "skills").
- **Test/demo DB bleed** → `tests/conftest.py` points the suite at a throwaway temp
  DB, so `pytest` no longer mutates the demo's seeded state (the old "reseed after
  pytest" caveat is gone).
- **Raw-text crash on structured agents** (e.g. typing into Attrition from Fleet) →
  now returns a graceful "needs structured signals — use the Attrition panel" instead
  of a red runtime error.
- **Empty escalations & cryptic audit** → triage writes a **decision dossier**
  (rationale + recommended action) to the audit log; the case drawer renders it as
  readable *Why / Recommended* lines, not raw JSON. An escalation now carries context.

## Known guardrails & limitations (be honest, not hidden)

- **Self-heal is destructive — now guarded.** On a vector-dimension mismatch the
  `policy_chunks` drop+recreate only fires when `ALLOW_DESTRUCTIVE_REINDEX` is set
  (default off); otherwise the store logs loudly and degrades. A production model swap
  should run `scripts/reindex.py` (vector-only, re-embeds from retained source text)
  rather than rely on lazy recreation. Residual sharp edge: with the flag *on*, a swap
  mid-session still empties retrieval until re-ingest completes.
- **Blinding ≠ bias-proof.** The Resume Screener strips names/protected attributes,
  but lexical/LLM scoring can still infer proxies (school, clubs, dates). True
  compliance needs deterministic proxy scrubbing before any model sees the text.
- **Keyword triage is bypassable.** The deterministic gateway is robust for the demo
  but not adversarial-injection-proof; prompt-injection guardrails are basic.

## Run it

```bash
# Backend (zero secrets)
cd backend && .venv/bin/python -m scripts.seed_data        # idempotent
.venv/bin/uvicorn api.main:app --port 8000 --reload
# Frontend
cd ../frontend && npm run dev                              # http://localhost:3000
```

> Tests are isolated (`tests/conftest.py` uses a throwaway temp DB), so running
> `pytest` never touches your demo's seeded data.

All five agents are now reachable in the UI (Policy Q&A + Triage via Chat,
Resume Screener, Attrition, Onboarding via Approvals/Fleet).

## Vector backend (one datastore, graceful degradation)

`services/rag.active_backend()` is the single selector for ingest/retrieve/delete:

- **SQLite (default, zero deps)** → in-process cosine over `policy_vectors`. Powers the demo.
- **Postgres → pgvector** (`services/pgvector_store.py`) → `policy_chunks` with an HNSW
  cosine index; `embedding <=> query` retrieval. **Verified end-to-end** against
  `pgvector/pgvector:pg16`: integration tests pass, seed embeds into Postgres, and
  the live dashboard's cited Policy Q&A retrieves through pgvector.
- `ensure_schema` **self-heals a vector-dimension mismatch** (drops/recreates the
  table if the embedding model size changed) instead of failing on insert.

Run on Postgres:
```bash
docker compose up -d db        # pgvector/pgvector:pg16, healthchecked
DATABASE_URL=postgresql://hr:hr_dev_password@localhost:5432/hrdb \
  python -m scripts.seed_data && uvicorn api.main:app --port 8000
# integration tests: RAG_TEST_DSN=postgresql://hr:hr_dev_password@localhost:5432/hrdb pytest tests/test_rag.py
```

## Input shield (pre-flight firewall)

`services/input_shield.py` sits in front of `dispatch_agent`: it **sanitises** free
text (strip control chars, collapse whitespace, cap length) and **validates**
structured agents against their contract. Raw text aimed at a maths module (the
Attrition agent) is now rejected *here* with a clear `unavailable` + guidance
("use the Attrition panel"), instead of crashing downstream. Tested incl. the real
`"sdsd"` / "is John about to quit?" failures.

## BYOK — bring your own key (ephemeral, never persisted)

`core/runtime_key.py` + a middleware in `api/main.py`: a visitor can send their own
key in `X-Client-LLM-Key`. It's held in a **request-scoped contextvar**, used only
for that request, and **cleared in `finally` — never written to the DB, audit log,
or any file** (regression-tested: the key never appears in the audit log). LLM
call-sites read `effective_api_key()`; `llm_active()` is the single gate, and a
visitor key **overrides `MOCK_LLM`/`DEMO_MODE`** (they opted into the spend). On
failure it falls back to the deterministic baseline. Wired into RAG synthesis,
attrition explanation, and the chat agent (per-request agent built for the BYOK
key); responses carry `X-BYOK: 0|1`. Chat messages are cleansed/capped pre-flight
as a lightweight token-footprint/loop guard.

**Provider-verified pulse.** `GET /byok/verify` authenticates the key against the
provider (`GET /v1/models` — no token spend) and returns `verified | rejected |
malformed | missing | unverifiable`. The top-bar control (`components/ByokControl.tsx`)
hits it on save: **green "verified"** only when the provider accepts it, **amber
"unverified"** if the provider is unreachable (offline demo — key kept, can still
try), and a **rejected** key is cleared with an error *before any agent runs*. Key
lives in `sessionStorage` only, attached as `X-Client-LLM-Key` via `authHeaders`;
"basic mode" hides while a key is active. Verified end-to-end (a fake key is really
rejected by Anthropic; missing/malformed handled without a network call).

> Caveats: the CrewAI triage classifier still reads the server env key (BYOK not
> wired there); the token cap is a char heuristic — swap in `tiktoken` for exact
> budgets.

## Resume ingestion — built vs. the v2 architecture

**Done now (scoped, zero new deps):** layout-aware PDF extraction (`pypdf`
`extraction_mode="layout"`, per-page fallback) so two-column resumes don't scramble
(Pain Point #1); a drag-drop upload UI with client pre-flight (size + magic bytes)
and a status-log spinner, wired to `/agents/resume_screener_agent/trigger/upload`.

**Deliberately deferred (the full diagram is the v2 roadmap):** the Screener is a
stateless JD+resume→score tool — it scores the *whole* resume, so it doesn't suffer
the 500-token mid-job-block split (Pain Point #2), and it has **no candidate
database**, so hybrid vector+relational filtering ("score >85% AND ≥3 yrs exp",
Pain Point #3) is a new subsystem, not a tweak. Building it means: structural
parser (PyMuPDF/Marker — heavy dep) → metadata-to-relational-row + job-block-bounded
chunking → embeddings → hybrid index. Tracked, not half-built.

## Next

Core is complete. Deferred to v2:
- **Candidate store + hybrid search** (the resume-ingestion diagram: structural
  parse → relational metadata + job-block chunks → vector+SQL hybrid filtering).
- **Async polling job runner** — only needed once real LLM calls risk Render's 30s
  gateway timeout; the deterministic demo agents run in <1s, so this is deploy
  hardening, not demo-blocking. (POST → task id, GET polls status; background runner.)
- Google OAuth, full test-suite trim, multi-stage Docker, advanced compliance pack
  (deterministic PII proxy scrubbing, prompt-injection hardening), `tiktoken` exact
  token budgets, BYOK wiring into the CrewAI triage path.

## Mission alignment

Human-in-the-loop (URGENT always escalates; onboarding pauses for approval),
audit-everything (the log *is* the metrics source), graceful degradation (works
with no key/DB), least privilege (RBAC + role switcher), own-your-data
(SQLite↔Postgres, PII redaction, export). On track.
