<div align="center">

# 🛠️ HR AI Command Center

**A safe, audited, open-source AI control plane for HR & people-operations.**

A fleet of specialised agents triages tickets, answers policy questions from
*your* documents, screens resumes, orchestrates onboarding, and flags attrition
risk — every action **audited**, every sensitive step **human-approved**, and it
runs on your laptop with **zero secrets**.

`FastAPI` · `Pydantic AI` · `LangGraph` · `CrewAI` · `Postgres + pgvector` · `Next.js 14`

</div>

---

## What is this?

The HR Command Center is an **operating layer** for HR work — not a chatbot and
not a wiki. Three pillars:

- **Fleet (action):** five agents that *do* HR work.
- **Policies (grounding):** RAG over your own policy PDFs so answers cite *your*
  documents, not a generic model.
- **Governance (trust):** human-in-the-loop approvals, role-based access, PII
  redaction, and an immutable audit trail make it deployable in a regulated domain.

> **AI engine — explicit & honest.** Intelligence is powered by **Anthropic Claude
> (Opus-capable)** via the Anthropic API. There is **no Gemini / no bundled CLM
> CLI**. The API key is read **only from the environment** (`ANTHROPIC_API_KEY`) —
> **never hardcoded** and never shipped in the frontend bundle. With **no key set**,
> the whole system runs in a deterministic fallback mode (keyword triage, hashing-
> embedding scoring, templated explanations) so you can evaluate it for **$0**.

---

## ✨ Features

- 🤖 **Five agents** — Triage · Policy Q&A · Resume Screener · Onboarding
  Orchestrator · Attrition Predictor (typed, contract-validated I/O).
- 💬 **Conversational assistant** (Pydantic AI) with tool calls, streaming, and a
  deterministic fallback.
- 📄 **RAG inside Postgres (pgvector)** — chunk → embed → top-k cosine (HNSW).
  One datastore; Qdrant optional.
- ✅ **Human-in-the-loop** approvals; **manual Resolve / Reopen** on cases.
- 🔒 **Auth + RBAC** (viewer → analyst → manager → admin) + **Google sign-in**;
  **role-aware surfaces** (employees get chat-only; HR gets the full console).
- 🧾 **Immutable audit log** with CSV export; **PII redacted at write** (audit +
  chat).
- ⚖️ **Compliance built-in** — demographic-blind resume scoring (bias gate in CI),
  prompt-injection refusal, advisory-only attrition, model cards.
- 💸 **Cost controls** — `MOCK_LLM` / `DEMO_MODE`, semantic answer cache, lean
  production image.
- 🔁 **Multi-modal intake** (text · PDF · URL scrape) + **inbound webhooks**
  (ATS / ticketing / forms).
- ↩️ **Undo** — soft-delete policies and restore (re-embed) from a toast.

---

## 🚀 Quickstart

```bash
# 1) Backend (zero secrets needed)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed_data            # 10 sample policies, cases, a chat demo
uvicorn api.main:app --reload --port 8000

# 2) Frontend
cd ../frontend && npm install && npm run dev    # http://localhost:3000
```

**Optional upgrades** (all env-driven, none required):

```bash
export ANTHROPIC_API_KEY=sk-ant-...    # LLM-grounded answers (Claude/Opus)
export DATABASE_URL=postgresql://hr:pass@localhost:5432/hrdb   # real pgvector RAG
export AUTH_ENFORCE=true               # enforce RBAC + the employee/HR surface split
```

Single-datastore stack (Postgres + pgvector + app):

```bash
export JWT_SECRET="$(openssl rand -hex 32)"
docker compose -f docker-compose.prod.yml up --build -d
```

See [`backend/.env.example`](./backend/.env.example) for **every** flag.

### .gitignore (what never gets committed)

`.env` / `.env.*` · `*.db` (+ `-wal`/`-shm`) · `.venv/` · `node_modules/` ·
`.next/` · `backend/sample_data/` · `.DS_Store`. Secrets live in the environment
only; CI runs **gitleaks** to keep it that way.

---

## 🧭 Usage

| You want to… | Do this |
|--------------|---------|
| Ask a policy question | **Chat** → "How many vacation days do I get?" → cited answer |
| Triage a ticket | **Chat / Fleet** → "I'm being harassed by my manager" → URGENT → human |
| Load company policies | **Policies** → drag-drop PDFs → chunked + embedded |
| Screen a resume | **Fleet → Resume Screener** → attach PDF + paste JD → score + skills |
| Approve onboarding | **Approvals** → review the paused step → Approve / Reject |
| Close a case | open it in **Cases** → **Mark resolved** (or Reopen) |
| Prove compliance | **Audit** → filter → **Export CSV** |

---

## 🔄 Workflow

```
 Upload policy PDF ─▶ extract ─▶ chunk ─▶ embed ─▶ pgvector (policy_chunks, HNSW)
                                                       ▲ top-k cosine
 Inbound (UI / chat / webhook) ─▶ TRIAGE classifies ─┐ │
                                                     ▼ │
                          creates CASE (auto-assigned + auto-status)
        URGENT → escalated·human   POLICY → resolved (cited)   else → open·queued
                                                     │
 Human resolves / reopens an open case ──────────────┤  (Resolve / Reopen button)
                                                     ▼
        Cases (live feed) ─▶ Analytics (KPIs + charts) ─▶ Audit (immutable, PII-redacted)
```

Every step is **validated against a contract**, **gated by a role** where it
matters, and **written to the audit log**.

---

## 🚪 Preconfigured portals

| Portal | Who | Surfaces |
|--------|-----|----------|
| **Employee self-service** | `viewer` (enforced mode) | **Chat only** — "HR Assistant" |
| **HR operator console** | `analyst` → `manager` → `admin` | Fleet · Cases · Policies · Analytics · Approvals · Audit (unlocked by role) |
| **Login / SSO** | everyone | Email+password · **Google OAuth** · "continue as guest" (demo) |
| **API docs (Swagger)** | developers | `http://localhost:8000/docs` |
| **Datastore** | ops | Postgres + pgvector on `:5432` (or SQLite for dev) |

In demo mode (`AUTH_ENFORCE=false`) all surfaces are shown from one login; enforced
mode applies the role split.

---

## 🖥️ Dashboard UI

Brand palette `#5D1C6A · #CA5995 · #FFB090 · #FFF1D3` — minimalist, responsive.

- **Chat** — streaming assistant with tool-call badges + a "basic mode" chip.
- **Fleet** — agent status, last action, run counts, inline trigger (text/PDF/URL).
- **Cases** — live WebSocket feed, category chips, **detail drawer** (ticket +
  audit activity trail + Resolve/Reopen).
- **Policies** — drag-drop upload, chunk counts, status, **delete with Undo**.
- **Analytics** — KPIs (resolved, escalations, hours saved) + per-agent bar +
  attrition-risk donut.
- **Audit** — every action, filter by agent, **CSV export**.
- **Approvals** — human-in-the-loop queue (approve / reject with reason).

---

## 📁 Project structure

```
hr-command-center/
├── backend/
│   ├── agents/        triage · policy_qa · resume_screener · onboarding · attrition · chat · contracts
│   ├── api/           FastAPI app + routes (agents · cases · policies · chat · auth · audit · webhooks)
│   ├── core/          memory (async SQLAlchemy) · security (JWT/RBAC) · safety · guardrails · embeddings
│   ├── services/      rag (backend selector) · pgvector_store
│   ├── pipelines/     ingestion · intake (PDF/URL) · rag_pipeline
│   ├── models/        attrition_model (scikit-learn)
│   ├── scripts/       seed_data · seed_admin · embed_policies
│   └── tests/         unit · integration · compliance/ (bias) · load/ (locust)
├── frontend/          Next.js 14 · Tailwind · TypeScript (app/, lib/, auth/, components/)
├── docker-compose.yml · docker-compose.prod.yml · render.yaml
└── docs: README · OVERVIEW · WALKTHROUGH · AGENT_PLAYBOOK · COMPLIANCE · MODEL_CARDS · SECURITY · SCALING · …
```

---

## 🧰 Tech stack

**Backend** — FastAPI · async SQLAlchemy (SQLite ↔ Postgres) · **pgvector** ·
Pydantic AI · LangGraph · CrewAI · scikit-learn · sentence-transformers · pypdf ·
httpx · BeautifulSoup · PyJWT · bcrypt · Authlib.
**Frontend** — Next.js 14 · React 18 · TypeScript · Tailwind CSS · Recharts ·
lucide-react.
**AI** — Anthropic Claude (Opus-capable) via env key; deterministic fallbacks.
**Infra** — Docker (multi-stage, non-root) · GitHub Actions CI (lint · test ·
compliance gate · build · gitleaks) · Render blueprint.

---

## 🌍 Open source

MIT-licensed and self-hostable (SQLite → Postgres, no lock-in). Contributions
welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md). One-command reproducible demo
(`python -m scripts.seed_data`), CI gates on every PR, and labelled good-first-issues.
**79 tests** green; bias disparity-ratio < 1.1 enforced in CI.

---

## 👤 About the author

> _Replace with your details before publishing._

**\<Your Name\>** — \<role / focus, e.g. "AI/ML engineer building trustworthy AI
for people operations"\>.
🔗 GitHub: `github.com/<you>` · LinkedIn: `linkedin.com/in/<you>` ·
✉️ `<you@example.com>`

Built as an open-source reference implementation and full-stack AI-engineering
portfolio piece.

---

## ⚠️ Disclaimer

This software is provided **"as is"** for **decision-support and reference**
purposes. It is **not legal, HR, or compliance advice**, and it does **not** make
fully automated employment decisions — every adverse action (termination,
rejection, discipline) requires a qualified human. AI outputs can be wrong; the
attrition model ships trained on **synthetic data** and must be validated on your
own governed dataset before any real use. Bias guardrails reduce but do not
eliminate risk — run your own audits (e.g. NYC LL144) and complete a DPIA / vendor
DPA as your jurisdiction requires. You are responsible for lawful, fair, and
privacy-respecting use of this software and any data you put into it.

---

## 📜 License & trademark

**License:** MIT — see [LICENSE](./LICENSE). You may use, copy, modify, and
distribute the software, including commercially, subject to the license terms; it
is provided without warranty.

**Trademark:** "HR AI Command Center" and any associated names, logos, and brand
palette are **not** licensed under MIT and remain the property of their owner.
You may run, fork, and reference the project, but please **do not present a fork as
the official project** or imply endorsement without permission. "Anthropic",
"Claude", "Next.js", "FastAPI", "PostgreSQL", and other names are trademarks of
their respective owners and are used here for identification only.

> _Replace "\<owner\>" / brand specifics with your details before publishing._
