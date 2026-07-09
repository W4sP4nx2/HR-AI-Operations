# Use Cases — How People Actually Use the HR AI Command Center

This is a hands-on walkthrough of the system **as it runs today** (locally, no
Docker, no API key required). Every request and response below was captured
against the live backend on `http://localhost:8000`. Each scenario names the
**persona**, the **trigger**, the **exact call**, the **real result**, and what
the **dashboard** shows.

> **Run it yourself**
> ```bash
> # backend
> cd backend && source .venv/bin/activate && uvicorn api.main:app --port 8000
> # frontend (separate shell)
> cd frontend && npm run dev    # → http://localhost:3000
> ```
> Everything works in **fallback mode** with no secrets. Ingest policies into
> pgvector and configure an allowlisted Fireworks or AMD/vLLM endpoint to upgrade
> answers from deterministic excerpts to model-grounded synthesis.

---

## Scenario 1 — Employee asks a policy question
**Persona:** any employee · **Panel:** Fleet → Policy Q&A · **Risk:** read-only

> *"How many vacation days do I get?"*

```bash
curl -s -X POST http://localhost:8000/agents/policy_qa_agent/trigger \
  -H 'Content-Type: application/json' \
  -d '{"input":"How many vacation days do I get?"}'
```
**Today (no policies ingested, no key):**
```json
{ "success": true, "data": {
  "answer": "(LLM disabled — showing top retrieved policy excerpt)\n\nNo relevant policy found.",
  "source_documents": [], "confidence_score": 0.0 } }
```
**With policies ingested + an active provider:** a grounded answer that cites
the specific policy document and version, with a confidence score from
retrieval. Every query is written to the audit log.

**In the UI:** the employee never sees raw JSON — HR ops watches Policy Q&A runs
tick up in the **Fleet** panel and can spot-check answers in **Audit**.

---

## Scenario 2 — HR ops triages an URGENT ticket
**Persona:** HR operations · **Panel:** Cases · **Risk:** escalates to a human

> *"System is down and payroll fails today, urgent help needed!"*

```bash
curl -s -X POST http://localhost:8000/agents/triage_agent/trigger \
  -H 'Content-Type: application/json' \
  -d '{"input":"System is down and payroll fails today, urgent help needed!"}'
```
**Real result:**
```
category: URGENT  |  status: escalated  |  assigned: human
```
The triage agent classified the ticket, opened a case, and **routed it straight
to a person** — it did *not* try to auto-resolve. A WebSocket event fires so the
case appears instantly in the live feed.

**In the UI:** a new row appears in **Cases** with a red `URGENT` chip and
`escalated → human`, and the "LIVE" badge confirms the WebSocket pushed it without
a refresh.

---

## Scenario 3 — HR ops triages a routine policy ticket
**Persona:** HR operations · **Panel:** Cases · **Risk:** auto-resolved via RAG

> *"Question about my health insurance benefits enrollment"*

```bash
curl -s -X POST http://localhost:8000/agents/triage_agent/trigger \
  -H 'Content-Type: application/json' \
  -d '{"input":"Question about my health insurance benefits enrollment"}'
```
**Real result:** `category: BENEFITS | status: open` — categorised and queued.
A POLICY-class ticket would be **auto-resolved** through the same RAG pipeline as
Scenario 1, closing the loop without a human. URGENT is the only class that always
demands a person.

**Why this matters:** the same agent both *deflects* routine work and *protects*
the human escalation path — that split is the core value to an HR ops team.

---

## Scenario 4 — Recruiter screens a resume against a JD
**Persona:** recruiter · **Panel:** Fleet → Resume Screener · **Risk:** decision-support only

```bash
curl -s -X POST http://localhost:8000/agents/resume_screener_agent/trigger \
  -H 'Content-Type: application/json' \
  -d '{"payload":{
        "job_description":"Senior Python engineer with FastAPI and PyTorch and AWS experience",
        "resume":"5 years Python, FastAPI, PyTorch, AWS, built ML pipelines"}}'
```
**Real result (strong candidate):**
```json
{ "score": 70, "recommendation": "hire",
  "reasoning": "Semantic fit 0.72; matched 4/6 required skills (keyword coverage 67%). Strong overall alignment.",
  "matched_skills": ["python","fastapi","pytorch","aws"],
  "missing_skills": ["senior","engineer"] }
```
A weak candidate (marketing resume vs. the same JD) scored **41 → no-hire**. The
screener returns the full structured contract every time — and it **never
auto-rejects**; it hands the recruiter a ranked, explainable decision.

> Works with **zero** heavy dependencies: when `sentence-transformers` is absent
> the embedder falls back to a deterministic hashing embedding, so the score is
> still meaningful and reproducible.

---

## Scenario 5 — Onboarding a new hire (human-in-the-loop)
**Persona:** HR coordinator + hiring manager · **Panel:** Approvals · **Risk:** writes, gated by approval

This is the flagship workflow: a LangGraph state machine that **pauses for a human**
before any sensitive step.

**Step 1 — kick off onboarding:**
```bash
curl -s -X POST http://localhost:8000/agents/onboarding_agent/trigger \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"name":"Ada Lovelace","email":"ada@acme.com",
        "department":"engineering","manager":"grace@acme.com"}}'
```
The agent runs `validate → create_accounts → assign_training` then **pauses**:
```json
{ "status": "paused", "task": {
  "id": "TASK-1B04E5B8", "step": "send_welcome_email", "status": "awaiting_approval",
  "context": "Ready to send welcome email to ada@acme.com with accounts
    ['sso:ada@acme.com','email:ada@acme.com','hris:Ada Lovelace'] and training
    ['security-awareness','code-of-conduct','engineering-101']." } }
```

**Step 2 — the task appears in the Approvals queue:**
```bash
curl -s http://localhost:8000/cases/pending      # → the TASK-... awaiting_approval
```

**Step 3 — the coordinator approves (with a reason, captured for audit):**
```bash
curl -s -X PATCH http://localhost:8000/cases/onboarding/approve \
  -H 'Content-Type: application/json' \
  -d '{"task_id":"TASK-1B04E5B8","reason":"Verified offer accepted and start date confirmed"}'
```
**Real result — the workflow resumes to completion:**
```json
{ "state": { ...,
  "welcome_sent": true, "manager_notified": true } }
```
The pending queue is now empty, and the audit trail reads:
```
onboarding | paused   | 02:17:05
onboarding | success  | 02:17:23
```
**Rejecting** instead (`/reject` with a reason) sends the workflow back to the
agent with the feedback — nothing sensitive happens without sign-off.

**In the UI:** the **Approvals** panel shows the pending card with full context;
Approve/Reject buttons resume or unwind the workflow live.

---

## Scenario 6 — HRBP checks attrition risk
**Persona:** HR business partner / people manager · **Panel:** Fleet → Attrition · **Risk:** advisory only

```bash
curl -s -X POST http://localhost:8000/agents/attrition_agent/trigger \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"tenure_months":8,"performance_score":2.0,"absence_days":20,
        "last_promotion_months":40,"salary_band":1,"manager_rating":2.0}}'
```
**Real result:**
```json
{ "attrition_risk_score": 0.10,
  "top_risk_factors": [
    {"factor":"tenure_months","contribution":0.126},
    {"factor":"performance_score","contribution":0.124},
    {"factor":"manager_rating","contribution":0.105}],
  "explanation": "Estimated attrition risk is 10%. The main drivers are
    tenure_months, performance_score, manager_rating. Consider a retention
    conversation and reviewing recent recognition and growth opportunities." }
```
A clearly at-risk profile scores **higher** than a healthy one (verified in the
test suite). The output is framed to **start a retention conversation** — never as
a punitive signal.

**In the UI:** the **Analytics** panel renders the attrition risk distribution as a
donut chart alongside resolution KPIs.

---

## Scenario 7 — Compliance officer reviews the audit trail
**Persona:** compliance / HR governance · **Panel:** Audit · **Risk:** read-only

Every agent action across all six scenarios above was logged automatically.

```bash
curl -s "http://localhost:8000/audit"                 # full trail, newest first
curl -s "http://localhost:8000/audit?agent=triage_agent"   # filter by agent
```
Each row carries `agent_name`, `action_type`, `input`, `output`, `status`, and
`timestamp`. For a monthly report, download it as CSV:
```bash
curl -s "http://localhost:8000/audit/export" -o audit.csv
```
**In the UI:** the **Audit** panel lists every action with a one-click CSV export —
this is the compliance backbone that makes the automation defensible.

---

## Scenario 8 — Operator monitors the fleet
**Persona:** HR ops lead · **Panel:** Fleet + top bar

The top bar polls `/health` every 10s (**System Healthy · N active**). The **Fleet**
panel polls `/agents` and shows each agent's status badge (IDLE/RUNNING/ERROR, with
a pulse animation while RUNNING), last action, last run time, and total run count —
plus an inline **Trigger** box to invoke any agent by hand.

```bash
curl -s http://localhost:8000/agents      # live status for all 5 agents
curl -s http://localhost:8000/health      # {status, agents_registered, agents_active}
```

---

## What changes when you add secrets / scale up

| Capability | Fallback mode (today) | + Fireworks configuration | + pgvector | + LangSmith |
|------------|----------------------|----------------------|----------|-------------|
| Policy Q&A | top retrieved excerpt | Fireworks-synthesised, cited answer | real top-k semantic retrieval | full trace + eval scores |
| Triage     | keyword classifier | LLM classifier (CrewAI) | POLICY auto-resolve via RAG | per-run observability |
| Resume     | hashing-embedding score | CrewAI 3-agent narrative review | — | — |
| Attrition  | RandomForest + templated text | Fireworks plain-English explanation | — | — |

Nothing about the **workflows, audit, approvals, or UI** changes — only the depth
of the intelligence. That separation is what lets you demo the whole system on a
laptop and harden it for production incrementally (see
[IMPLEMENTATION.md](./IMPLEMENTATION.md) §3 Docker/K8s and §7 rollout).
