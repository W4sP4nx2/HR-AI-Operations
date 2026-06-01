# Agent Playbook — Use Cases & Workflows

The systematic reference for the five agents in the HR AI Command Center. Each
agent is **engineered, not loose**: it has a typed input model, a validated output
contract, a required role, declared tools, and explicit guardrails — all defined in
[`backend/agents/contracts.py`](./backend/agents/contracts.py) (`AGENT_SPECS`) and
enforced by contract tests (`tests/test_agent_contracts.py`).

> **How to read this:** each agent card below maps 1:1 to its `AgentSpec`. The
> "Validated output" is the Pydantic schema the agent's real output is checked
> against on every run and in CI.

---

## The fleet at a glance

| Agent | Role to use | Risk posture | Input → Output contract |
|-------|-------------|--------------|--------------------------|
| **Triage** | analyst+ | escalate | `TicketInput` → `TriageResult` |
| **Policy Q&A** | viewer+ | advisory | `TicketInput` → `PolicyAnswer` |
| **Resume Screener** | analyst+ | decision-support | `ResumeInput` → `ResumeScore` |
| **Onboarding Orchestrator** | manager+ | gated-write | `NewHireInput` → `OnboardingResult` |
| **Attrition Predictor** | manager+ | advisory | `AttritionInput` → `AttritionResult` |

RBAC roles ascend: **viewer → analyst → manager → admin**. In advisory mode
(`AUTH_ENFORCE=false`, the default) anyone can run anything for demos; in enforced
mode the "Role to use" column is required.

---

## 1. Triage Agent

- **Purpose:** classify an incoming HR ticket and route it.
- **Framework:** CrewAI (LLM classifier) with a deterministic keyword fallback.
- **Validated input:** `TicketInput { text: str (non-empty) }`
- **Validated output:** `TriageResult { category, case{id,category,status,assigned_agent}, resolution? }`
- **Tools:** keyword/LLM classifier · RAG pipeline · cases store.
- **Guardrails:** URGENT **always escalates to a human** (never auto-resolved);
  every classification is audited.

**Workflow**
```
ticket ─▶ classify ─┬─ URGENT     ─▶ open case (status=escalated, assignee=human) ─▶ audit
                    ├─ POLICY     ─▶ RAG auto-resolve ─▶ case(status=resolved)     ─▶ audit
                    └─ other      ─▶ open case (status=open, category=X)           ─▶ audit
                                    └─▶ WebSocket "new_case" ─▶ live Cases feed
```

**Use cases**
- *HR ops inbox:* "Payroll fails today, urgent!" → `URGENT` → escalated to a human in ms.
- *Self-service:* "What's the carry-over rule for leave?" → `POLICY` → auto-resolved via RAG.
- *Routing:* "Question about my dental plan" → `BENEFITS` → queued by category.

---

## 2. Policy Q&A Agent

- **Purpose:** answer policy questions from ingested documents, with citations.
- **Framework:** LangGraph `StateGraph` over the RAG pipeline.
- **Validated input:** `TicketInput { text }`
- **Validated output:** `PolicyAnswer { answer, source_documents[], confidence_score 0..1 }`
- **Tools:** `qdrant_search` · `get_policy_doc` · Claude synthesis.
- **Guardrails:** grounded in retrieved docs (cites `doc_id`); says "no relevant
  policy found" instead of hallucinating when the store is empty.

**Workflow**
```
question ─▶ embed ─▶ Qdrant top-k ─▶ [hit?] ─yes─▶ Claude synthesise + cite ─▶ answer ─▶ audit
                                     └─no──▶ "No relevant policy found"        ─▶ answer ─▶ audit
```

**Use cases**
- Employee asks "how many vacation days?" → cited answer from `annual_leave_policy`.
- HR ops spot-checks an answer's sources in the Audit panel.
- Powered by the **Chat** panel too (the `search_policy` tool calls this pipeline).

---

## 3. Resume Screener Agent

- **Purpose:** score a resume against a job description and explain the fit.
- **Framework:** CrewAI (3-agent crew) with a deterministic embedding fallback.
- **Validated input:** `ResumeInput { job_description, resume (non-empty) }`
- **Validated output:** `ResumeScore { score 0..100, recommendation, reasoning, matched_skills[], missing_skills[] }`
- **Tools:** embedding similarity · skill matcher · CrewAI crew.
- **Guardrails:** **decision-support only — never auto-rejects**; every screen is audited.

**Workflow**
```
JD + resume ─▶ extract skills ─▶ semantic + keyword score ─▶ recommendation
            └─ (CrewAI narrative when an API key is set) ─▶ ResumeScore ─▶ audit
```

**Use cases**
- Recruiter attaches a resume PDF + types the JD → "Score 95 · hire", matched/missing skills.
- ATS webhook (`POST /webhooks/ats`) screens inbound applicants automatically.
- A human always makes the final call; the score is a ranked first pass.

---

## 4. Onboarding Orchestrator

- **Purpose:** run the new-hire checklist, pausing for human approval.
- **Framework:** LangGraph state machine with a durable human checkpoint.
- **Validated input:** `NewHireInput { name, email, department, manager }`
- **Validated output:** `OnboardingResult { status: paused|completed|error, task?, state? }`
- **Tools:** validate · create_accounts · assign_training · notify.
- **Guardrails:** state-changing steps require **explicit human approval**;
  **approval AND rejection are captured** in the audit log with a reason.

**Workflow**
```
new hire ─▶ validate ─▶ create_accounts ─▶ assign_training ─▶ ⏸ PAUSE (Approvals)
                                                                │
                          ┌──── manager decision (manager+) ────┤
                          ▼                                      ▼
        APPROVE: send_welcome ─▶ notify_manager ─▶ done    REJECT: unwind + reason
                          ▼                                      ▼
              audit "human_approved"                  audit "human_rejected"
```

**Use cases**
- Coordinator starts onboarding for "Ada Lovelace" → status `paused` at `send_welcome_email`.
- Manager **Approves** in the Approvals panel → emails send, manager notified, audited.
- Manager **Rejects** "start date not confirmed" → workflow unwinds; reason captured.

---

## 5. Attrition Predictor

- **Purpose:** score attrition risk and surface the top drivers.
- **Framework:** scikit-learn `RandomForestClassifier` + Claude explanation.
- **Validated input:** `AttritionInput { tenure_months, performance_score 1..5, absence_days, last_promotion_months, salary_band 1..5, manager_rating 1..5 }`
- **Validated output:** `AttritionResult { attrition_risk_score 0..1, top_risk_factors[3], explanation }`
- **Tools:** random forest · feature attribution · Claude explanation.
- **Guardrails:** **advisory only** — framed to start a retention conversation,
  never punitive; manager+ access; sensitive-data handling reviewed.

**Workflow**
```
employee features ─▶ RandomForest.predict_proba ─▶ risk score
                  └─ feature attribution ─▶ top 3 drivers ─▶ Claude/templated explanation
                                                          └─▶ AttritionResult (advisory)
```

**Use cases**
- HRBP scores an at-risk profile → "10% risk; drivers: tenure, performance, manager rating."
- Output framed as "consider a retention conversation," never as a verdict.

---

## End-to-end: a day in the Command Center

```
1. Admin signs in (or Google) ─▶ RBAC role attached to the session.
2. Manager uploads policy PDFs (Policies panel) ─▶ ingested + registered.
3. Employee asks a question in Chat ─▶ search_policy ─▶ cited answer (audited).
4. A ticket arrives (UI / webhook) ─▶ Triage ─▶ URGENT escalates, POLICY auto-resolves.
5. Recruiter screens a resume ─▶ ResumeScore ─▶ shortlist (audited, human decides).
6. Coordinator starts onboarding ─▶ paused ─▶ Manager Approves/Rejects (captured).
7. HRBP checks attrition risk ─▶ advisory watchlist.
8. Compliance opens Audit ─▶ every action above, exportable as CSV.
```

Every step is **validated against a contract**, **gated by a role** where it
matters, and **written to the immutable audit log** — the loop that makes this an
HR *Master* Center rather than a loose collection of scripts.

---

## For engineers: adding or changing an agent

1. Define/extend the input + output models and add an `AgentSpec` to
   `AGENT_SPECS` in `agents/contracts.py` (purpose, role, tools, guardrails, risk).
2. Implement the agent; ensure its return validates via `validate_output(name, result)`.
3. Add it to `AGENT_REGISTRY` (API) — `test_registry_is_complete` enforces parity.
4. Add a contract test mirroring the ones in `tests/test_agent_contracts.py`.
5. Gate its trigger with `Depends(require_role(spec.min_role))` if it writes or is sensitive.

The registry is the single source of truth; the docs, the API, and the tests all
derive from it, so an agent **cannot ship loosely** — it must declare its contract.
