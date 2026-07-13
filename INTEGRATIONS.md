# Govern.ai integrations and use cases

## CrewAI

CrewAI now implements two explicit hierarchical systems. Each uses a custom
manager with `allow_delegation=True`, exactly two non-delegating specialists,
one bounded task, and `Process.hierarchical`.

| System | Manager | Worker agents | Use case |
|---|---|---|---|
| `resume_review` | Talent Review Manager | Resume Evidence Analyst; Fairness and Policy Guard | reconcile normalized skill evidence and fairness controls for recruiter review |
| `policy_case_resolution` | HR Operations Manager | Case Triage Analyst; Policy Grounding Guard | reconcile case classification with policy evidence before HR action |

Discover the topology at `GET /crews/hierarchical`. Run a system at
`POST /crews/hierarchical/{system_id}/run` with one of three modes:

- `auto`: live CrewAI when the package and provider are ready, otherwise honest fallback;
- `deterministic`: always run the local two-worker contracts;
- `live`: require CrewAI plus a configured, allowlisted provider or return `unavailable`.

The live builder uses a real custom manager agent and
`Process.hierarchical`. The deterministic path is explicitly labeled
`deterministic_fallback`; it does not claim CrewAI executed. Both paths return a
schema-certified manager-to-human A2A envelope and preserve the human decision
boundary.

## LangSmith

LangSmith is an optional observability integration for debugging and evaluation,
not the audit system of record. Govern.ai sends trace IDs, agent names, model
route, latency, certification state, token estimates, and cost tier. It does
not send raw resume text, candidate identifiers, provider keys, or full agent
payloads.

Use cases:

- compare deterministic fallback and live-provider runs on the same golden set;
- inspect schema/certification failures and latency by agent;
- attribute estimated input/output tokens to a cost tier;
- attach human-review outcomes as evaluation metadata without feeding them back
  into training automatically.

Each hierarchy creates a manager/root trace with nested worker spans. Only
payload hashes, sizes, top-level keys, agent IDs, status and cost metadata are
sent. Required configuration is explicit: `LANGSMITH_TRACING=true`,
`LANGSMITH_API_KEY`, and optional `LANGSMITH_PROJECT=govern-ai-crewai`.
Legacy `LANGCHAIN_TRACING_V2` and `LANGCHAIN_API_KEY` names remain accepted.
Without those values, local preview stays zero-spend and the append-only
Govern.ai audit remains complete.

## Provider and data integrations

| Integration | Product job | Current status |
|---|---|---|
| Fireworks or AMD/vLLM | optional structured inference / batch / vision | live-gated by credentials and runtime evidence |
| Postgres + pgvector | policy and evidence retrieval | production default; SQLite fallback for preview |
| ATS webhook | resume intake | supported route, synthetic fixtures for demo |
| LangGraph | onboarding checkpoints and policy workflow state | local path proven |
| Human approval queue | final review for sensitive outcomes | required for resume decisions and state-changing onboarding |

The integration rule is simple: frameworks can execute work, but only Govern.ai
policy, certification, audit, and human approval decide whether the result may
move to the next step.
