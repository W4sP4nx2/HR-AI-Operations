# Govern.ai product direction

This document defines who the product serves and where its boundaries sit.
Current implementation status belongs in [README.md](./README.md); trust
principles belong in [MISSION.md](./MISSION.md).

---

## 1. Shared product thesis

The product is an **operating layer for HR work**, not a chatbot and not a wiki.

- **Fleet = action.** The agents *do* HR work — triage, answer, screen, onboard,
  predict. Without agents it's a CRUD app.
- **Policy evidence = grounding.** An ungrounded LLM in HR is a liability. Policies turn
  "an AI" into "*your company's* HR assistant" — answers cite *your* documents.
- **Governance = trust.** Audit, human-in-the-loop approvals, RBAC, and bias
  guardrails make the first two deployable in a regulated domain.

> Remove any leg and it collapses into a toy, a search box, or a black box.

**Do policies have to be imported first? No.** The center boots, authenticates,
triages, screens, onboards, predicts, and audits with **zero policies**. Policies
are *fuel*: they upgrade the knowledge-grounded agents (Policy Q&A, POLICY-class
triage) from honest "not documented" to cited answers. The seed script ingests
samples so the demo isn't empty.

---

## 2. Competitive wedge

| Segment | Examples | Their model | We win on | They win on |
|---------|----------|-------------|-----------|-------------|
| HR service delivery | Workday, ServiceNow HRSD, SuccessFactors | Closed, costly, not agent-native | Open-source, agent-native, audit-first, self-host | Integrations, scale, trust |
| HR chatbots / Q&A | Leena AI, Moveworks, Espressive | Closed SaaS, mostly single-purpose | Multi-agent + HITL + audit | Polish, connectors, support |
| People analytics | Visier | Dashboards, not actioning | Agents *act*, advisory-not-punitive, bias-tested | Mature models |
| Agent toolkits | LangChain/CrewAI templates | Libraries, not HR products | HR guardrails, compliance evidence, RBAC | Flexibility |

**White space:** there is no strong **open-source, audited, multi-agent HR command
center** that runs with zero secrets and ships compliance evidence. The moat is the
**governance + open-source + data-residency (self-host)** combination that closed
SaaS can't match for regulated buyers.

---

## 3. Two audiences, two surfaces

The "Command Center" is an **operator console for the HR *team***, not an employee
tool. Employees and HR are different users with different needs — and different
**privacy boundaries**.

### Employee (self-service) — `viewer`
A clean **chat-first** surface: ask HR questions (RAG-grounded, cited), and (roadmap)
submit a ticket / check *their own* case. They **must not** see the fleet, all
cases, policy management, or the audit log — that would be a privacy and liability
problem.

### HR operator console — `analyst` → `manager` → `admin`
The full dashboard, unlocked progressively:

| Role | Sees | Can do |
|------|------|--------|
| **viewer** (employee) | Chat | Ask questions; (roadmap) own cases |
| **analyst** (HR) | + Fleet, Cases, Analytics | Run agents, triage, screen resumes |
| **manager** | + Policies, Approvals, Audit | Approve/reject, manage policies, review audit |
| **admin** | everything | Manage users & roles, config |

### How access behaves
- **Open-access evaluation (`AUTH_ENFORCE=false`, local default and public
  sandbox):** no login is required. A persona launchpad exposes seeded
  evaluation surfaces and labels roles as advisory.
- **Enforced mode (`AUTH_ENFORCE=true`):** surfaces are **gated by role**. A signed-in
  `viewer` gets the "HR Assistant — Employee self-service" chat-only view; HR roles
  get the operator console. RBAC also gates the *actions* (approve/ingest/manage),
  so it's defence-in-depth: navigation *and* endpoints.

This directly answers "normal users shouldn't see high-level requests": in the real
product they don't — they get a focused assistant, and the command center is
reserved for the people who operate it.

---

## 4. Why one console in open-access evaluation

A reviewer enters without credentials, chooses a seeded persona, and can inspect
the complete workflow. Setting `AUTH_ENFORCE=true` turns the same application
into a role-scoped product. The split is configuration, not a separate build.

---

## 5. Roadmap implied by this model
- **Per-user case ownership** so employees see *their* cases (today cases are
  org-scoped by role).
- **Embeddable employee chat widget** (Slack/Teams/portal) as the primary employee
  entry point — the dashboard becomes HR-only.
- **Tenant isolation** for multi-org deployments (see [SCALING.md](./SCALING.md)).

See [MISSION.md](./MISSION.md) for principles and [COMPLIANCE.md](./COMPLIANCE.md)
for how the access model maps to privacy obligations.

## 6. Flagship workflow and integration boundary

**Auditable Resume Review** is the flagship proof of the Govern.ai operating
layer. The workflow is:

```text
resume intake → identity blinding → structured profile → policy guard
→ transparent advisory rubric → explanation → human approval → audit
```

The extractor and policy guard are independently addressable A2A-shaped HTTP
roles (`/a2a/agents/.../rpc`) and exchange certified, PII-safe artifacts. The
current demo proves two endpoints in one service; it does not claim remote
federation or two separately deployed services. See
[A2A_TECHNICAL_PLAN.md](./A2A_TECHNICAL_PLAN.md).

CrewAI is an optional bounded narrative adapter around already blinded data.
LangSmith is an optional redacted trace/evaluation sink. Neither framework is
the authorization source, audit system of record, or hiring decision-maker. See
[INTEGRATIONS.md](./INTEGRATIONS.md) for the concrete use cases and gates.
