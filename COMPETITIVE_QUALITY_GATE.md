# Competitive Quality Gate

Run this gate before a release or hackathon submission. Do not push a claim
whose evidence is marked environment-gated.

## Current evidence

| Gate | Status | Evidence |
|---|---|---|
| Tracked-secret scan | Pass | `gitleaks git --config .gitleaks.toml` |
| SSN absent from resume case/audit storage | Pass | `tests/test_compliance.py` |
| Model allow-list enforcement | Pass | `tests/test_llm_factory.py`, static provider guard |
| Fireworks/BYOK auth contract | Pass | `scripts/collect_hackathon_evidence.py --profile static`, `tests/test_input_shield_byok.py` |
| AMD-hosted Gemma deployment profile | Pass | `scripts/verify_amd_gemma_overlay.py`; live ROCm run still required |
| CPU exact top-5, 10k × 384 | Pass | 3.256292 ms p95 on Darwin arm64; scoring/top-k only |
| AMD/ROCm top-5 | Environment-gated | Run on named ROCm hardware; target <10 ms p95 |
| No-key policy answer | Pass | Local hashing retrieval and grounded excerpt tests |
| Structured triage | Pass | Pydantic category, priority, confidence and rationale |
| Batch JSONL uniqueness | Pass | JSON/JSONL/PDF-folder preparation tests |
| Scanned-resume VLM | Implemented, live run gated | Disabled by default; requires approved image egress and Fireworks config |
| Batch monitoring persistence | Pass | Normalized job metadata is reconciled to `batch_jobs`; no resume output stored |
| Audit and human approval | Pass | Chat/audit, triage and onboarding approval tests |

This is not a green AMD performance submission until the ROCm benchmark and one
live Fireworks structured/VLM/Batch run are attached.

## 1. Security

Do not use a keyword grep as a secret scanner. Secure code necessarily contains
identifiers such as `api_key`, `secret`, and `password`.

Non-secret hackathon gate:

```bash
python scripts/collect_hackathon_evidence.py --profile static
```

```bash
gitleaks dir . --no-banner --config .gitleaks.toml --redact --exit-code 1

cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  -p pytest_asyncio.plugin \
  tests/test_security.py \
  tests/test_input_shield_byok.py \
  tests/test_provider_guardrails_static.py \
  tests/test_compliance.py -q
```

Text sent to external model paths is PII-redacted. Scanned images are different:
pixels may contain names and identifiers that cannot be removed reliably before
vision extraction. `ENABLE_RESUME_VLM=false` is therefore the default. Enabling
it is an explicit data-egress decision requiring an approved provider agreement.

## 2. Vector performance

```bash
cd backend
python -m scripts.benchmark_vector_search \
  --rows 10000 --dimension 384 --queries 30 --top-k 5 \
  --enforce-target --output benchmark-vector.json
```

The command measures in-memory exact cosine scoring plus top-k. It excludes
embedding and database/network time and reports whether the result is CPU or
Triton. The committed CPU result is
[`backend/benchmarks/results/vector-search-darwin-arm64.json`](./backend/benchmarks/results/vector-search-darwin-arm64.json).

For AMD kernel evidence:

```bash
python -m benchmarks.benchmark_kernels \
  --matrix --max-gpu-memory-mb 2048 \
  --output benchmark-amd.json
```

Publish the GPU model, ROCm/Torch/Triton versions, shape, dtype, recall/error,
p50/p95 and memory. A CPU pass cannot support an AMD claim.

## 3. Fireworks

### Structured policy and triage

Policy synthesis retrieves five chunks, cites bracketed source numbers and
rejects uncited or out-of-range model citations. Triage returns the typed
`category`, deterministic `priority`, `confidence`, and `rationale`.

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  -p pytest_asyncio.plugin \
  tests/test_grounding_guardrails.py \
  tests/test_fireworks_workloads.py \
  tests/test_llm_factory.py -q
```

### Fireworks auth and BYOK

Fireworks follows the OpenAI-compatible Serverless auth profile:
`Authorization: Bearer $FIREWORKS_API_KEY` against
`https://api.fireworks.ai/inference/v1`. The hosted demo can instead use
`X-Client-LLM-Key`; that key stays in browser memory, is sent only to verified
model-capable routes, is held in a request-scoped contextvar, and is cleared
after the response. The backend ignores the header on ordinary application
routes even if a client sends it manually.

Offline contract checks:

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  -p pytest_asyncio.plugin \
  tests/test_input_shield_byok.py tests/test_llm_factory.py -q
```

Credentialed live check:

```bash
export LLM_PROVIDER=fireworks
export FIREWORKS_API_KEY=...
export FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
export ALLOWED_MODELS=accounts/fireworks/models/deepseek-v3p1
python -m scripts.verify_hackathon_env --mode fireworks-auth
python -m scripts.fireworks_smoke --enable-cost-tracking
curl -s http://localhost:8000/byok/verify \
  -H "X-Client-LLM-Key: $FIREWORKS_API_KEY"
python -m scripts.byok_smoke --provider fireworks --json
```

The BYOK response must report `status=verified` and `provider=fireworks`; do not
store the secret value itself.

## 3.5 AMD-hosted Gemma

The judged AMD path uses `LLM_PROVIDER=amd_vllm`, an internal
OpenAI-compatible vLLM `/v1` endpoint, and a Gemma/Gamma-family served model
present in `ALLOWED_MODELS`.

Offline contract checks:

```bash
python scripts/verify_amd_gemma_overlay.py
kubectl kustomize deploy/k8s/overlays/amd-gemma >/tmp/hrcc-amd-gemma.yaml
```

Credentialed AMD-cluster proof:

```bash
kubectl apply -k deploy/k8s/overlays/amd-gemma
kubectl -n hr-ai-system rollout status deploy/hrcc-gpu-inference
kubectl -n hr-ai-system port-forward svc/hrcc-gpu-inference 8001:8000
curl http://localhost:8001/health
curl -H "Authorization: Bearer $AMD_VLLM_API_KEY" http://localhost:8001/v1/models
cd backend
python -m scripts.amd_vllm_smoke --json
```

The backend `/health` response must report `provider=amd_vllm` and
`byok_supported=false`; `/v1/models` must list the Gemma/Gamma-family served
model present in `ALLOWED_MODELS`. `AMD_VLLM_API_KEY` is a private service key
and must never be submitted through `X-Client-LLM-Key`.

### Batch preparation

```bash
export ALLOWED_MODELS=accounts/example/models/approved-model

python -m scripts.fireworks_prepare_batch test_data.jsonl output.jsonl \
  --model "$ALLOWED_MODELS"

python -m scripts.fireworks_prepare_batch ./resumes output.jsonl \
  --model "$ALLOWED_MODELS" \
  --job-description-file job-description.txt
```

For scanned PDFs, use `--vision` only after approving image egress:

```bash
python -m scripts.fireworks_prepare_batch ./scanned-resumes output-vlm.jsonl \
  --model "$ALLOWED_MODELS" --vision --max-pages 10
```

Every row has a unique `custom_id`; duplicate IDs fail before upload. Fireworks
requires JSONL under 1 GB and a Batch-compatible model. See the
[official Batch documentation](https://docs.fireworks.ai/guides/batch-inference).

### Batch monitor

```bash
python -m scripts.fireworks_batch_job watch \
  --job-id resume-demo-001 --interval 10 --max-polls 60
```

The monitor records provider state and request counts in `batch_jobs`. It does
not persist candidate content or claim that completed rows passed human review.

### Scanned-resume VLM

```bash
export ENABLE_RESUME_VLM=true
export FIREWORKS_VISION_MODEL=accounts/example/models/approved-vision-model
# FIREWORKS_VISION_MODEL must also be in ALLOWED_MODELS.
```

An image-only upload is rendered in memory, bounded by page count and payload
size, sent through the central Fireworks client, validated against a strict
schema, converted to contact-free screening text, and then processed by the
advisory resume screener. Fireworks documents VLM image inputs and JSON Schema
responses in its [Vision guide](https://docs.fireworks.ai/guides/querying-vision-language-models)
and [Chat API](https://docs.fireworks.ai/api-reference/post-chatcompletions).

## 4. Audit and approval

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  -p pytest_asyncio.plugin \
  tests/test_api_integration.py \
  tests/test_auth_chat_reject.py \
  tests/test_cases.py -q
```

The onboarding workflow must remain `awaiting_approval` until a manager decision.
Approve and reject are compare-and-set operations and both create immutable audit
rows with actor ID, role, timestamp and outcome.

## Release decision

Commit and push only after:

1. CI, gitleaks, dependency audit and the full test suite pass.
2. A live Fireworks run validates the configured model IDs and account quota.
3. AMD claims have named-hardware benchmark artifacts.
4. The worktree contains only reviewed release changes.
