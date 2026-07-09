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

## 6. Ship it
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
