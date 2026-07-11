# Hackathon Completion Audit

This audit maps the AMD/Gemma hackathon blueprint to current repository
evidence. It is intentionally stricter than the pitch: if evidence is local,
static, mocked, or environment-gated, the claim says so.

## Verdict

The project is **blueprint-complete and static-evidence complete** for the
Fireworks-first HR AI control-plane story. It is **not live-certified** for
Fireworks billing, Fireworks Batch completion, or AMD-hosted Gemma performance
until the credentialed provider and hardware smoke tests run.

Safe claim today:

> HR AI Command Center is a governed, cost-bounded A2A control plane for HR
> workflows. It runs without model spend, supports request-scoped Fireworks BYOK
> for live structured inference, and includes an AMD/vLLM Gemma deployment
> profile whose real hosting and performance claims are gated by smoke and
> benchmark evidence.

Short release wording: Fireworks-authenticated and AMD-Gemma deployable; live
provider and hardware performance claims remain gated by smoke/benchmark
evidence.

Do not claim today:

- production legal compliance;
- live Fireworks billing savings;
- AMD latency, throughput, or cost advantage;
- 10,000-user production scale;
- autonomous adverse employment decisions;
- zero hallucinations or zero PII risk.

## Requirement Matrix

| Blueprint requirement | Current status | Authoritative evidence |
|---|---|---|
| Senior thesis: governed A2A control plane, not chatbot demo | Implemented in docs | `AMD_HACKATHON_STRATEGY.md` thesis section, `README.md` product core |
| Fireworks-first pivot while keeping AMD/Gemma route | Implemented in docs and config | `HACKATHON_GEMMA_AMD_DEPLOYMENT.md`, `docker-compose.amd.yml`, `deploy/k8s/overlays/amd-gemma` |
| Model IDs not hardcoded; route only from allowlist | Implemented | `backend/core/fireworks.py`, `backend/core/llm_factory.py`, `backend/agents/orchestrator.py`, `tests/test_llm_factory.py`, `tests/test_orchestrator.py` |
| A2A agent cards and tool-visible routing metadata | Implemented | `backend/agents/a2a_cards.py`, `/agents/orchestrator/plan`, `tests/test_orchestrator.py` |
| Certified A2A envelopes for cross-agent handoff | Implemented | `backend/core/a2a_envelope.py`, `tests/test_a2a_envelope.py`, `tests/test_zero_spend_cost_certification.py` |
| Constrained structured output path | Implemented at request-building and certification layer | `backend/core/fireworks.py`, `backend/core/fireworks_certifier.py`, `tests/test_fireworks_workloads.py` |
| Zero-spend cost governance before API calls | Implemented | `backend/core/cost_guard.py`, `backend/core/cost_router.py`, `backend/core/cost_attribution.py`, `tests/test_zero_spend_cost_certification.py` |
| Deterministic cache and context freshness checks | Implemented | `backend/services/semantic_cache.py`, `tests/test_zero_spend_cost_certification.py`, `tests/test_cost_router.py` |
| RAG over policy chunks instead of full-PDF stuffing | Implemented | `backend/services/rag.py`, `backend/services/vector_store.py`, policy/RAG tests, README status |
| Adversarial synthetic dataset bundle | Implemented and locally certified | 40 version-conflict policy PDFs, 10,000 ATS rows, 500 guardrail prompts, 1,000 resume PDFs; `make etl-certify` |
| Postgres/pgvector + MinIO ETL integration | Local Docker run certified | `docs/evidence/local-etl-integration.json`; pgvector 0.8.2, metadata-backed 2024 PTO winner, exactly 1,000 MinIO objects |
| Request-scoped, route-scoped BYOK key handling | Implemented | `backend/core/runtime_key.py`, backend route allowlist in `backend/api/main.py`, `backend/api/routes/byok.py`, memory-only `frontend/lib/api.ts`, `tests/test_input_shield_byok.py` |
| Provider credential trust boundaries | Implemented | Fireworks BYOK may override only Fireworks/hosted-provider auth; AMD/vLLM always uses the server-owned service key; `/health` exposes `byok_supported`; `tests/test_input_shield_byok.py` proves browser keys cannot override or contact AMD/vLLM |
| Enforced-auth first administrator bootstrap | Implemented | AMD overlay requires `ADMIN_EMAIL`/`ADMIN_PASSWORD`; `backend/api/main.py` tolerates concurrent unique-email races across replicas; `tests/test_admin_bootstrap.py` |
| Fireworks Batch preparation and status control plane | Implemented, live job gated | `backend/scripts/fireworks_prepare_batch.py`, `backend/services/fireworks_batch.py`, `/lifecycle/fireworks/batch/{job_id}`, Batch tests |
| Scanned-resume VLM path | Implemented, disabled by default and egress-gated | `backend/services/resume_vlm.py`, `ENABLE_RESUME_VLM=false`, `COMPETITIVE_QUALITY_GATE.md` |
| Human-in-the-loop for sensitive workflows | Implemented for shipped flows | onboarding/case tests, `AGENT_PLAYBOOK.md`, `README.md`, audit/case routes |
| LangSmith/cost observability story | Implemented as optional, best-effort layer | `backend/agents/langsmith_cost_tracker.py`, `tests/test_zero_spend_cost_certification.py`, `README.md` |
| AMD-hosted Gemma deployment profile | Static contract implemented | `scripts/preflight_amd_gemma_judge.py` composes overlay verification, rendered Kustomize, claims checks, runtime evidence, backend provider/BYOK posture, and the live Gemma smoke; `deploy/k8s/overlays/amd-gemma`; `tests/test_amd_gemma_judge_preflight.py` |
| AMD/Gemma live proof | Live-gated | Requires `LLM_PROVIDER=amd_vllm`, named AMD device plus ROCm/vLLM runtime evidence, reachable vLLM `/v1`, served Gemma-family model, and `python -m scripts.amd_vllm_smoke --json` |
| Fireworks live proof | Live-gated | Requires Fireworks key, official base URL, allowlisted model, and `python -m scripts.fireworks_smoke --enable-cost-tracking` |
| Published performance claims | Not allowed yet | Need named hardware, software versions, corpus shape, dtype, p50/p95, correctness/error and memory evidence |

## Static Evidence Run

Command:

```bash
python3 scripts/collect_hackathon_evidence.py --profile static
```

Expected static bundle contents:

- docs link check;
- platform manifest check;
- AMD/Gemma overlay verifier;
- AMD/Gemma one-command static judge preflight;
- frontend lint;
- provider routing, BYOK, orchestrator, AMD smoke-harness and health tests;
- readiness audit;
- generated claims summary and SHA-256 evidence manifest.

The readiness audit safe wording is:

> Fireworks-authenticated and AMD-Gemma deployable; live provider and hardware
> performance claims remain gated by smoke/benchmark evidence.

## Live Certification Still Required

### Fireworks

```bash
cd backend
export LLM_PROVIDER=fireworks
export FIREWORKS_API_KEY=...
export FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
export ALLOWED_MODELS=accounts/fireworks/models/deepseek-v3p1
python -m scripts.verify_hackathon_env --mode fireworks-auth
python -m scripts.fireworks_smoke --enable-cost-tracking
```

Evidence to keep:

- smoke output;
- selected model ID;
- estimated versus provider-billed token cost;
- cache/prefilter/router metrics;
- one structured output sample if pitching live inference.

### AMD-Hosted Gemma

```bash
cd backend
export LLM_PROVIDER=amd_vllm
export AMD_VLLM_API_KEY=...
export AMD_VLLM_BASE_URL=http://amd-vllm.example.internal:8000/v1
export AMD_VLLM_MODEL=google/gemma-3-27b-it
export AMD_VLLM_SERVED_MODEL=amd-gemma-3-27b-it
export HF_TOKEN=...
export ALLOWED_MODELS=$AMD_VLLM_SERVED_MODEL
export AMD_EVIDENCE_DIR=hackathon-evidence/amd-run-001
python -m scripts.verify_hackathon_env --mode amd-gemma
python -m scripts.amd_vllm_smoke --json
cd ..
python3 scripts/capture_amd_runtime_evidence.py \
  --target kubernetes \
  --out /tmp/amd-runtime.json
python3 scripts/collect_hackathon_evidence.py \
  --profile amd-gemma \
  --amd-runtime-evidence /tmp/amd-runtime.json \
  --out "$AMD_EVIDENCE_DIR"
python3 scripts/verify_evidence_manifest.py "$AMD_EVIDENCE_DIR"
```

Evidence to keep:

- `/health` response;
- `/v1/models` response showing the Gemma-family served name;
- chat smoke output;
- GPU model, ROCm version, vLLM version, model ID, prompt shape and latency;
- benchmark JSON before any speed claim.
