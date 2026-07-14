# Govern.ai agentic coding instructions

## Project identity

Govern.ai is a governed, audit-first HR workflow orchestrator.

- Current branch: `dev`. Never commit or push directly to `main`.
- Backend: FastAPI, Pydantic, PostgreSQL/SQLite, pgvector.
- Frontend: Next.js, React, TypeScript, Tailwind.
- Inference: Fireworks serving paths with deterministic no-key fallback.
- Preserve unrelated work in the dirty worktree.

## Core architecture

Use one orchestrator, not inter-agent message passing:

```text
request
  -> route (fast / standard / batch / deploy-on-demand)
  -> CostRouter + semantic cache
  -> provider call through llm_factory
  -> FireworksOutputCertifier
  -> audit service
  -> user response
```

The product surfaces are the selected route/model, cost tier, cache state,
certification result, audit event, deterministic fallback, and human checkpoint.
Do not present envelope or card metadata as a user-facing feature.

## Aligned live agent contract (2026-07-14)

The CrewAI Studio export is design input, not executable source of truth. The
live product keeps the smaller original fleet and maps the exported roles onto
tested runtime boundaries:

| Studio role | Live product mapping |
|---|---|
| GitHub Handbook Ingestor | Removed. Policy/resume context arrives as validated endpoint parameters or the existing pgvector RAG path. |
| HR Triage Specialist | `triage_agent` plus the single orchestrator route gate. |
| Policy + Benefits specialists | `policy_qa_agent`; benefits remain a policy category until a distinct contract has tests and product demand. |
| Bias-Aware Resume Screener | `resume_screener_agent` and the bounded `resume_review` CrewAI subtask. |
| Onboarding Coordinator | `onboarding_agent` with durable approval/rejection state. |
| Attrition Analyst | `attrition_agent`, advisory only. |
| Governance Certifier | `FireworksOutputCertifier` plus typed Pydantic contracts; this is an enforcement service, not an autonomous agent. |
| Agent Config Publisher | Removed. Runtime agents never write specs or code to GitHub. |

The product hierarchy is deliberately bounded:

```text
validated API parameters
  -> one product orchestrator
  -> one selected CrewAI manager subtask
  -> two non-delegating evidence/control workers
  -> output certification
  -> durable human approval task
```

CrewAI is an optional reasoning layer, not the workflow system of record. Its
implemented systems are `policy_case_resolution` and `resume_review`. Discover
them with `GET /crews/hierarchical` and run one with:

```json
{
  "mode": "deterministic | auto | live",
  "inputs": {
    "ticket": "required for policy_case_resolution",
    "policy_context": "optional endpoint-supplied context",
    "policy_version": "optional version"
  }
}
```

Resume runs accept `job_description` and `resume`. Unknown fields are ignored
before execution, required fields are checked, text is sanitized/redacted, and
no crew fetches an external repository. `auto` selects live execution only when
CrewAI and an allowlisted Fireworks or AMD/vLLM runtime are ready; otherwise it
selects deterministic fallback before launch. A live launch or certification
failure must surface as a failure and must never silently fall back.

The user-facing run view shows manager/worker relationships, execution mode,
certification, provider-call state, and the resulting human approval task. It
does not expose prompts, secrets, raw A2A envelopes, or internal tool cards.

## Critical boundaries

- Agent code must not import or instantiate `openai` or `fireworks` clients.
- All provider construction and calls go through `backend/core/llm_factory.py`.
- Every generated response must pass `FireworksOutputCertifier` before use.
- Every material action must be written through
  `backend/services/audit_service.py`.
- Use `CostRouter.classify()` before provider execution.
- Use `HRSemanticCache` for repeated governed queries.
- Read model IDs from `ALLOWED_MODELS` and runtime configuration.
- CrewAI receives its LLM only from `backend/core/llm_factory.py`; Fireworks and
  AMD/vLLM endpoints, keys, and models are injected runtime parameters.
- Never hardcode API keys, provider credentials, or a non-allowlisted model.
- Redact PII before provider transmission and audit persistence.

## Gemma multimodal route

Image-bearing resume requests use the allowlisted Gemma 4 26B A4B IT
deploy-on-demand route. Text-only resume requests remain on the standard route.
The route must fail closed when the required Gemma model is absent, and resume
output remains advisory with a human recruiting decision.

## Contract and safety rules

- Executable workflow contracts remain in `backend/agents/contracts.py`.
- Sensitive HR actions require explicit human review.
- URGENT triage cannot auto-resolve.
- Resume screening cannot auto-reject.
- Attrition output cannot authorize adverse action.
- Deterministic output must be labelled as fallback, never live inference.

## Release gates

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_asyncio.plugin -q
ruff check backend scripts
cd frontend && npm run build
npm audit --audit-level=high
make preview-check
git diff --check
```

Exercise Chat, Cases, Policies, Approvals, Audit, Command, Screener, Attrition,
and Analytics in the local browser. Confirm `/lifecycle/fireworks` exposes the
visible orchestration controls and no A2A/card product surface.

## Anti-patterns

- Inter-agent envelope passing as product architecture.
- GitHub scraping or publishing as a runtime agent dependency.
- Fixed OpenAI model IDs in CrewAI agents.
- A2A cards or tool metadata exposed as a product feature.
- Raw or uncertified model output used by a workflow.
- Provider clients constructed in agent modules.
- Dead demo links, fake live status, or unmeasured performance claims.
- Direct work on `main`.

## Key files

- `backend/agents/orchestrator.py`
- `backend/core/llm_factory.py`
- `backend/core/cost_router.py`
- `backend/core/fireworks_certifier.py`
- `backend/services/semantic_cache.py`
- `backend/services/audit_service.py`
- `frontend/app/components/DemoWalkthrough.tsx`
- `frontend/app/components/AgentFleet.tsx`
- `frontend/app/components/AuditLog.tsx`
