# Implementation Plan & Roadmap — HR AI Command Center

This document is the engineering and product companion to the [README](./README.md).
It records **what is built today**, **how to run it (Docker)**, the **backend
implementation plan**, the **improvement backlog for HR managers**, the mapping
to the **target job description (portfolio value)**, and a concrete
**use-case rollout plan**.

---

## 1. Current status (what works today)

| Area | Status | Evidence |
|------|--------|----------|
| FastAPI backend, 5 agents registered | ✅ Done | `GET /health` → `agents_registered: 5` |
| Triage agent (URGENT→human, POLICY→RAG, keyword fallback) | ✅ Done | URGENT ticket escalates to `human`; BENEFITS/POLICY routed |
| Resume screener (deterministic fallback) | ✅ Done | good match → 70/hire, poor match → 41/no-hire |
| Attrition predictor (RandomForest + factors) | ✅ Done | returns `attrition_risk_score` + top 3 factors + explanation |
| Policy Q&A (RAG) | ✅ Done | graceful "no policy found" with empty store |
| Onboarding orchestrator (human checkpoint) | ✅ Done | registered, pauses for approval |
| Graceful degradation w/o Qdrant + sentence-transformers | ✅ **Fixed** | see §2 |
| Next.js 14 dashboard (Fleet/Cases/Analytics/Audit/Approvals) | ✅ Done | live WebSocket feed, brand theme |
| Backend test suite | ✅ 14/14 pass | `pytest tests/ -v` |
| Case detail drawer (ticket + audit activity trail) | ✅ Done | `/cases/{id}/detail`; slide-over in Cases panel |
| Docker Compose (qdrant + backend + frontend) | ✅ Hardened | healthchecks + ordered startup, see §3 |
| CI (lint + test + image build) | ✅ Done | `.github/workflows/ci.yml` |
| **Postgres-ready data layer** (async SQLAlchemy) | ✅ Done | SQLite + Postgres 16 both verified, see SCALING.md §7 |
| **Multi-modal intake** (text · PDF · URL scrape) | ✅ Done | `/agents/{name}/trigger/upload`, PDF resume → 95/hire |
| **Inbound webhooks** (ATS/ticketing/forms) | ✅ Done | `/webhooks/{source}` with routing + secret |
| **Trigger status contract** (ok/error/unavailable) | ✅ Done | UI shows Success/Failed/Unavailable chips |

### Current stage (latest iteration)
The system has moved from "runnable demo" to **integration-ready**: external
systems and documents can drive the agents, every trigger returns a precise
machine-readable outcome, and the data layer is production-portable.

- **Data layer → Postgres-ready** — `core/memory.py` rewritten to async SQLAlchemy
  Core; storage chosen by `DATABASE_URL` (SQLite dev / Postgres prod), public API
  unchanged. Verified on both backends. (SCALING.md §7.)
- **Multi-modal intake** — `pipelines/intake.py` turns typed text, uploaded PDFs,
  or scraped URLs into agent-ready text; `POST /agents/{name}/trigger/upload`.
- **Webhooks & scrapers** — `POST /webhooks/{source}` lets ATS / ticketing /
  forms trigger agents; URL intake scrapes pages (httpx + BeautifulSoup).
- **Status contract** — `ok` / `error` / `unavailable` envelope (`api/responses.py`)
  surfaced as colour-coded chips in the Fleet UI, with an `intake` summary
  ("what was passed in"). `_mode: degraded|full` flags no-LLM runs.
- **Tests** — 14/14 (intake text/PDF/URL, response-contract, case-detail trail).
- **Case detail drawer** — clicking a case opens a slide-over with the full
  ticket and its chronological **audit activity trail** (`/cases/{id}/detail`).
- **Bug fixed** — the async migration left `GET /cases/{id}` calling a deleted
  `get_case_sync`; switched to the async `get_case` and added a regression test.

### Earlier fixes (prior iterations)
- **Qdrant-optional reads** — `VectorStore.search`/`get_by_doc_id` return `[]`
  instead of crashing when `qdrant_client` is missing or the server is down.
- **Embedder fallback** — `core/embeddings.py` falls back to a deterministic
  hashing embedding when `sentence-transformers` is absent.
- **Docker** — `.dockerignore` for both images, healthchecks, ordered `depends_on`.

---

## 2. Design principle: graceful degradation (verified)

The system is layered so the **control plane always works**, and intelligence is
additive:

```
no deps          → keyword triage · hashing-embedding resume scoring · templated explanations
+ sentence-transformers → semantic embeddings for RAG + resume similarity
+ Qdrant running        → real top-k policy retrieval
+ ANTHROPIC_API_KEY     → Claude answers, CrewAI/LangGraph LLM orchestration
+ LangSmith key         → full trace/eval observability (roadmap §5)
```

This is the property that makes the project demo-able anywhere (laptop, CI,
recruiter's machine) without secrets — and is the foundation for the MLOps story
in §6.

---

## 3. Docker setup

### Files
```
docker-compose.yml          dev stack: qdrant + backend (--reload) + frontend (npm run dev)
backend/Dockerfile          python:3.11-slim, layer-cached pip install
frontend/Dockerfile         node:20-alpine
backend/.dockerignore       excludes .venv, *.db, data/, .git  (NEW)
frontend/.dockerignore      excludes node_modules, .next, .git (NEW)
```

### Run the full stack
```bash
cd hr-command-center
export ANTHROPIC_API_KEY=sk-ant-...        # optional; omit to run in fallback mode
docker compose up --build
```
- Dashboard → http://localhost:3000
- API / Swagger → http://localhost:8000/docs
- Qdrant → http://localhost:6333/dashboard

### What hardening was added
- **Healthchecks** — Qdrant (TCP probe on 6333), backend (`/health` 200 check).
- **Ordered startup** — backend waits for `qdrant: service_healthy`; frontend
  waits for `backend: service_healthy`. No more race on first boot.
- **Lean build context** — `.dockerignore` keeps the local `.venv`,
  `node_modules`, SQLite DB and `.git` out of the image (faster builds, smaller
  images, no secret leakage).

### Backend implementation plan — production Docker (backlog)
- [ ] Multi-stage backend image; run as non-root `appuser`.
- [ ] Pin `requirements.txt` (hashes) + split heavy ML deps into an optional layer.
- [ ] Frontend: `output: "standalone"` in `next.config.js` + multi-stage
      `builder → runner` image (~10× smaller than dev image).
- [ ] `docker-compose.prod.yml` override: no bind mounts, `uvicorn` workers
      (gunicorn), `NODE_ENV=production`, restart policies.
- [ ] Push images to GHCR from CI on tagged releases.

### Kubernetes (next milestone)
- [ ] Helm chart: `Deployment` per service, `Service`, `Ingress`, `HPA`.
- [ ] Qdrant as a `StatefulSet` with a `PersistentVolumeClaim`.
- [ ] Migrate SQLite → managed Postgres (`StatefulSet` or external) for HA.
- [ ] `ConfigMap` for non-secret config, `Secret` for `ANTHROPIC_API_KEY`.
- [ ] Liveness/readiness probes mapped to the existing `/health` endpoint.

---

## 4. Backend implementation plan (engineering backlog)

Ordered by priority; each item is independently shippable.

### P0 — correctness & resilience
1. **Persist agent runtime state** to SQLite (currently in-memory in `memory.py`),
   so the Fleet panel survives a restart.
2. **Idempotent triage** — dedupe cases by content hash to avoid duplicate cases
   when an agent is retried.
3. **Structured error envelope** for partial failures (agent ran, sub-step failed).

### P1 — RAG quality
4. **Re-ranking** — add a cross-encoder re-rank step after Qdrant top-k.
5. **Citations with offsets** — return char spans so the UI can highlight sources.
6. **Ingestion API** — `POST /policies/ingest` (multipart PDF) instead of the
   Python-only `rag_pipeline.ingest_directory`.

### P2 — agent depth
7. **Onboarding** — wire real connectors (see §6 integrations) behind the human
   checkpoint; today the steps are simulated.
8. **Attrition** — replace synthetic training data with a CSV upload + scheduled
   retrain job; persist the model artifact.
9. **Triage SLAs** — per-category SLA timers; auto-escalate on breach.

### P3 — platform
10. **AuthN/AuthZ** — JWT + role gate (HR admin vs. analyst vs. read-only).
11. **Rate limiting & request IDs** on every route.
12. **Observability** — OpenTelemetry traces; LangSmith for LLM/agent runs (§6).

---

## 5. Improvement backlog for HR managers (product roadmap)

Framed in the language of the people who *operate* the system, not the people who
build it. Each is written as an outcome.

### Now (next sprint)
- **One-click case detail** — click any case in the feed to see the full ticket,
  the agent's reasoning, retrieved policy sources, and the audit trail in a drawer.
- **Approval reason templates** — reject/approve with reusable canned reasons
  ("needs manager sign-off", "missing documentation") for consistency & speed.
- **CSV export everywhere** — audit log export exists; extend to cases & analytics
  for monthly reporting.

### Next (this quarter)
- **Policy library manager** — upload, version, and retire policy PDFs from the UI;
  see which answers cited which document version (compliance-grade traceability).
- **Bulk resume screening** — drop a folder of resumes against one JD; ranked table
  with matched/missing skills and exportable shortlist.
- **Attrition watchlist** — a saved view of employees above a risk threshold, with
  recommended retention actions and a "schedule 1:1" nudge.
- **Configurable triage rules** — let HR ops define keyword/category routing and
  which categories require a human, without a code deploy.

### Later (strategic)
- **Manager self-service portal** — managers submit onboarding/offboarding and
  track status without emailing HR.
- **Slack / MS Teams agent** — employees ask policy questions in chat; answers are
  RAG-grounded and logged to the same audit trail.
- **Compliance dashboard** — SOC2/GDPR-style report: every automated decision,
  who approved it, and the evidence, on demand.
- **Multilingual policy Q&A** — answer in the employee's language from the same
  English policy corpus.

---

## 6. Portfolio value — alignment with the target JD

This project is a single, runnable artifact that touches **every** competency
area in the role:

| JD requirement | Where it lives in this project | Status |
|----------------|-------------------------------|--------|
| **RAG pipelines** | `pipelines/rag_pipeline.py` — pypdf → MiniLM embeddings → Qdrant top-k → Claude synthesis; Policy Q&A agent | ✅ built, ⏭ re-ranking + citations (§4 P1) |
| **Multi-agent orchestration (GenAI dev)** | 5 agents across LangGraph (`policy_qa`, `onboarding` state machine w/ human checkpoint) + CrewAI (`resume_screener` 3-agent crew, `triage`) | ✅ built |
| **FastAPI microservices (system design)** | `api/` — typed routes, single response envelope, WebSocket feed, CORS, pydantic-settings config | ✅ built |
| **Docker / CI-CD (MLOps)** | `docker-compose.yml` (healthchecks + ordered start), per-service Dockerfiles + `.dockerignore`, `ci.yml` (lint → test → build) | ✅ built, ⏭ K8s + GHCR (§3) |
| **Model lifecycle / monitoring (LangSmith)** | Audit table logs every agent action today; LangSmith tracing is the next observability layer (§4 P3) | ⏭ planned |
| **Workday / ServiceNow integrations (infrastructure)** | Onboarding orchestrator's `create_accounts` / `notify_manager` steps are the integration seam; see §6 connector plan | ⏭ planned (seam in place) |

### Integration connector plan (Workday / ServiceNow)
The onboarding agent already pauses at a human checkpoint and emits WebSocket
events — the right place to attach real systems of record:

- **Adapter interface** — `connectors/base.py` defining `create_account`,
  `assign_equipment`, `open_ticket`, `notify`. Agents depend on the interface,
  not the vendor.
- **ServiceNow** — `open_ticket` / status sync via the Table API; triage URGENT
  cases mirror to a ServiceNow incident.
- **Workday** — `create_account` / worker profile pull via Workday REST; attrition
  features (tenure, comp band) sourced from Workday instead of synthetic data.
- **Mock connectors first** — ship deterministic mocks so the flow is demoable and
  testable without vendor credentials (same philosophy as §2).

### The one-line pitch
> A full-stack AI engineering portfolio piece in one project: production-shaped
> RAG + multi-agent orchestration behind FastAPI microservices, containerized with
> Docker/CI-CD, with a clear path to K8s, LangSmith observability, and Workday/
> ServiceNow integration — and it runs end-to-end with **zero secrets** thanks to
> deterministic fallbacks.

---

## 7. Use-case plan (rollout)

A phased plan to take this from demo to a system HR actually relies on. Each phase
is independently valuable and ends in a usable increment.

### Phase 0 — Policy Q&A copilot (lowest risk, highest visibility)
- **User:** any employee asks "how many vacation days do I get?"
- **Flow:** question → RAG over ingested policy PDFs → grounded answer + citations,
  logged to audit.
- **Why first:** read-only, no writes to systems of record, immediate value, and it
  exercises the whole RAG + audit spine.
- **Success metric:** % of policy questions answered without HR involvement;
  citation accuracy spot-checks.

### Phase 1 — Ticket triage & auto-resolution
- **User:** HR ops inbox.
- **Flow:** incoming ticket → triage agent classifies → POLICY auto-resolved via
  RAG, URGENT escalated to a human, others queued by category.
- **Success metric:** median time-to-first-touch; % auto-resolved; zero URGENT
  tickets missed.

### Phase 2 — Resume screening assist
- **User:** recruiters.
- **Flow:** JD + resume(s) → structured score, matched/missing skills,
  hire/no-hire recommendation → human makes the final call.
- **Guardrail:** decision-support only; never auto-rejects. All scores audited.
- **Success metric:** recruiter hours saved per req; shortlist quality vs. baseline.

### Phase 3 — Onboarding orchestration (writes, behind human approval)
- **User:** HR coordinators + hiring managers.
- **Flow:** new-hire record → validate → create accounts → assign training →
  **human checkpoint** → welcome email → notify manager. Real connectors
  (Workday/ServiceNow) attach here.
- **Guardrail:** every state-changing step is human-approved on first rollout, then
  selectively automated as confidence builds.
- **Success metric:** onboarding cycle time; checklist completeness; error rate.

### Phase 4 — Attrition early-warning
- **User:** people managers + HRBPs.
- **Flow:** scheduled scoring over the workforce → watchlist above threshold →
  recommended retention actions.
- **Guardrail:** advisory only; framed as "start a conversation", never punitive.
  Access-controlled; sensitive-data handling reviewed.
- **Success metric:** retention of flagged-and-actioned employees vs. control.

### Cross-cutting rollout guardrails
- **Human-in-the-loop by default** for any write or sensitive decision (§ already
  built for onboarding; extend to others).
- **Audit everything** — already enforced; this is the compliance backbone.
- **Fail open to humans** — if an agent/LLM is unavailable, the case routes to a
  person, never silently drops (the graceful-degradation property in §2).
- **Start advisory, earn automation** — every agent ships as decision-support; auto-
  actions are unlocked per-category once accuracy is proven against the audit log.
