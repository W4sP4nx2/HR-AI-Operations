# HR AI Command Center

> **A safe, audited, open-source AI layer for HR & people-ops.** A team of agents
> triage tickets, answer policy questions from *your* documents, screen resumes,
> orchestrate onboarding, and flag attrition risk — every action **audited**, every
> sensitive step **human-approved**, and it runs on your laptop with **zero secrets**.

> 🚀 **Live demo — BYOK sandbox:** **https://hr-frontend-sve4.onrender.com**
>
> By design this public instance ships with **no server API key**. To see the live
> LLM agents, **bring your own temporary Anthropic key** — it lives only in your
> browser session frame (sent as `X-Client-LLM-Key`, held in a request-scoped
> contextvar) and is **never stored, logged, or written to our database**. Without a
> key, every feature still works in deterministic fallback mode. *That's the
> zero-trust Provider Sandbox architecture — a security choice, not a missing feature.*

<!-- CI badge points at the published repo's Actions. -->
[![CI](https://github.com/W4sP4nx2/HR-AI-Operations/actions/workflows/ci.yml/badge.svg)](https://github.com/W4sP4nx2/HR-AI-Operations/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-CA5995)
![Backend](https://img.shields.io/badge/backend-FastAPI%20%C2%B7%20Pydantic%20AI-FFB090)
![Frontend](https://img.shields.io/badge/frontend-Next.js%2014-5D1C6A)
![Tests](https://img.shields.io/badge/tests-175%20passing-CA5995)

A FastAPI backend orchestrates five specialised agents (LangGraph, CrewAI,
scikit-learn) plus a Pydantic AI chat assistant over a RAG pipeline backed by
**pgvector** (RAG lives inside Postgres — one datastore; Qdrant is an optional
alternative). A Next.js 14 dashboard provides login + RBAC, live fleet monitoring,
a conversational assistant, policy management, case triage, human-in-the-loop
approvals, a compliance audit trail and analytics.

## Try it in 2 minutes

```bash
# Backend (zero secrets needed)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed_data          # sample policies, cases, chats
uvicorn api.main:app --reload --port 8000

# Frontend
cd ../frontend && npm install && npm run dev   # http://localhost:3000
```

Everything runs in **deterministic fallback mode** with no API key. Add
`ANTHROPIC_API_KEY` for LLM-grounded answers (+ Postgres/pgvector for real
semantic retrieval), and `AUTH_ENFORCE=true` to turn RBAC from advisory into
enforced. See [SECURITY.md](./SECURITY.md).

> **Demo:** `▶️ add a GIF here` (record Chat → Cases → Approvals).

## Docs

| Doc | What |
|-----|------|
| [OVERVIEW.md](./OVERVIEW.md) | Full project overview (features · quickstart · structure · author · license) |
| [LAUNCH_PLAN.md](./LAUNCH_PLAN.md) | Demo script, OSS success criteria, path to hosting |
| [PRODUCT.md](./PRODUCT.md) | Thesis, competitive wedge, two-audience model |
| [WALKTHROUGH.md](./WALKTHROUGH.md) | 5-minute guided tour + pitch |
| [AGENT_PLAYBOOK.md](./AGENT_PLAYBOOK.md) | Per-agent contracts, use cases & workflows |
| [TEST_PLANS.md](./TEST_PLANS.md) | Agent, RAG, pipeline, BYOK, UI and attrition scenario test plans |
| [USER_MANUAL.md](./USER_MANUAL.md) · [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md) | End-user & operator guides |
| [MISSION.md](./MISSION.md) | Mission & principles |
| [SCALING.md](./SCALING.md) | Architecture & path to 1M+ req |
| [SECURITY.md](./SECURITY.md) | Security posture & hardening |
| [COMPLIANCE.md](./COMPLIANCE.md) | Auditor evidence pack, bias tests, RBAC matrix |
| [MODEL_CARDS.md](./MODEL_CARDS.md) | Per-agent model cards (EU AI Act / LL144) |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Packaging & deploy (Compose / Render) |
| [SHOWCASE_READINESS.md](./SHOWCASE_READINESS.md) | Honest gap review + plan |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | How to contribute |

## Before you run it — costs, privacy & access

- **💸 Bring your own API key.** LLM features call Anthropic and **cost money**;
  free-tier rate limits apply. The app runs **fully without a key** in
  deterministic mode. Set `MOCK_LLM=true` or `DEMO_MODE=true` to guarantee **zero
  LLM spend** (and cache/stabilise demos). Policy answers are cached
  (`POLICY_CACHE_SIZE`) to cut repeat cost.
- **🔒 Your data stays in your instance.** No PII leaves your deployment. Audit
  logs are local; **PII (emails/phones/SSNs/cards) is redacted before it is
  written** (`REDACT_PII=true`). LLM calls happen **only when explicitly
  triggered**.
- **👤 First-run admin.** With open registration, the **first account becomes
  admin**. For enforced setups, set `ADMIN_EMAIL` + `ADMIN_PASSWORD` (admin is
  created on boot) or run `python -m scripts.seed_admin --email you@org.com --password '…'`.
- **🧭 Support boundary.** The OSS build is **advisory-mode by default**
  (`AUTH_ENFORCE=false`) so it's instantly usable. Enforced RBAC, SSO, and
  multi-tenant are **self-host tuning** — set `AUTH_ENFORCE=true` and see
  [SECURITY.md](./SECURITY.md) and [SCALING.md](./SCALING.md). This is a reference
  implementation, not a managed service.

See [`backend/.env.example`](./backend/.env.example) for every flag.

## Architecture

```
┌──────────────────────────┐        WebSocket /ws/feed        ┌─────────────────────────┐
│  Next.js 14 Dashboard     │ <───────────────────────────────│  FastAPI (async)         │
│  Fleet · Cases · Analytics│        REST /agents /cases       │  /agents /cases /audit   │
│  Audit · Approvals        │ ────────/audit /health──────────>│  /health  /ws/feed       │
└──────────────────────────┘                                  └────────────┬────────────┘
                                                                            │
                      ┌───────────────────────────┬───────────────────────┼───────────────────────┐
                      ▼                           ▼                        ▼                       ▼
              Policy Q&A (LangGraph)     Onboarding (LangGraph)    Resume Screener (CrewAI)   Triage (CrewAI)
                      │                           │                        │                       │
                      └────────► RAG pipeline (pypdf → MiniLM/hashing embeddings → pgvector top-k) ◄──────┘
                                                  │
                                       Attrition Predictor (scikit-learn RandomForest + Claude explanations)
                                                  │
                       Postgres + pgvector (audit · cases · users · chat · policy_chunks)  [SQLite for dev]
```

## The five agents

| Agent | Framework | What it does |
|-------|-----------|--------------|
| **Policy Q&A** | LangGraph `StateGraph` | RAG over HR policy PDFs in **pgvector** (top-k cosine via the RAG service). Returns answer, source documents, a confidence score and a `needs_review` flag; refuses prompt-injection; logs every query to the audit table. |
| **Onboarding Orchestrator** | LangGraph | `validate → create_accounts → assign_training → [human checkpoint] → send_welcome_email → notify_manager`. State persists to SQLite; pauses for human approval and emits a WebSocket event. |
| **Resume Screener** | CrewAI (3 agents) | JD Parser → Resume Scorer → Recommendation. Uses sentence-transformers for semantic similarity. Returns `{score, recommendation, reasoning, matched_skills, missing_skills}`. |
| **Triage** | CrewAI | Classifies tickets into BENEFITS / POLICY / ONBOARDING / PERFORMANCE / COMPLIANCE / URGENT. URGENT → human; POLICY → auto-resolved via RAG. |
| **Attrition Predictor** | scikit-learn | `RandomForestClassifier` on six features; returns risk score + top factors, with a plain-English explanation generated by Claude. Trains on synthetic data at startup. |

## Project layout

```
hr-command-center/
├── backend/        FastAPI app, agents, RAG pipeline, core services, tests
├── frontend/       Next.js 14 + Tailwind + TypeScript dashboard
├── docker-compose.yml
├── .github/workflows/ci.yml
└── README.md
```

## Quick start (Docker)

```bash
cd hr-command-center
cp backend/.env.example backend/.env      # add your ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-...        # used by docker-compose
docker compose up --build
```

Then open:

- Dashboard: http://localhost:3000
- API docs (Swagger): http://localhost:8000/docs
- Postgres (pgvector): `localhost:5432` (user `hr`, db `hrdb`)

## Local development (without Docker)

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add ANTHROPIC_API_KEY
uvicorn api.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

> The system is designed to **degrade gracefully**: without an `ANTHROPIC_API_KEY` or a vector backend, agents fall back to deterministic logic (keyword triage, hashing-embedding resume scoring, templated explanations) so the dashboard and API remain fully functional for development and testing.

## RAG & vector search (single datastore)

The system never stuffs whole PDFs into the prompt — it **chunks → embeds →
retrieves only the top-k (5) relevant chunks** per query. The vector backend is
selectable (`VECTOR_BACKEND`, `ENABLE_RAG`):

- **pgvector (default on Postgres)** — embeddings live in a `policy_chunks`
  table (`vector` column, hnsw cosine index). **One datastore** — no separate
  Qdrant service to run.
- **Qdrant** — used only if `VECTOR_BACKEND=qdrant` is explicitly pinned.
- **local (default on SQLite, zero dependencies)** — chunk embeddings are stored
  in a `policy_vectors` table and cosine similarity is computed in-process. RAG
  therefore works **end-to-end with no external services at all** — exactly the
  mode you get from `python -m scripts.seed_data` + `uvicorn`. For HR-sized
  corpora an in-Python top-k scan is plenty fast.

Embeddings come from `sentence-transformers/all-MiniLM-L6-v2` (384-dim) when
installed, else a deterministic, **synonym-aware** hashing embedding (512-dim,
zero-dep — works in the lean image). The fallback drops stopwords and folds common
HR vocabulary (vacation→leave, 401k→benefits, wfh→remote, …) onto shared tokens so
lexical retrieval still surfaces the right policy for the questions reviewers
actually ask. Ingest happens automatically on PDF upload; backfill an existing
deployment with:

```bash
python -m scripts.embed_policies            # (re)embed sample_data/policies
```

Load test the RAG path with Locust — see [`tests/load/`](./backend/tests/load/README.md)
(targets: retrieval < 100 ms, full response < 3 s p95).

## API surface

Every endpoint returns a consistent envelope:
`{ "success": bool, "status": "ok"|"error"|"unavailable", "data": any, "error": string | null }`.
The `status` field lets the UI trigger button distinguish success, a real failure,
and a capability being unavailable.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health + active agent count |
| GET | `/agents` | All agents with live status, last action, run counts |
| POST | `/agents/{name}/trigger` | Manually invoke an agent (JSON `{input, payload}`) |
| POST | `/agents/{name}/trigger/upload` | Invoke from typed text, a **PDF** attachment, or a **URL** to scrape (multipart) |
| POST | `/webhooks/{source}` | Inbound trigger from external systems (ATS, ticketing, forms) |
| GET | `/cases` | List HR cases (filter by `category`, `status`) |
| POST | `/cases` | Create a case |
| GET | `/cases/pending` | Tasks awaiting human approval |
| PATCH | `/cases/{id}/approve` | Approve a paused task (resumes the agent) |
| PATCH | `/cases/{id}/reject` | Reject a paused task with a reason |
| GET | `/audit` | Audit log (filter by `agent`) |
| GET | `/audit/export` | Download the audit log as CSV |
| WS | `/ws/feed` | Live case / approval / escalation events |

## Configuration

All settings load from the environment via `pydantic-settings` (`backend/core/config.py`). No secrets are hardcoded.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `DATABASE_URL` | `sqlite:///./hr_command_center.db` | SQLite database |
| `ENVIRONMENT` | `development` | Deployment environment |

All Claude calls use model `claude-sonnet-4-20250514`.

## Testing & CI

```bash
cd backend && pytest tests/ -v
```

GitHub Actions (`.github/workflows/ci.yml`) runs on push / PR to `main`:

1. **lint** — `ruff` + `black` for Python, `eslint` for TypeScript
2. **test** — `pytest backend/tests/`
3. **build** — `docker build` for backend and frontend

## Design principles

- **Audit everything.** Every agent action is written to the audit table with agent name, action type, input, output, timestamp and status.
- **Human-in-the-loop.** Checkpoints persist agent state and push a WebSocket event so a human can approve or reject before sensitive steps run.
- **Resilient by default.** Optional heavy dependencies (LangGraph, CrewAI, Qdrant, Claude) are loaded lazily with deterministic fallbacks.
- **Consistent contracts.** A single response envelope and typed frontend API client keep the surface predictable.

## Tech stack

FastAPI · LangGraph · CrewAI · Pydantic AI · scikit-learn · sentence-transformers · **Postgres + pgvector** (Qdrant optional) · Anthropic Claude · async SQLAlchemy · JWT/OAuth · Next.js 14 · TypeScript · Tailwind CSS · Recharts · Docker.
