# Runbook — validate the prod stack & pgvector (copy-paste)

> **Run everything from the repo root `hr-command-center/`** (not its parent).
> Paste blocks **without the `#` comment lines** if your zsh isn't set to
> `setopt interactive_comments` — comments and `\` line-continuations are the
> reason the earlier paste errored.

## 0. Get into the right directory
```bash
cd /Users/lwinnaingkyaw/Documents/Claude/Projects/Project\ Mario/hr-command-center
```

## 1. Bring up the prod stack (single datastore: Postgres + pgvector)
```bash
export JWT_SECRET="$(openssl rand -hex 32)"
export ADMIN_EMAIL=admin@acme.com ADMIN_PASSWORD='a-strong-password'
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml ps
```
- App: backend http://localhost:8000/health · frontend http://localhost:3000
- Postgres is published on `localhost:5432` (user `hr`, db `hrdb`, password
  `hr_dev_password` unless you set `POSTGRES_PASSWORD`).

## 2. Seed 10 policies + embed into pgvector (inside the container)
```bash
docker compose -f docker-compose.prod.yml exec backend python -m scripts.seed_data
docker compose -f docker-compose.prod.yml exec backend python -m scripts.embed_policies
```
You should now see `→ N vectors` per policy (not "registry only").

## 3. pgvector round-trip test (from the host venv — has pytest)
```bash
cd backend && source .venv/bin/activate
RAG_TEST_DSN="postgresql://hr:hr_dev_password@localhost:5432/hrdb" \
  pytest tests/test_rag.py::test_pgvector_roundtrip_integration -v
cd ..
```
> The DSN uses `hr:hr_dev_password` (the compose creds) — **not** `postgres:password`.
> The prod image is lean (no pytest), so run the test from the **host venv**, not
> `docker compose exec`.

## 4. Load test the RAG chat path (Locust)
```bash
cd backend && source .venv/bin/activate
pip install locust
locust -f tests/load/locustfile.py --headless -u 50 -r 5 --run-time 60s \
       --host http://localhost:8000
cd ..
```
Targets: retrieval < 100 ms, full chat response < 3 s p95. Paste the summary table
into the README. Compare `ENABLE_RAG=true` vs `false` to isolate retrieval cost.

## 5. Fast local demo (no Docker, zero spend)
```bash
cd backend && source .venv/bin/activate
AUTH_ENFORCE=false MOCK_LLM=true ENABLE_RAG=true uvicorn api.main:app --port 8000
```

## 6. Local product inspection gate

Use this gate before any demo or review. It proves the product is usable without
secrets and that live-provider claims remain visibly gated.

```bash
make preview
```

Open `http://127.0.0.1:3001`.

Checklist:

- **Chat**: ask `How many PTO days do I get under the current policy?`; the
  seeded active 2024 policy should answer `25 days` with citation chips.
- **Analytics → Dynamic Capability Engine**: deterministic fallback should show
  `measured_local`; Fireworks and AMD/Gemma should show `live_gated` until
  credentials/runtime evidence are injected.
- **Analytics → Token Cost & Serverless Usage**: local estimate should show
  provider calls, token totals, tier spend, budget circuit breaker state, and
  Fireworks serverless attribution tags. In zero-secret preview it must say
  local estimate, not provider billing.
- **AI settings**: context caps, policy timeout, retrieval top-k, and cache TTL
  must be visible.
- **Integrations**: A2A should be proven locally, CrewAI configured, and
  LangSmith not configured unless tracing env is injected.

## 7. Live integration evidence gates

Run these only from an approved environment with real credentials. These
commands are intentionally separate from the local preview so a failed external
dependency does not masquerade as a product regression.

### Fireworks Serverless

```bash
cd backend
export LLM_PROVIDER=fireworks
export FIREWORKS_API_KEY=...
export FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
export ALLOWED_MODELS=accounts/fireworks/models/<approved-model-id>
export FIREWORKS_ACCOUNT_ID=...          # required for account billing export
python3 -m scripts.verify_hackathon_env --mode fireworks-auth --json
python3 -m scripts.fireworks_smoke --enable-cost-tracking
python3 -m scripts.byok_smoke --provider fireworks --json
```

Pass evidence:

- `/health` reports `llm_provider=fireworks`, `llm_enabled=true`, no config
  issues.
- Analytics token/serverless panel moves from local estimate to live observed
  provider-call evidence after a model-backed workflow.
- Fireworks account billing remains a separate export surface; use the
  Fireworks billing-usage API or `firectl billing get-usage` for rated account
  totals.

### AMD-hosted Gemma through vLLM

```bash
cd backend
export LLM_PROVIDER=amd_vllm
export AMD_VLLM_MODEL=google/gemma-3-27b-it
export AMD_VLLM_SERVED_MODEL=amd-gemma-3-27b-it
export AMD_VLLM_API_KEY=...
export AMD_VLLM_BASE_URL=http://<amd-vllm-host>:8000/v1
export ALLOWED_MODELS=$AMD_VLLM_SERVED_MODEL
export AUTH_ENFORCE=true
export AUTH_OPEN_REGISTRATION=false
export JWT_SECRET=<long-random-secret>
export ADMIN_EMAIL=admin@example.com
export ADMIN_PASSWORD=<strong-password>
export DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/<db>
python3 -m scripts.verify_hackathon_env --mode amd-gemma --json
python3 -m scripts.amd_vllm_smoke --json
python3 scripts/capture_amd_runtime_evidence.py --target kubernetes --out /tmp/amd-runtime.json
python3 scripts/verify_amd_runtime_evidence.py /tmp/amd-runtime.json
```

Pass evidence:

- `/v1/models` exposes the Gemma-family served model.
- `/health` shows the AMD route active and browser BYOK disabled.
- Runtime evidence includes named AMD GPU, ROCm/vLLM versions, and a successful
  smoke response. Do not publish latency or throughput claims without benchmark
  artifacts.

### A2A + CrewAI + LangSmith

```bash
cd backend
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=...             # or LANGSMITH_API_KEY
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  tests/test_a2a_envelope.py \
  tests/test_orchestrator.py \
  tests/test_crewai_cost_tracker.py \
  tests/test_zero_spend_cost_certification.py -q
```

Pass evidence:

- Settings → Integrations shows A2A proven, CrewAI configured, and LangSmith
  configured only when tracing and key are both present.
- Certified A2A envelopes include schema, latency, cost metadata, and redaction
  evidence before handoff.

### Live ETL integration

```bash
cd backend
export DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/<db>
export S3_ENDPOINT_URL=http://<minio-or-s3-host>:9000
export S3_BUCKET=hrcc-synthetic-resumes
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1
python3 -m scripts.certify_etl_integrations --out ../hackathon-evidence/live-etl.json
```

Pass evidence:

- pgvector is the active RAG backend and the poisoned PTO policy test selects
  `policy_pto_2024`.
- object storage lists exactly the planned synthetic resume objects.
- the output artifact contains sanitized evidence only; no credentials.

## 8. Ship it
```bash
cd /Users/lwinnaingkyaw/Documents/Claude/Projects/Project\ Mario/hr-command-center
ruff check backend && black --check backend \
  && (cd backend && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q) \
  && (cd frontend && npm run build)
git add -A && git commit -m "RAG on pgvector (single datastore) + load test + compliance gate"
git push                 # → GitHub Actions runs lint · test · compliance · build · secret-scan
```
Then watch the **Actions** tab go green (the `build` job is gated on
`lint`, `test`, and `compliance`).

---

### Common gotchas (what bit you)
- **`no such file or directory ... docker-compose.prod.yml`** → you were in
  `Project Mario/`; `cd hr-command-center` first.
- **`ERROR: file or directory not found: backend/tests/test_rag.py`** → same; the
  path is correct *from `hr-command-center/`*.
- **`zsh: command not found: #` / `unknown file attribute: i`** → zsh tried to run
  the `#` comment lines / glob the `[i]`. Run `setopt interactive_comments` once,
  or paste the commands without the comment lines.
- **round-trip test can't connect** → use the `hr:hr_dev_password@localhost:5432`
  DSN, and make sure step 1 is up (`docker compose ... ps` shows `db` healthy).
