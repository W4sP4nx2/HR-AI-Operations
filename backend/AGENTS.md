# Backend engineering instructions

## Single-orchestrator boundary

`agents/orchestrator.py` owns route planning. It selects a Fireworks serving
path and allowlisted model, applies cost/cache policy, certifies the result, and
records a privacy-safe audit event. Do not add agent-to-agent messaging or card
dispatch to the product path.

Provider construction stays in `core/llm_factory.py`. Agent modules must not
instantiate OpenAI-compatible clients. Model IDs come from `ALLOWED_MODELS` and
runtime settings only.

Bounded CrewAI subtasks receive sanitized endpoint parameters only. They may
delegate evidence work internally, but the product orchestrator remains the
single owner of routing, certification, audit, and durable human checkpoints.
No CrewAI agent may fetch or publish GitHub content at runtime.

## Safety and contracts

- Validate executable workflow input/output with `agents/contracts.py`.
- Run generated output through `FireworksOutputCertifier` before use.
- Persist material actions through `services/audit_service.py` with hashed or
  redacted inputs.
- Keep URGENT triage, resume screening, attrition, and onboarding behind human
  review boundaries.
- Keep deterministic fallback available and honestly labelled.
- Create a durable `agent_tasks` checkpoint whenever a certified crew result
  requires human review; a label without a queue item is not HITL.

## Gemma

Image-bearing resume work uses an allowlisted Gemma 4 26B A4B IT
deploy-on-demand route. Text-only screening uses the standard route. Missing
Gemma configuration must fail closed before provider execution.

## Verification

Run focused orchestrator tests, the full backend suite, full Ruff checks, the
preview healthcheck, and a provider-bypass scan. Do not claim live Fireworks or
AMD performance without credentials/runtime evidence and measured results.
