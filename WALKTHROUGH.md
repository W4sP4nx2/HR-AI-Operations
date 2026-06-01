# Application Walkthrough, Problem-Solving & Pitch

A guided tour of the **HR AI Command Center** — what it solves, how to run the
full pipeline end-to-end, and how to pitch it. Companion to
[README](./README.md), [USER_MANUAL](./USER_MANUAL.md),
[OPERATIONS_MANUAL](./OPERATIONS_MANUAL.md), [SCALING](./SCALING.md) and
[PITCH](./PITCH.md). For a formal QA matrix, see
[TEST_PLANS](./TEST_PLANS.md).

---

## 1. The problem

HR and people-ops teams drown in repetitive, high-stakes work spread across
disconnected tools. The same five pains show up everywhere:

| Pain | Cost today | What it needs |
|------|-----------|---------------|
| Policy questions flood HR inboxes | Hours/week of manual lookup | Instant, **cited** answers from *your* documents |
| Urgent tickets buried in a generic queue | Payroll/compliance issues wait | Automatic triage + **human escalation** |
| Resume screening is slow & inconsistent | 15–30 min/resume, no paper trail | Scored, explainable first pass |
| Onboarding breaks across systems | Missed steps, bad first day | Orchestrated checklist with **approval gates** |
| Attrition noticed *after* people quit | Lost talent, hindsight only | Early risk signals framed for action |

And the meta-problem: **most HR automation has no audit trail and no off-switch.**
Regulators, auditors, and employees can't see what an AI decided or why.

---

## 2. The solution in one picture

```
   Inputs                     Control plane                    Outputs
 ───────────         ────────────────────────────         ──────────────
 Typed text  ─┐      ┌──────────────────────────┐        Cited answers
 PDF upload  ─┼────► │  Intake → normalises text │        Triaged cases
 Scraped URL ─┤      └─────────────┬────────────┘        Resume scores
 Webhook     ─┘                    ▼                       Attrition risk
 Chat box    ─────►  ┌──────────────────────────┐        Onboarding steps
                     │   5 agents + chat (RAG)   │            │
                     │  triage · policy · resume │            ▼
                     │  onboarding · attrition   │     Human approval gate
                     └─────────────┬────────────┘            │
                                   ▼                          ▼
                        Immutable audit log  ◄────────  Every action logged
                                   │
                          SQLite (dev) / Postgres (prod)
```

Three principles make it enterprise-credible:

1. **Human-in-the-loop by default** — anything sensitive pauses for approval.
2. **Audit everything** — every action is logged immutably and exportable.
3. **Graceful degradation** — runs on a laptop with zero secrets; intelligence is
   additive (LLM, vector DB, observability layer in as you add them).

---

## 3. Five-minute full-pipeline walkthrough

### 3.0 Seed sample data (one command)
```bash
cd backend && source .venv/bin/activate
python -m scripts.seed_data
```
This generates **5 policy PDFs** (annual leave, parental leave, remote work,
benefits, code of conduct), ingests them, files **6 sample tickets** through
triage (creating URGENT/POLICY/BENEFITS/ONBOARDING cases), and prints a **chat
transcript**. Everything works without an API key.

### 3.1 Start the stack
```bash
# backend
uvicorn api.main:app --reload --port 8000
# frontend
cd ../frontend && npm run dev      # http://localhost:3000
```

### 3.2 Policies — submit a policy for agents to use
**Dashboard → Policies.** Drag-and-drop a policy PDF. It's extracted, chunked, and
ingested into the vector store; the registry shows chunk count and status. This is
the knowledge the Policy Q&A agent and chat assistant answer from.

> API: `POST /policies/ingest` (multipart) · `GET /policies` · `DELETE /policies/{id}`

### 3.3 Chat — ask, triage, and look up in one box
**Dashboard → Chat.** The Pydantic AI assistant picks the right tool per message:

| You type | Tool called | Result |
|----------|------------|--------|
| "How many vacation days do I get?" | `search_policy` | Cited policy answer |
| "Payroll fails today, urgent!" | `triage_ticket` | Opens an URGENT case, returns the id |
| "List all open urgent cases" | `list_open_cases` | Live case list |
| "Status of CASE-AB12CD34?" | `get_case_status` | Case + activity trail |

Replies **stream token-by-token**; tool-call badges show what the agent did. With
no API key it runs in **basic mode** (deterministic tool dispatch); with
`ANTHROPIC_API_KEY` the same UI upgrades to LLM-grounded answers.

> API: `POST /chat` · `POST /chat/stream` (SSE)

### 3.4 Cases — watch the workflow continue
**Dashboard → Cases.** Cases the chat/triage created appear **live**. Click one to
open the **detail drawer**: full ticket + the chronological audit activity trail.
URGENT cases are routed to a human; POLICY questions auto-resolve via RAG.

### 3.5 Fleet — trigger any agent directly
**Dashboard → Fleet.** Trigger an agent with text, a **PDF attachment**, or a URL.
Each run returns **Success / Failed / Unavailable** with an intake summary. Try the
Resume Screener: attach a resume PDF + type a job description → score + reasoning.

### 3.6 Approvals — the human gate
Trigger the Onboarding Orchestrator (Fleet or chat). It runs validate → create
accounts → assign training, then **pauses**. **Dashboard → Approvals** shows the
pending step; Approve (with a reason) resumes it to completion, Reject rolls it
back. Both decisions are audited.

### 3.7 Audit — the compliance backbone
**Dashboard → Audit.** Every action from the steps above is here — input, output,
status, timestamp. **Export CSV** for compliance/finance.

---

## 4. Problem → capability map

| The problem (§1) | How the app solves it | Where |
|------------------|----------------------|-------|
| Policy questions flood HR | RAG over your PDFs, cited answers, via chat or agent | Policies + Chat + Policy Q&A |
| Urgent tickets buried | Triage classifies → URGENT escalates, POLICY auto-resolves | Triage agent, Cases |
| Resume screening slow | Score + matched/missing skills + reasoning from a PDF | Resume Screener (Fleet) |
| Onboarding breaks | Orchestrated checklist, paused for human approval | Onboarding + Approvals |
| Attrition noticed late | Risk score + top drivers, framed for a conversation | Attrition Predictor |
| No audit / off-switch | Immutable log + approval gates on every sensitive step | Audit + Approvals |
| Disconnected tools | Ingests text/PDF/URL/webhooks from existing systems | Intake + Webhooks |

---

## 5. Who uses it

- **HR generalists** — deflect routine questions, triage the inbox, run onboarding.
- **Recruiters** — first-pass resume screening with a paper trail.
- **HR business partners** — attrition watchlist and retention prompts.
- **Compliance/finance** — exportable audit of every automated decision.
- **Employees** — self-serve policy answers in the chat box, 24/7.
- **Engineers** — a production-shaped, runs-on-a-laptop reference implementation.

---

## 6. The pitch

### One sentence
> A safe, audited AI layer for HR and finance that handles routine work
> automatically, escalates anything sensitive to a human, ingests work from any
> source (text, PDF, links, or webhooks from your existing tools), and runs on a
> laptop today with a clear path to a million-request production deployment.

### Why it wins
- **Demoable in 5 minutes, zero secrets** — `seed_data.py` + two `dev` commands.
- **Trust-first** — human-in-the-loop + immutable audit are built into the data
  model, not bolted on. That's what unblocks adoption in regulated HR/finance.
- **Additive intelligence** — the same UI and workflows run deterministically or
  LLM-grounded; you buy AI depth incrementally, never a rewrite.
- **Integration-ready** — multi-modal intake + inbound webhooks mean it slots
  alongside Workday/ServiceNow/ATS instead of replacing them.
- **Scales** — Postgres-ready async data layer, documented path to Redis, task
  queues, and Kubernetes (see SCALING.md).

### Proof points (today)
- 7 agents/tools, multi-modal intake, inbound webhooks, streaming chat assistant.
- Policy ingestion → RAG → cited answers; human-approved onboarding; live case feed.
- **25 backend tests green**, lint/format clean, Docker-hardened, CI in place.

### The ask (to go production-grade)
- `ANTHROPIC_API_KEY` + **prompt caching, tool use, citations** (cost + quality).
- A **PostgreSQL** URL, a **Qdrant** instance, and **policy PDFs** to ingest.
- **LangSmith** for trace/eval observability.
- Optional: Slack app creds for a conversational Q&A wow-moment; Workday/ServiceNow
  sandbox for a live integration demo.

Everything degrades gracefully, so the app stays demoable while these land.

---

## 7. Try it now

```bash
# one-time
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# seed + run
python -m scripts.seed_data
uvicorn api.main:app --reload --port 8000      # API + docs at :8000/docs
cd ../frontend && npm install && npm run dev   # dashboard at :3000
```
Open **http://localhost:3000** → Policies, Chat, Cases, Fleet, Approvals, Audit.

## 8. Prove it

The scenario walkthroughs above are backed by a dedicated test plan:
[TEST_PLANS.md](./TEST_PLANS.md). It covers per-agent golden paths, adversarial
RAG cases, pipeline ingestion, BYOK ephemerality, attrition calibration, and UI
honesty checks. Use it as the acceptance checklist before a demo, PR, or release.
