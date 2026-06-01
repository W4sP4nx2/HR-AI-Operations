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
| `render.yaml` | One-click cloud deploy (Render Blueprint) |
| `.github/workflows/ci.yml` | CI gate: lint · test · build · secret-scan |

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
export ANTHROPIC_API_KEY=sk-ant-...             # optional
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
   services. Set `ANTHROPIC_API_KEY`, `ADMIN_*`, `CORS_ORIGINS`, and the frontend's
   `NEXT_PUBLIC_API_BASE`/`NEXT_PUBLIC_WS_URL` in the dashboard, then redeploy.

> The same blueprint pattern maps to Fly.io / Railway — point them at
> `*/Dockerfile.prod`.

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
  scores attrition (scikit-learn), and answers policy/chat via the Anthropic SDK
  when `ANTHROPIC_API_KEY` is set.

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
