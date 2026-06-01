# Auto-Resolution & Operational Tooling — Engineering Review

**Date:** 2026-06-01
**Scope:** Proposal to (1) auto-attach an AI policy recommendation to cases via a
background task, and (2) add `scripts/reindex.py` + rewrite `scripts/seed_data.py`.

**Verdict:** Don't implement the proposal as written. The auto-resolution feature
**already exists and is better than the proposed version**, and both utility
scripts would destroy core invariants this project is built on. A small,
correct subset is worth doing — described at the end.

---

## 1. Auto-resolution already exists — and synchronously, by design

The proposal's goal — "attach a suggested resolution to the case before the
Analyst views the queue" — is **already implemented** in
[`agents/triage_agent.py`](backend/agents/triage_agent.py) (`TriageAgent.run`):

```python
elif category == "POLICY":
    # Auto-resolve with RAG.
    resolution = await asyncio.to_thread(rag_pipeline.query, ticket_text)
    status = "resolved"
    assigned = "policy_qa_agent"
...
if category == "POLICY" and resolution:
    dossier["confidence"] = resolution.get("confidence_score")
    dossier["sources"] = resolution.get("source_documents", [])[:3]
```

The RAG lookup runs (offloaded to a worker thread so it doesn't block the loop),
and the answer + confidence + cited sources are attached to the **decision
dossier** and written to the audit log *before* `run()` returns. The analyst
sees the recommendation the moment the case appears. The CPU/IO-bound work is
already off the event loop via `asyncio.to_thread`.

### Why moving it to `BackgroundTasks` is a regression, not an upgrade

| Issue | Current (synchronous) | Proposed (`BackgroundTasks`) |
|---|---|---|
| **Race condition** | Recommendation is present when the case is created. | Case is returned *without* the recommendation; the task populates it later. An analyst who opens the queue in that window sees an empty dossier — the exact "passive case sitting there" the proposal set out to fix. |
| **BYOK key** | RAG reads the request-scoped key from the contextvar inside the request. | `BackgroundTasks` run *after* the response; the contextvar is already reset in the `finally`, so `effective_api_key()` silently falls back to the **server key**. This is precisely the BYOK-into-background leak flagged in the prior session. |
| **Error visibility** | A RAG failure surfaces in the triage response + audit log. | The proposed task swallows errors with `print(...)` — no audit row, invisible in production. |
| **Ordering vs. audit** | Dossier and audit row are written together, consistently. | Case row and recommendation are written by two different code paths at two different times — partial state is observable. |

There is no latency win either: the work is the same RAG query; the only change
is *when* the analyst can trust the field is populated.

## 2. The proposed code does not match this codebase

The snippets assume a stack that isn't here:

- **`database/models.py`, `database/session.py`, `SessionLocal`, declarative
  `Base`** — none exist. Persistence is **SQLAlchemy Core `Table`** objects on an
  **async** engine in [`core/memory.py`](backend/core/memory.py) (WAL SQLite ↔
  Postgres). The `cases` table is `cases_t` (id, category, status,
  assigned_agent, summary, detail, created_at, updated_at). `backend/models/`
  contains only `attrition_model.py` — a maths model, not an ORM table.
- **`services/policy_qa.py` / `query_policy_engine`** — doesn't exist. The RAG
  entrypoint is `pipelines.rag_pipeline.rag_pipeline.query`. It reads the BYOK
  key from a contextvar, **not** a `key=` argument — so `key=effective_key`
  would be ignored.
- **`api/routes/triage.py` / `process_and_log_triage` / `get_active_byok_key`** —
  none exist. Triage is the async `TriageAgent.run`.

A synchronous `SessionLocal()` block inside a background task would also open a
*second* connection against WAL SQLite while a request may hold the writer —
reintroducing the `database is locked` risk we just mitigated.

## 3. The two utility scripts are destructive — do not add them

### `scripts/reindex.py` — would erase the audit log

```python
Base.metadata.drop_all(bind=engine)   # ← drops EVERY table
```

This drops **all** tables, including the immutable `audit` log — the single
source of truth from which every metric, KPI, and compliance export is derived.
It is the most damaging possible operation on this system. It also:

- references non-existent `database.session` / `database.models`;
- conflates two unrelated things. The `allow_destructive_reindex` guard added
  last session is **specifically** about the pgvector `policy_chunks` self-heal
  (a vector-dimension mismatch), **not** the application tables. The correct
  re-index re-embeds policies from the retained `source_text` — it never drops
  `cases`, `audit`, or `users`.

### `scripts/seed_data.py` — would re-introduce the "fabricated metrics" bug

A correct, idempotent `scripts/seed_data.py` already exists. The proposed
rewrite would:

- **Overwrite** it with a **non-idempotent** version (adds 25 random cases on
  *every* run);
- insert cases with **no corresponding audit rows**, directly violating the
  project's central invariant — *"all metrics derived from the audit log, never
  fabricated by agents."* STATUS records that the "fabricated Analytics → live
  metrics" bug was already fixed; this script un-fixes it;
- call `Case(...)` with `ai_recommendation=...` against a `Table` that has no
  such column and no such constructor.

---

## What I'd actually do (correct subset, opt-in)

If the goal is to surface the recommendation as **first-class case fields** (so
the Cases panel renders it without re-querying), the right change is small,
synchronous, and race-free:

1. **Add two columns** to `cases_t` in `core/memory.py`: `ai_recommendation`
   (Text, nullable) and `ai_confidence` (Float, nullable).
2. **Populate them in `TriageAgent.run`**, where the RAG result *already exists*
   — pass them into the existing `memory.create_case(...)` call. No background
   task, no race, no BYOK leak, no new DB session.
3. **Write a *correct* `scripts/reindex.py`** that pairs with the guard: it
   re-embeds policies from `memory`'s retained `source_text` via
   `rag.delete_policy` + `rag.ingest_chunks` (or sets `ALLOW_DESTRUCTIVE_REINDEX`
   only to let the pgvector table recreate), and **never touches `cases`,
   `audit`, or `users`**.
4. **Leave the existing idempotent `seed_data.py` untouched.**

This delivers the visible product win (a populated recommendation on the case)
while preserving human-in-the-loop, the audit log as source of truth, BYOK
isolation, and graceful degradation.

---

## Recommendation

- ❌ Background-task auto-resolution — regresses an existing, better feature.
- ❌ `scripts/reindex.py` as proposed — drops the audit log.
- ❌ `scripts/seed_data.py` rewrite — fabricates metrics, non-idempotent.
- ✅ (Optional) Persist `ai_recommendation` / `ai_confidence` synchronously in
  `TriageAgent.run` + a correct, non-destructive `reindex.py`.

Say the word and I'll implement the ✅ subset.
