# Hackathon Deployment: Fireworks Auth + AMD-Hosted Gemma

This is the judge-facing runbook for the **Best AMD-Hosted Gemma Project** track.
It separates three things that are easy to blur during a demo:

1. **Auth** — who pays for live model calls and where the key lives.
2. **Model selection** — exact model IDs or served names come from
   `ALLOWED_MODELS`; the application never invents a fallback model.
3. **Hosting claim** — “AMD-hosted Gemma” means the live judged path reaches a
   Gemma-family model served from an AMD ROCm/vLLM endpoint, with Fireworks used
   as the API-compatible reference path and optional hosted inference plane.

## Win thesis

Govern.ai is strongest when pitched as:

> A governed HR agent control plane that can run without model spend, authenticate
> to Fireworks with request-scoped keys for live structured AI, and switch the
> judged inference path to a self-hosted Gemma model on AMD ROCm/vLLM without
> changing the product workflow.

That gives judges three concrete win points:

| Win point | What to show | Evidence |
|---|---|---|
| Fireworks API auth is safe | BYOK key stays in browser memory, is attached only to verification/model-capable routes, lives in a server request context, and can be verified via `/byok/verify`. | `/byok/verify` `X-BYOK`, ordinary-route rejection tests, no key in Web Storage, DB, or audit logs |
| Provider selection is explicit | Fireworks uses approved `accounts/.../models/...` IDs; the AMD judged route separately requires a Gemma served name. | `/agents/orchestrator/plan`, `verify_hackathon_env.py` |
| AMD hosting is real | Backend points to `AMD_VLLM_BASE_URL`, not Fireworks, for the judged run; the Hugging Face token is mounted only into the GPU pod. | `docker-compose.amd.yml`, split Kubernetes secrets, vLLM health, runtime evidence pack |

## Authentication trust boundaries

These credentials solve different problems and must never be presented as
interchangeable:

| Boundary | Credential | Storage and transport | Rule |
|---|---|---|---|
| User → HR application | Application JWT | Browser session uses `Authorization: Bearer ...`; backend validates role and identity | Controls product access and RBAC; it is not a model-provider key |
| HR application → Fireworks | Server `FIREWORKS_API_KEY`, or visitor Fireworks key in `X-Client-LLM-Key` | Server key comes from deployment secrets; visitor key is memory-only and request-scoped | On allowlisted inference routes, visitor BYOK overrides the server Fireworks key for that request only |
| HR backend → AMD/vLLM | `AMD_VLLM_API_KEY` | Kubernetes/Compose secret shared only by backend and inference service | Private service credential; browser BYOK is disabled and cannot override it |
| GPU pod → Hugging Face | `HF_TOKEN` | GPU-only Kubernetes/Compose secret | Used only to download gated Gemma weights; never mounted into the backend or frontend |

The `/health` response exposes only non-secret posture: `auth_enforced`,
`llm_provider`, `llm_enabled`, `llm_config_issues`, and `byok_supported`. In the
Fireworks profile, `byok_supported=true`. In the AMD/vLLM profile it is `false`.

## Judge keyword hooks

Use these exact hooks in the README, pitch, recording title, and submission
summary. They are intentionally short so a judge can scan them in seconds:

- **AMD powered** — the judged route can switch to `LLM_PROVIDER=amd_vllm` and
  serve the allowlisted model through AMD ROCm/vLLM.
- **Gemma powered / Gamma powered** — the model allowlist and served model name
  must contain the official Gemma family name; keep “Gamma powered” only as a
  search/spoken alias if the event material or user prompt uses that spelling.
- **Fireworks powered** — Fireworks-compatible auth, BYOK verification, and
  OpenAI-compatible request structure prove the hosted/API path.

Safe one-line version:

> Fireworks powered auth, Gemma powered reasoning, and an AMD powered deployment
> route for the Best AMD-Hosted Gemma Project track.

## Fireworks API auth profile

Use this profile for the hosted demo, BYOK sandbox, and Fireworks reference run.
It follows Fireworks' OpenAI-compatible quickstart shape: a bearer API key and
the Serverless base URL.

```bash
export LLM_PROVIDER=fireworks
export FIREWORKS_API_KEY=fw_...                 # secret manager or judge harness
export FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
export ALLOWED_MODELS=accounts/fireworks/models/kimi-k2p6
export AUTH_ENFORCE=true
export REDACT_PII=true
```

No server key is required for the public BYOK demo. In that mode, a visitor's
temporary Fireworks key is sent as:

```text
X-Client-LLM-Key: <visitor Fireworks API key>
```

The browser keeps it only in JavaScript memory, so reload or tab close clears it.
The middleware then stores it in a request-scoped contextvar and clears it after
the request. It is never accepted in the request body, Web Storage, server logs,
the database, or audit records.

Both sides enforce route scope. The frontend attaches the header only to
`/byok/verify`, chat, and agent-trigger calls. The backend independently ignores
BYOK headers on health, metrics, authentication, audit, case, policy-management,
and orchestration-plan routes.

Offline preflight:

```bash
cd backend
python -m scripts.verify_hackathon_env --mode fireworks-auth
```

Live smoke, only after secrets are injected:

```bash
cd backend
python -m scripts.fireworks_smoke --enable-cost-tracking
```

BYOK verification proof, from the running backend:

```bash
curl -s http://localhost:8000/byok/verify \
  -H "X-Client-LLM-Key: $FIREWORKS_API_KEY"
cd backend
python -m scripts.byok_smoke --provider fireworks --json
```

The response must include `"status":"verified"` and `"provider":"fireworks"`.
Do not paste or store the key itself in the evidence bundle.

Fireworks auth proof does not require Gemma. The current
[Fireworks Gemma 3 27B catalog entry](https://fireworks.ai/models/fireworks/gemma-3-27b-it)
lists `accounts/fireworks/models/gemma-3-27b-it` as deploy-on-demand and not
serverless; use it only after creating that deployment. The judged Gemma
requirement is proved by the AMD/vLLM route below, while the inexpensive
Fireworks reference smoke can use any currently available, approved serverless
model ID.

## AMD-hosted Gemma profile

Use this for the **Best AMD-Hosted Gemma Project** judged path. The backend talks
to a local OpenAI-compatible vLLM server running on AMD ROCm. The technical
model ID and served model name must contain the official spelling `gemma`, and
the served name must also appear in `ALLOWED_MODELS`. “Gamma powered” is a
judge-facing keyword alias only; it is never accepted as a model identifier.

The canonical hackathon topology is one AMD host running the production Compose
stack plus the AMD overlay. This minimizes judge-day orchestration risk while
still producing named GPU, ROCm, PyTorch, and vLLM evidence. The Kubernetes
overlay is the scale-out follow-up, not a prerequisite for the primary demo.

```bash
export AMD_VLLM_MODEL=google/gemma-3-27b-it
export AMD_VLLM_SERVED_MODEL=amd-gemma-3-27b-it
export AMD_VLLM_API_KEY=$(openssl rand -hex 32)
export HF_TOKEN=...
export JWT_SECRET=$(openssl rand -hex 32)
export POSTGRES_PASSWORD=$(openssl rand -hex 24)
export ADMIN_EMAIL=judge-admin@example.com
export ADMIN_PASSWORD=replace-with-a-strong-private-password
export AMD_VLLM_MAX_MODEL_LEN=32768
export AMD_VLLM_BASE_URL=http://amd-vllm:8000/v1
export ALLOWED_MODELS=$AMD_VLLM_SERVED_MODEL
export LLM_PROVIDER=amd_vllm
export AUTH_ENFORCE=true
export REDACT_PII=true
```

Start the AMD overlay:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.amd.yml \
  --profile amd up -d
make judge-amd-live
```

The default `gfx94X` image is the current AMD `rocm/vllm` MI300X-family build and
is pinned by its published SHA-256 digest. Gemma 3 weights are license-gated on
Hugging Face, so `HF_TOKEN` is required after accepting Google's usage terms.
The judged Compose profile disables public registration, requires first-admin
and database credentials, passes vLLM auth through `VLLM_API_KEY` rather than a
process argument, and binds direct database/vLLM host ports to loopback.
The vLLM API key protects the OpenAI-compatible `/v1` surface; it is not a
replacement for network isolation on health, metrics, or other HTTP routes.
Keep the direct port loopback-only (or behind an equivalent private firewall)
and retain the Kubernetes NetworkPolicies below when this profile is exposed
outside the host.

The Kubernetes overlay is future-state reference material only. It is not part
of the hackathon runbook and is not required for the primary Compose demo. If a
later scale-out phase needs it, the dedicated overlay requires:

- Provide a reachable PostgreSQL 16 database with `pgvector`; the overlay does
  not deploy one. Replace the external placeholder in `DATABASE_URL`.
- Set private `ADMIN_EMAIL` and strong `ADMIN_PASSWORD` values. Authentication
  is enforced and public registration is disabled in this profile; the backend
  safely bootstraps that first administrator across concurrent replicas.
- Publish or preload `hrcc-backend:1.0.0` and `hrcc-frontend:1.0.0`, or replace
  them with immutable registry digests.
- Run the AMD device plugin and label the judged MI300X node as shown below.

```bash
python scripts/preflight_amd_gemma_judge.py --mode static
kubectl get nodes \
  -o custom-columns=NAME:.metadata.name,ARCH:.status.nodeInfo.architecture,GPU:.status.capacity.amd\.com/gpu
export AMD_NODE_NAME=replace-with-mi300x-node-name
kubectl label node "$AMD_NODE_NAME" accelerator=amd-instinct-mi300x --overwrite
kubectl apply -f deploy/k8s/base/namespace.yaml
cp deploy/k8s/overlays/amd-gemma/hrcc-secrets.example.env /tmp/hrcc-secrets.real.env
cp deploy/k8s/overlays/amd-gemma/hrcc-gpu-secrets.example.env /tmp/hrcc-gpu-secrets.real.env
# accept the Gemma license, then edit every replace-* value, ADMIN_EMAIL,
# ADMIN_PASSWORD, and the DB URL
kubectl -n hr-ai-system create secret generic hrcc-secrets \
  --from-env-file=/tmp/hrcc-secrets.real.env \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n hr-ai-system create secret generic hrcc-gpu-secrets \
  --from-env-file=/tmp/hrcc-gpu-secrets.real.env \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -k deploy/k8s/overlays/amd-gemma
```

`hrcc-secrets` contains application credentials consumed by the backend;
`hrcc-gpu-secrets` contains only model identifiers and `HF_TOKEN`. This prevents
the API process from receiving the gated-weight download credential. The
portable judge profile allows backend egress to TCP 5432; narrow that rule to
the real database destination before production use.

Offline preflight:

```bash
cd backend
python -m scripts.verify_hackathon_env --mode amd-gemma
```

Runtime proof to capture:

```bash
kubectl -n hr-ai-system rollout status deploy/hrcc-gpu-inference
```

Keep the three Kubernetes port-forwards running in separate terminals:

```bash
kubectl -n hr-ai-system port-forward svc/hrcc-backend 8000:8000
kubectl -n hr-ai-system port-forward svc/hrcc-frontend 3000:3000
kubectl -n hr-ai-system port-forward svc/hrcc-gpu-inference 8001:8000
```

Open `http://localhost:3000`, then capture the API and AMD/Gemma checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl -H "Authorization: Bearer $AMD_VLLM_API_KEY" \
  http://localhost:8001/v1/models
cd backend
python -m scripts.amd_vllm_smoke --json
cd ..
python3 scripts/capture_amd_runtime_evidence.py \
  --target docker-compose \
  --out /tmp/amd-runtime.json
python3 scripts/verify_amd_runtime_evidence.py /tmp/amd-runtime.json
# Export the same ADMIN_EMAIL/ADMIN_PASSWORD values used in hrcc-secrets so the
# preflight can prove a real enforced-auth login without printing either value.
python3 scripts/preflight_amd_gemma_judge.py \
  --mode live \
  --amd-runtime-evidence /tmp/amd-runtime.json
```

For the AMD-hosted route, `/byok/verify` must return
`"status":"unsupported"` and `"provider":"amd_vllm"` without contacting vLLM.
The direct `/v1/models` and `amd_vllm_smoke` checks prove private service
authentication without sending the internal key through the browser path.

## Demo sequence for judges

1. Open `http://localhost:3000` through the judged port-forward. Show the app
   works with no provider key: chat, cases, policies, and audit stay usable in
   deterministic mode.
2. Add a Fireworks BYOK key in the UI. Show `/byok/verify` returns
   `status=verified`, `provider=fireworks`, and that live mode does not write
   the key to audit rows.
3. Call `/agents/orchestrator/plan` for a resume or policy workload. Show the
   selected model comes from `ALLOWED_MODELS`.
4. Switch to `LLM_PROVIDER=amd_vllm` with the AMD overlay. Show the same product
   workflow now routes to the AMD-hosted Gemma served name. Show
   `byok_supported=false`, the hidden browser-key control, and the authenticated
   `/v1/models`/AMD smoke evidence from the operator terminal.
5. Open the case/audit detail. Show citations, confidence, human-review triggers,
   and certified A2A envelope metadata.

## Evidence package before submission

Create each bundle in a new, empty directory. The collector refuses to reuse a
non-empty directory so stale live results cannot leak into a later packet.

```bash
export STATIC_EVIDENCE_DIR=hackathon-evidence/static-run-001
python3 scripts/collect_hackathon_evidence.py \
  --profile static \
  --out "$STATIC_EVIDENCE_DIR"
python3 scripts/verify_evidence_manifest.py "$STATIC_EVIDENCE_DIR"

# Run with a Fireworks-configured backend reachable at BACKEND_BASE_URL.
export FIREWORKS_EVIDENCE_DIR=hackathon-evidence/fireworks-run-001
python3 scripts/collect_hackathon_evidence.py \
  --profile fireworks-auth \
  --out "$FIREWORKS_EVIDENCE_DIR"
python3 scripts/verify_evidence_manifest.py "$FIREWORKS_EVIDENCE_DIR"

# Capture identity from the real AMD runtime, then collect the AMD live bundle.
python3 scripts/capture_amd_runtime_evidence.py \
  --target docker-compose \
  --out /tmp/amd-runtime.json
export AMD_EVIDENCE_DIR=hackathon-evidence/amd-run-001
python3 scripts/collect_hackathon_evidence.py \
  --profile amd-gemma \
  --amd-runtime-evidence /tmp/amd-runtime.json \
  --out "$AMD_EVIDENCE_DIR"
python3 scripts/verify_evidence_manifest.py "$AMD_EVIDENCE_DIR"
python3 scripts/audit_hackathon_readiness.py "$AMD_EVIDENCE_DIR"
```

Use `--profile fireworks-auth`, `--profile amd-gemma`, or `--profile full` only
inside the credentialed/provider/GPU environment. Those profiles intentionally
fail if required secrets or live deployment evidence are missing. `--profile
full` additionally requires two simultaneously running provider-specific
backends and distinct settings:

```bash
export FIREWORKS_ALLOWED_MODELS=accounts/fireworks/models/kimi-k2p6
export AMD_VLLM_ALLOWED_MODELS=amd-gemma-3-27b-it
export FIREWORKS_BACKEND_BASE_URL=http://localhost:8000
export AMD_BACKEND_BASE_URL=http://localhost:8002
export FULL_EVIDENCE_DIR=hackathon-evidence/full-run-001
python3 scripts/collect_hackathon_evidence.py \
  --profile full \
  --amd-runtime-evidence /tmp/amd-runtime.json \
  --out "$FULL_EVIDENCE_DIR"
```

Run `audit_hackathon_readiness.py` over the evidence directory before recording
the pitch. It separates safe wording from claims that still need live Fireworks
or AMD hardware proof.

Do not claim AMD latency, throughput, or cost wins until the benchmark output
names the hardware, ROCm/vLLM versions, model, input shape, p50/p95 latency,
memory, and correctness/error data.

## Exact pitch wording

Use this:

> Govern.ai is Fireworks-authenticated and AMD-Gemma deployable. The
> same governed HR workflow can run in deterministic mode, with request-scoped
> Fireworks BYOK for live structured inference, or against a Gemma-family model
> hosted on AMD ROCm/vLLM. Model selection is allowlisted, outputs are certified,
> and sensitive outcomes remain human-reviewable and auditable.

Short submission tagline:

> AMD powered. Gemma powered. Fireworks powered.

Avoid this unless the evidence package proves it:

- “10x faster”
- “production compliant”
- “fully autonomous HR decisions”
- “AMD powered” as a live-hosting claim without naming the AMD GPU, ROCm/vLLM
  versions, and successful Gemma smoke run
