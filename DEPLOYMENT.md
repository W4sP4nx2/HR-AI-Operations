# Deployment & Packaging

Three ways to run, from laptop to zero-touch cloud. All images are multi-stage,
non-root, and health-checked.

## Artifacts

| File | Purpose |
|------|---------|
| `backend/Dockerfile` | Dev backend image (used by `docker-compose.yml`) |
| `backend/Dockerfile.prod` | **Prod** backend: multi-stage, non-root, healthcheck, **lean deps** |
| `backend/requirements.txt` | Full dev stack (incl. torch/CrewAI/LangGraph) |
| `backend/requirements-prod.txt` | **Lean runtime** — deployable on small/free tiers |
| `frontend/Dockerfile.prod` | **Prod** frontend: Next.js standalone, non-root, tiny runtime |
| `docker-compose.yml` | Dev stack (SQLite, hot reload) |
| `docker-compose.prod.yml` | **Prod** stack: Postgres + Qdrant + prod images + restart policies |
| `docker-compose.amd.yml` | **AMD overlay**: pinned ROCm/vLLM image for gfx94X/MI300X |
| `render.yaml` | One-click cloud deploy (Render Blueprint) |
| `.github/workflows/ci.yml` | CI gate: lint · test · build · secret-scan |

## Fireworks submission mode
For judged AMD/Fireworks runs, do not add a real default host or model id to the
repo. The harness or secret manager must inject:

```bash
export LLM_PROVIDER=fireworks
export FIREWORKS_API_KEY=...
export FIREWORKS_BASE_URL=...       # intentionally no repo default
export ALLOWED_MODELS=model-a,model-b
```

`/health` reports `llm_provider`, `llm_enabled`, and `llm_config_issues` so a
missing env var is visible immediately. `MOCK_LLM=true` does not disable
Fireworks when the required harness env is complete.

Before recording or submitting, run one live smoke test from `backend/`:

```bash
python -m scripts.fireworks_smoke
```

If `EMBEDDING_PROVIDER=fireworks`, the same smoke test also verifies that the
embedding endpoint returns a non-empty vector and prints its probed dimension.

No-key contract and Batch dataset preparation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  -p pytest_asyncio.plugin tests/test_fireworks_workloads.py -q
ALLOWED_MODELS=model-a python -m scripts.fireworks_prepare_batch \
  input.json output.jsonl --model model-a
```

See [FIREWORKS_AI.md](./FIREWORKS_AI.md) for the workload router, structured
output/vision contracts, autoscaling behavior, and fine-tuning gate.

## Image architecture requirement
The judging VM pulls on `linux/amd64`. If you build on Apple Silicon, force the
target platform on the submitted images:

```bash
docker buildx build --platform linux/amd64 \
  -f backend/Dockerfile.prod \
  -t "$REGISTRY/hr-command-center-backend:$TAG" \
  --push backend

docker buildx build --platform linux/amd64 \
  -f frontend/Dockerfile.prod \
  -t "$REGISTRY/hr-command-center-frontend:$TAG" \
  --push frontend
```

Verify the pushed manifest before submitting:

```bash
python scripts/verify_image_platform.py "$REGISTRY/hr-command-center-backend:$TAG" \
  --platform linux/amd64
python scripts/verify_image_platform.py "$REGISTRY/hr-command-center-frontend:$TAG" \
  --platform linux/amd64
```

## 1. Local dev (zero secrets)
```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && python -m scripts.seed_data
uvicorn api.main:app --reload --port 8000
cd ../frontend && npm install && npm run dev
```

## 2. Production stack (Docker Compose)
```bash
export JWT_SECRET="$(openssl rand -hex 32)"     # required
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"
export LLM_PROVIDER=fireworks                   # optional live provider
export FIREWORKS_API_KEY=...
export FIREWORKS_BASE_URL=...
export ALLOWED_MODELS=model-a,model-b
export ADMIN_EMAIL=you@org.com ADMIN_PASSWORD='a-strong-password'
docker compose -f docker-compose.prod.yml up --build -d
```
- Postgres + Qdrant come up first (health-gated); the backend waits for both.
- `AUTH_ENFORCE=true` and the admin account is created on boot from `ADMIN_*`.
- Backend `:8000`, frontend `:3000`. Put a TLS-terminating reverse proxy in front.

## 3. Zero-touch cloud (Render Blueprint)
1. Push to GitHub (CI must be green — see the gate below).
2. Render → **New + → Blueprint** → select the repo (`render.yaml`).
3. Render provisions Postgres, **auto-generates `JWT_SECRET`**, and deploys both
   services. Set `LLM_PROVIDER`, provider secrets, `ADMIN_*`, `CORS_ORIGINS`, and
   the frontend's `NEXT_PUBLIC_API_BASE`/`NEXT_PUBLIC_WS_URL` in the dashboard,
   then redeploy.

> The same blueprint pattern maps to Fly.io / Railway — point them at
> `*/Dockerfile.prod`.

## AMD ROCm inference overlay

The AMD path uses a pre-built image from AMD's verified `rocm/vllm` repository.
It does not build ROCm, PyTorch, or vLLM on the demo host. The host still needs a
compatible AMD kernel driver and access to `/dev/kfd` and `/dev/dri`.

```bash
export AMD_VLLM_MODEL=<model path or registry id>
export AMD_VLLM_SERVED_MODEL=<served name>
export AMD_VLLM_API_KEY="$(openssl rand -hex 24)"
export AMD_VLLM_BASE_URL=http://amd-vllm:8000/v1
export ALLOWED_MODELS="$AMD_VLLM_SERVED_MODEL"

docker compose -f docker-compose.prod.yml -f docker-compose.amd.yml \
  --profile amd up -d
```

The overlay is explicit about `linux/amd64`, mounts the AMD device nodes, gives
vLLM a model cache and shared memory, and health-gates the application backend.
Override `AMD_VLLM_IMAGE` only with another reviewed, pinned ROCm image.

AMD's current inference guide recommends pre-built ROCm-enabled vLLM containers:
[ROCm vLLM inference](https://rocm.docs.amd.com/en/latest/how-to/rocm-for-ai/inference/benchmark-docker/vllm.html).
The pinned repository used here is published by
[AMD's verified `rocm` organization](https://hub.docker.com/r/rocm/vllm/tags).

## Demo scaling without a cluster

Docker Compose remains the default demo path. To show a scaling decision without
claiming that a Kubernetes cluster or live metric adapter exists, run:

```bash
cd backend
python -m scripts.simulate_scaling \
  --current-replicas 1 \
  --queue-depth 25 \
  --p95-ms 2400 \
  --gpu-utilization 94
```

The JSON output always includes `"simulated": true` and says that its inputs are
operator-supplied projections. It must not be exported as live Prometheus
telemetry. Use the optional manifests under `deploy/` on EKS, GKE, or another
managed cluster only when a real cluster is provisioned.

## The CI → deploy gate
`git push` → **CI** (`ruff`, `black`, `pytest`, frontend `build`, `gitleaks`) must
pass → merge to `main` → platform auto-deploys the built images. **Failures block
the merge; deploys are deterministic** (pinned Dockerfiles, no `latest` app code).

## Lean vs full image (why the prod image is small)

The full `requirements.txt` pulls **torch** (via sentence-transformers), **CrewAI**
and **LangGraph** — multi-GB, too heavy for free tiers. Because every heavy import
is **lazy** and the app **degrades gracefully**, the prod image installs
`requirements-prod.txt` (no torch/CrewAI/LangGraph) and still:
- triages (keyword classifier), screens resumes (hashing embedding + blinding),
  scores attrition (scikit-learn), and answers policy/chat via the configured
  Pydantic AI provider when live LLM env is set.

For full semantic RAG + CrewAI/LangGraph orchestration, build with the dev
`requirements.txt` instead. **Entry point** (both): `uvicorn api.main:app` (the
`CMD` in `Dockerfile.prod`). Verified: the lean runtime boots and runs all agents
in fallback mode with the heavy deps absent.

## Scaling note (honest)
The production image runs **one backend worker** so the in-process WebSocket live
feed stays correct. Horizontal scale (multiple workers/replicas) needs **Redis
Pub/Sub fan-out** for the feed plus a task queue for agent work — the documented
next step in [SCALING.md](./SCALING.md). For a single-instance showcase/deploy this
is the right default; don't add Redis/K8s until a real workload demands it.

## Production checklist
See [SECURITY.md](./SECURITY.md) — strong `JWT_SECRET`, `AUTH_ENFORCE=true`,
`WEBHOOK_SECRET` (HMAC), locked `CORS_ORIGINS`, Postgres backups, secret scanning.
