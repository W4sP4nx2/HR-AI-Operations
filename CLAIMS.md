# Hackathon Claims Ledger

This is the top-level judge-facing claim contract for the **Best AMD-Hosted
Gemma Project** submission. It separates what is already proven by static repo
evidence from what still requires live Fireworks credentials or an AMD ROCm/vLLM
host.

## Submission keyword hooks

Use these hooks in the title, recording, and short description:

- **Fireworks powered** auth — API keys follow the Fireworks Serverless
  quickstart shape: `FIREWORKS_API_KEY`, bearer auth, and the OpenAI-compatible
  base URL `https://api.fireworks.ai/inference/v1`.
- **Gemma powered / Gamma powered** reasoning — model selection must come from
  `ALLOWED_MODELS`, and the judged model/served name must be in the Gemma
  family. Keep “Gamma” only as a search/spoken alias when needed.
- **AMD powered** deployment route — the judged route is `LLM_PROVIDER=amd_vllm`
  against an OpenAI-compatible vLLM endpoint on AMD ROCm hardware.

Safe short version before live hardware proof:

> Fireworks powered auth, Gemma powered model routing, and an AMD powered
> deployment profile for the Best AMD-Hosted Gemma Project track.

## Claim status

| Claim | Status | Current proof | Remaining proof before stronger wording |
|---|---|---|---|
| Fireworks auth contract is implemented | Static-proven | Memory-only, route-scoped `frontend/lib/api.ts`; backend route allowlist in `backend/api/main.py`; `backend/core/runtime_key.py`; `backend/api/routes/byok.py`; `tests/test_input_shield_byok.py` | Real `FIREWORKS_API_KEY`, `python -m scripts.fireworks_smoke --enable-cost-tracking`, and `python -m scripts.byok_smoke --provider fireworks --json` |
| Fireworks quickstart base URL is enforced for the hackathon profile | Static-proven | `backend/scripts/verify_hackathon_env.py`, `tests/test_verify_hackathon_env.py` | Live provider response from `https://api.fireworks.ai/inference/v1` |
| Fireworks BYOK and AMD service auth are isolated | Static-proven | `backend/core/runtime_key.py`, `backend/api/main.py`, `/health` `byok_supported`, hidden AMD browser-key UI, `tests/test_input_shield_byok.py` | Live Fireworks BYOK smoke plus AMD direct service-auth smoke |
| Provider model selection is allowlisted and the AMD served model is Gemma | Static-proven | `ALLOWED_MODELS`, `backend/agents/orchestrator.py`, `tests/test_orchestrator.py`, `backend/scripts/verify_hackathon_env.py` | Fireworks smoke for its approved model plus AMD `/v1/models` showing the Gemma-family served name |
| AMD-hosted Gemma deployment profile exists | Static-proven | `docker-compose.amd.yml`, split GPU/application secrets, concurrency-safe first-admin bootstrap, localhost judge CORS/port-forward contract, external PostgreSQL/pgvector prerequisite, database egress, `scripts/verify_amd_gemma_overlay.py`, `scripts/verify_platform_manifests.py` | Pullable app images, reachable PostgreSQL/pgvector, private admin credentials, and a live AMD ROCm/vLLM host with a Gemma-family served model |
| AMD powered runtime is real | Live-gated | Static deployment profile only | `LLM_PROVIDER=amd_vllm`, validated `amd-runtime.json` with AMD GPU and ROCm/vLLM versions, `/health`, `/v1/models`, and `python -m scripts.amd_vllm_smoke --json` |
| Performance advantage | Not claimed | None | Named hardware, software versions, shape, dtype, p50/p95 latency, memory, and correctness/error evidence |

## Evidence commands

Increment each `run-001` suffix for every attempt; collectors reject non-empty
directories so earlier live evidence cannot be reused accidentally.

Static evidence:

```bash
export STATIC_EVIDENCE_DIR=hackathon-evidence/static-run-001
python3 scripts/collect_hackathon_evidence.py \
  --profile static \
  --out "$STATIC_EVIDENCE_DIR"
python3 scripts/audit_hackathon_readiness.py "$STATIC_EVIDENCE_DIR"
```

Fireworks live proof:

```bash
cd backend
export LLM_PROVIDER=fireworks
export FIREWORKS_API_KEY=...
export FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
export ALLOWED_MODELS=accounts/fireworks/models/deepseek-v3p1
export FIREWORKS_EVIDENCE_DIR=hackathon-evidence/fireworks-run-001
python -m scripts.verify_hackathon_env --mode fireworks-auth
python -m scripts.fireworks_smoke --enable-cost-tracking
python -m scripts.byok_smoke --provider fireworks --json
cd ..
python3 scripts/collect_hackathon_evidence.py \
  --profile fireworks-auth \
  --out "$FIREWORKS_EVIDENCE_DIR"
python3 scripts/verify_evidence_manifest.py "$FIREWORKS_EVIDENCE_DIR"
```

AMD-hosted Gemma live proof:

```bash
cd backend
export LLM_PROVIDER=amd_vllm
export AMD_VLLM_MODEL=google/gemma-3-27b-it
export AMD_VLLM_SERVED_MODEL=amd-gemma-3-27b-it
export AMD_VLLM_API_KEY=...
export HF_TOKEN=...
export AMD_VLLM_BASE_URL=http://amd-vllm.example.internal:8000/v1
export ALLOWED_MODELS=$AMD_VLLM_SERVED_MODEL
export AMD_EVIDENCE_DIR=hackathon-evidence/amd-run-001
python -m scripts.verify_hackathon_env --mode amd-gemma
python -m scripts.amd_vllm_smoke --json
cd ..
python3 scripts/capture_amd_runtime_evidence.py \
  --target kubernetes \
  --out /tmp/amd-runtime.json
python3 scripts/preflight_amd_gemma_judge.py \
  --mode live \
  --amd-runtime-evidence /tmp/amd-runtime.json
python3 scripts/collect_hackathon_evidence.py \
  --profile amd-gemma \
  --amd-runtime-evidence /tmp/amd-runtime.json \
  --out "$AMD_EVIDENCE_DIR"
python3 scripts/verify_evidence_manifest.py "$AMD_EVIDENCE_DIR"
```

## Phrases to avoid until live proof exists

- “AMD powered” as a live-hosting claim without the AMD GPU name, ROCm/vLLM
  versions, and successful Gemma smoke run;
- “10x faster” or any speedup claim;
- “production compliant”;
- “fully autonomous HR decisions”;
- “zero hallucinations” or “zero PII risk.”
