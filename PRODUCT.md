# Product Direction — What This Is, and Who It's For

The reasoning behind the app's shape: why **Fleet + Policies** is the thesis, the
competitive wedge, and the **two-audience** model (employee self-service vs. HR
operator console).

---

## 1. The thesis: Fleet acts, Policies ground, Governance makes it safe

The product is an **operating layer for HR work**, not a chatbot and not a wiki.

- **Fleet = action.** The agents *do* HR work — triage, answer, screen, onboard,
  predict. Without agents it's a CRUD app.
- **Policies = grounding.** An ungrounded LLM in HR is a liability. Policies turn
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

### How it behaves
- **Demo mode (`AUTH_ENFORCE=false`, default):** *all* surfaces are shown so a
  reviewer can explore the whole system from one login. The top bar shows a
  "demo · open access" chip so this is honest, not hidden.
- **Enforced mode (`AUTH_ENFORCE=true`):** surfaces are **gated by role**. A signed-in
  `viewer` gets the "HR Assistant — Employee self-service" chat-only view; HR roles
  get the operator console. RBAC also gates the *actions* (approve/ingest/manage),
  so it's defence-in-depth: navigation *and* endpoints.

This directly answers "normal users shouldn't see high-level requests": in the real
product they don't — they get a focused assistant, and the command center is
reserved for the people who operate it.

---

## 4. Why one dashboard in the demo

Convenience and narrative: a reviewer logs in once and sees everything, then flips
`AUTH_ENFORCE=true` to watch the same app become a role-scoped product. The split is
**configuration, not a rebuild** — the surfaces and the RBAC are already there.

---

## 5. Roadmap implied by this model
- **Per-user case ownership** so employees see *their* cases (today cases are
  org-scoped by role).
- **Embeddable employee chat widget** (Slack/Teams/portal) as the primary employee
  entry point — the dashboard becomes HR-only.
- **Tenant isolation** for multi-org deployments (see [SCALING.md](./SCALING.md)).

See [MISSION.md](./MISSION.md) for principles and [COMPLIANCE.md](./COMPLIANCE.md)
for how the access model maps to privacy obligations.
