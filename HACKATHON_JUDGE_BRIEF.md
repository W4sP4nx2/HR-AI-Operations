# Hackathon Judge Brief

## One-Line Thesis

Govern.ai is a governed, cost-bounded HR operations layer with typed,
certified handoffs: deterministic when no model is available,
Fireworks-authenticated for live structured inference, and AMD-Gemma deployable
through an OpenAI-compatible ROCm/vLLM route.

Keyword hooks for the submission title and recording: **AMD powered**, **Gemma
powered** / **Gamma powered**, and **Fireworks powered**. Use “Gemma” for the
official technical claim; keep “Gamma” only as a keyword alias when needed.

## The Nail In The Head

Most agent demos fail in enterprise settings because they treat model calls as
magic. This project treats model calls as governed infrastructure:

1. **Route cheaply** — deterministic fast paths and the smallest allowlisted
   capable model handle simple work.
2. **Retrieve narrowly** — policy answers use pgvector chunks and citations
   instead of stuffing full PDFs into prompts.
3. **Constrain outputs** — agent contracts use schema-bound structured output
   and certification before another agent consumes a result.
4. **Attribute spend** — cost tier, model route, token estimates, cache state and
   provider-call state are recorded with each governed run.
5. **Escalate safely** — low confidence, urgent tickets, policy conflicts and
   sensitive actions route to human review.

## What Judges Should See

| Moment | What it proves |
|---|---|
| Run with no API key | The product is useful before any provider spend. |
| `/agents/orchestrator/plan` | The fleet chooses an agent, serving path, model source and Fireworks primitive before execution. |
| Governed CrewAI run in Fleet | Endpoint parameters drive a bounded manager/worker subtask; the result is certified and a real approval task appears in the queue. |
| Fireworks BYOK verification | Hosted-provider spend is opt-in; the memory-only Fireworks key is accepted only on verification, chat, and agent-trigger routes. |
| AMD service-auth boundary | Browser BYOK disappears in the AMD profile; the backend uses its private vLLM service key and the GPU pod alone receives `HF_TOKEN`. |
| Split GPU/application secrets | The Hugging Face weight-download token is mounted only into the inference pod, not the backend. |
| Policy Q&A with citations | RAG grounds answers in policy evidence rather than chat history. |
| Resume / Batch path | Bulk work is asynchronous and auditable instead of fake-synchronous. |
| Approval queue | CrewAI human-review flags are durable approve/reject work, not decorative metadata. |
| Integrations panel | CrewAI is optional and certified; LangSmith is optional redacted observability, not the audit system of record. |
| AMD/vLLM profile | The same workflow can target a Gemma-family model served on AMD ROCm/vLLM. |
| `CLAIMS.md` | Static, Fireworks-live and AMD-live claims are separated by evidence status. |

## Canonical Judge Topology

Use one AMD gfx94X/MI300X-family host with Docker Compose for the recorded and
live judged run. It keeps PostgreSQL and the backend on a private Compose
network and exposes the direct vLLM port on loopback only. Kubernetes is a
future-state scale-out option; it is not required for this hackathon or to
demonstrate the core AMD-hosted Gemma claim.

The provider handoff is deliberate:

1. Run `make judge-fireworks-live` against the hosted Fireworks profile to prove
   the API-key/BYOK contract.
2. Start the AMD Compose profile and switch `LLM_PROVIDER=amd_vllm`.
3. Run `make judge-amd-live` to capture the named AMD/ROCm/vLLM runtime, prove
   application login, prove browser BYOK is disabled, and smoke the served Gemma
   model.

## Evidence Commands

Use a new `run-001` suffix for each attempt; evidence directories are
intentionally single-use.

Static package:

```bash
export STATIC_EVIDENCE_DIR=hackathon-evidence/static-run-001
python3 scripts/collect_hackathon_evidence.py \
  --profile static \
  --out "$STATIC_EVIDENCE_DIR"
python3 scripts/verify_evidence_manifest.py "$STATIC_EVIDENCE_DIR"
```

Fast static gate before every rehearsal:

```bash
make judge-static
```

Local endpoint-driven CrewAI proof (no provider key):

```bash
curl -s http://127.0.0.1:8010/crews/hierarchical
curl -s -X POST http://127.0.0.1:8010/crews/hierarchical/policy_case_resolution/run \
  -H 'content-type: application/json' \
  -d '{"mode":"deterministic","inputs":{"ticket":"Urgent safety incident","policy_context":"Route safety incidents to a human HR manager."}}'
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -p pytest_asyncio.plugin \
  backend/tests/test_hierarchical_crewai.py -q
```

Fireworks live proof:

```bash
cd backend
export FIREWORKS_EVIDENCE_DIR=hackathon-evidence/fireworks-run-001
python -m scripts.verify_hackathon_env --mode fireworks-auth
python -m scripts.fireworks_smoke --enable-cost-tracking
python -m scripts.byok_smoke --provider fireworks --json
cd ..
python3 scripts/collect_hackathon_evidence.py \
  --profile fireworks-auth \
  --out "$FIREWORKS_EVIDENCE_DIR"
```

The first three commands above are also available as `make
judge-fireworks-live` after the Fireworks environment variables are injected.

Use a currently available serverless model for this inexpensive auth smoke.
Fireworks Gemma 3 27B is currently deploy-on-demand rather than serverless; the
AMD/vLLM phase below is the authoritative Gemma hosting proof.

AMD-hosted Gemma live proof:

```bash
export AMD_EVIDENCE_DIR=hackathon-evidence/amd-run-001
docker compose -f docker-compose.prod.yml -f docker-compose.amd.yml \
  --profile amd up -d
make judge-amd-live
python3 scripts/collect_hackathon_evidence.py \
  --profile amd-gemma \
  --amd-runtime-evidence /tmp/amd-runtime.json \
  --out "$AMD_EVIDENCE_DIR"
python3 scripts/verify_evidence_manifest.py "$AMD_EVIDENCE_DIR"
python3 scripts/audit_hackathon_readiness.py "$AMD_EVIDENCE_DIR"
```

`make judge-amd-live` captures the Compose runtime and then invokes
`scripts/preflight_amd_gemma_judge.py --mode live`; the explicit script name is
kept here so the evidence step remains discoverable and auditable.

For a non-default evidence location, run `make judge-amd-live
AMD_RUNTIME_EVIDENCE_FILE=/secure/tmp/amd-runtime.json` and pass the same path to
the collector. Use `capture_amd_runtime_evidence.py --target kubernetes` only for
the scale-out Kubernetes route.

## Safe Submission Wording

Use:

> Fireworks-authenticated and AMD-Gemma deployable; live provider and hardware
> performance claims remain gated by smoke/benchmark evidence.

Short keyword version:

> Fireworks powered auth, Gemma powered model routing, and an AMD powered
> deployment profile for the Best AMD-Hosted Gemma Project track.

Do not use until live evidence exists:

- “AMD powered” as a live-hosting claim without naming the AMD GPU, ROCm/vLLM
  versions, and successful Gemma smoke run;
- “10x faster”;
- “production compliant”;
- “fully autonomous HR decisions”;
- “zero hallucinations” or “zero PII risk.”
