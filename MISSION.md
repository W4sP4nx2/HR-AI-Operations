# Mission & Direction

## Mission

> **Give HR and people-ops teams a safe, auditable AI layer that automates the
> routine, escalates the sensitive to a human, and proves every decision —
> open-source and runnable on a laptop.**

The shared product rule is: **Fleet acts, policy evidence grounds, and
governance controls.** Model inference is an optional capability layer around a
durable workflow core, not the system of record and never the final authority
for an adverse employment action.

AI is arriving in HR whether teams are ready or not. Most of it is a black box:
no audit trail, no human gate, no way for an employee or a regulator to ask
"why did this happen?" That's unacceptable for decisions about people — pay,
performance, hiring, leave, attrition. This project exists to make HR automation
**trustworthy by construction**, not as an afterthought.

## Principles (the non-negotiables)

1. **Human-in-the-loop by default.** Anything that writes to a system of record
   or touches a sensitive decision pauses for an explicit human approval — and
   the approval *or rejection* is captured with who, when, and why.
2. **Audit everything.** Every agent action and every human decision is written
   to an immutable log, exportable for compliance. If it isn't logged, it didn't
   happen.
3. **Graceful degradation.** The control plane, audit, approvals and UI always
   work. Intelligence is additive: deterministic fallbacks with zero secrets →
   LLM-grounded with an API key → semantic retrieval with a vector DB. You never
   hit a wall, and you never need a credit card to evaluate it.
4. **Least privilege.** Role-based access (viewer → analyst → manager → admin)
   gates who can trigger agents, approve tasks, manage policies, and administer
   users.
5. **Own your data.** Self-hostable, SQLite-to-Postgres portable, with explicit
   data controls (delete chat sessions, remove policies, export audit). No lock-in.
6. **Integrate, don't replace.** Multi-modal intake (text/PDF/URL) and inbound
   webhooks let it slot alongside Workday, ServiceNow and ATS tools.

## Who it's for

Employees (self-serve policy answers), HR generalists (triage + onboarding),
recruiters (resume screening), HRBPs (attrition signals), compliance/finance
(audit), and engineers (a production-shaped reference for agentic AI).

## Direction (where this is going)

**Now — trustworthy core:** five agents plus a tool-using assistant,
multi-modal intake, policy ingestion and pgvector RAG, human approvals,
immutable audit evidence, auth/RBAC, Fireworks online and Batch contracts,
Docker Compose, and an open-access zero-secret evaluation path.

**Next — measured depth:** run named-hardware AMD/ROCm benchmarks, exercise live
provider smoke tests, strengthen retrieval and agent evaluations, and add
connectors only where a governed workflow needs them.

**Later — production platform:** tenant isolation, enterprise identity,
distributed queues and rate limits, multi-pod realtime fan-out, and managed
Kubernetes only when measured load requires it.

## How features map to the mission

| Capability | Principle it serves |
|------------|---------------------|
| Approval gate + reject capture + audit | Human-in-the-loop · Audit everything |
| Deterministic fallbacks (no key needed) | Graceful degradation |
| RBAC (viewer/analyst/manager/admin) + Google auth | Least privilege |
| Policy registry + ingestion + delete | Own your data |
| Chat history list/get/delete | Own your data |
| Intake (text/PDF/URL) + webhooks | Integrate, don't replace |
| SQLite ↔ Postgres, self-host, MIT licence | Own your data · open-source |

Every decision about what to build next is checked against these principles:
**does it keep HR automation trustworthy, transparent, and in the user's
control?** If not, it doesn't ship.
