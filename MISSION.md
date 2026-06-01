# Mission & Direction

## Mission

> **Give HR and people-ops teams a safe, auditable AI layer that automates the
> routine, escalates the sensitive to a human, and proves every decision —
> open-source and runnable on a laptop.**

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

**Now — trustworthy core (shipped):** 5 agents + a tool-using chat assistant,
multi-modal intake, inbound webhooks, policy ingestion + RAG, human approvals
with reject-capture, immutable audit, auth + RBAC + Google sign-in, chat history
with data controls, Postgres-ready async data layer, Docker-hardened, CI, and a
zero-secret demo path.

**Next — depth & integrations:** LLM-grounded answers with prompt caching, tool
use and citations; LangSmith eval/observability; the connector framework
(Workday/ServiceNow/Slack); a policy-library version manager; bulk operations.

**Later — platform:** multi-tenancy, a compliance dashboard, scale-out
(Redis + task queue + Kubernetes per [SCALING.md](./SCALING.md)), and a
connector marketplace.

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
