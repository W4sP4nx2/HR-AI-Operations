# Operations Manual — HR AI Command Center

For **administrators, DevOps/SRE, and IT** who deploy, integrate, secure and run
the system in an HR or financial enterprise. End-user guidance is in the
[User Manual](./USER_MANUAL.md); architecture and scaling in
[SCALING.md](./SCALING.md); roadmap in [IMPLEMENTATION.md](./IMPLEMENTATION.md).

---

## 1. System overview

- **Backend** — FastAPI (async), 5 agents, RAG pipeline, audit/case/approval store.
- **Frontend** — Next.js 16 dashboard.
- **State** — async SQLAlchemy: **SQLite** for dev, **PostgreSQL** for production
  (chosen by `DATABASE_URL`, no code change).
- **Vector search** — Postgres + pgvector HNSW in production; local and Qdrant
  adapters are optional.
- **Inference** — deterministic fallback, Fireworks online/Batch, or an
  environment-injected AMD/vLLM endpoint.

The guiding principle is **graceful degradation**: the control plane, audit,
approvals and UI always work; AI depth is additive. Nothing fails closed — when a
capability is missing the system reports `unavailable`, never silently drops work.

---

## 2. Install & run

### Local (no Docker)
```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # no secrets required for fallback mode
uvicorn api.main:app --reload --port 8000

# Frontend
cd frontend && npm install
cp .env.local.example .env.local
npm run dev                     # http://localhost:3000
```

### Docker (full stack)
```bash
docker compose up --build
# Dashboard :3000 · API :8000/docs · Postgres/pgvector :5432
```
The compose stack has healthchecks and ordered startup (frontend waits for a
healthy backend, backend waits for Postgres).

---

## 3. Configuration (environment variables)

All settings load from the environment / `.env` via `pydantic-settings`
(`backend/core/config.py`). No secrets are hardcoded.

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `fireworks` | Live provider: `fireworks`, `anthropic`, or `amd_vllm`. |
| `FIREWORKS_API_KEY` | — | Fireworks key. Absent means deterministic fallback mode. |
| `FIREWORKS_BASE_URL` | — | Injected Fireworks OpenAI-compatible base URL. |
| `ALLOWED_MODELS` | — | Comma-separated model allow-list. |
| `DATABASE_URL` | `sqlite:///./hr_command_center.db` | `sqlite:///…` (dev) or `postgresql://…` (prod). |
| `VECTOR_BACKEND` | auto | `pgvector`, `local`, or explicitly pinned `qdrant`. |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model (falls back to a hashing embedding if not installed). |
| `WEBHOOK_SECRET` | — | Shared secret required on inbound webhooks (see §6). |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed dashboard origins. |
| `ENVIRONMENT` | `development` | Deployment environment label. |

**Switch to Postgres** — set only:
```bash
DATABASE_URL=postgresql://user:pass@db-host:5432/hrdb
```
The async driver (`asyncpg`) is selected automatically; schema + indexes are
created on first start.

---

## 4. How input enters the system

There are **three intake paths**, all normalised by `pipelines/intake.py` into
plain text before an agent runs. Each returns the status envelope
(`ok` / `error` / `unavailable`) plus an `intake` summary (`source_type`,
`source_ref`, `chars`, `truncated`). Text is capped at 20,000 chars.

### 4a. Manual trigger — JSON
```bash
curl -X POST http://localhost:8000/agents/triage_agent/trigger \
  -H 'Content-Type: application/json' \
  -d '{"input":"payroll fails today, urgent"}'
```

### 4b. Manual trigger — file / URL / text (multipart)
```bash
# PDF attachment (e.g. a resume) against a JD
curl -X POST http://localhost:8000/agents/resume_screener_agent/trigger/upload \
  -F 'file=@resume.pdf' -F 'job_description=Senior Python engineer, FastAPI'

# Scrape a URL for its readable text
curl -X POST http://localhost:8000/agents/policy_qa_agent/trigger/upload \
  -F 'url=https://intranet.example.com/leave-policy'

# Plain text
curl -X POST http://localhost:8000/agents/triage_agent/trigger/upload \
  -F 'text=I cannot access the benefits portal'
```

### 4c. Inbound webhook (external systems)
See §6.

---

## 5. The status contract (success / fail / unavailable)

Every trigger response carries a machine-readable `status` the UI button maps to:

| `status` | `success` | Meaning | Operator action |
|----------|-----------|---------|-----------------|
| `ok` | `true` | Ran and produced a result. | — |
| `error` | `false` | Attempted but failed: bad input, unreadable PDF, wrong URL scheme, unknown agent. | Surface the `error` message to the user. |
| `unavailable` | `false` | A capability/dependency is missing or unreachable: scraper libs absent, URL fetch failed, vector DB down. The `data.capability` names it. | Enable the capability or check the dependency. |

Successful results also include `_mode: "degraded" | "full"` — `degraded` means
no active provider, so answers use deterministic fallbacks.

> **Monitoring tip:** alert on a rising rate of `unavailable` — it usually means a
> dependency (Postgres/vector search, scraper egress, provider quota) needs attention, distinct from
> user `error`s.

---

## 6. Webhooks & scrapers (integrations)

### Inbound webhooks
External systems (ATS, ticketing/helpdesk, HRIS, web forms) POST JSON to
`/webhooks/{source}`; the payload is normalised to text and routed to an agent.

```bash
curl -X POST http://localhost:8000/webhooks/ticketing \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: <WEBHOOK_SECRET>' \
  -d '{"subject":"Cannot enroll in benefits","body":"need help choosing a plan"}'
```

- **Source routing** (default agent per source): `ticketing`/`helpdesk`/`form` →
  Triage · `ats` → Resume Screener · `policy` → Policy Q&A · unknown → Triage.
- **Override** the agent per call with `"target_agent": "<agent_name>"`.
- **Text discovery** scans `text`, `message`, `body`, `description`, `summary`,
  `content`, `subject` (subject + body combined when both present).
- **A `url` field** in the payload triggers the scraper instead of text.

### Security
- Set **`WEBHOOK_SECRET`**; callers must send it in the `X-Webhook-Secret` header.
  With no secret set (dev), verification is skipped.
- **Production hardening (recommended):** replace the shared secret with per-source
  **HMAC signature** verification (`_verify_signature` in
  `api/routes/webhooks.py` is the hook), put the endpoint behind the API gateway,
  and rate-limit per source.

### Scrapers
URL intake uses `httpx` + BeautifulSoup, stripping scripts/styles. Only `http(s)`
is allowed; fetch failures return `unavailable` (not `error`). For production:
restrict egress (allowlist domains), set timeouts (default 10s), and consider a
queue so a slow page never blocks a request worker (see SCALING.md step 3).

---

## 7. Loading policy documents (RAG)

Policy Q&A and POLICY-class triage answer from documents you ingest into Qdrant.

```python
# from the backend venv
from pipelines.rag_pipeline import rag_pipeline
rag_pipeline.ingest_directory("./policies")     # all PDFs in a folder
# or a single file:
rag_pipeline.ingest_pdf("./policies/leave-policy.pdf")
```
Chunking is 512 tokens / 50 overlap; retrieval is cosine top-k = 5. Without Qdrant
running, retrieval returns empty and answers say "No relevant policy found" rather
than erroring. **Re-ingest** whenever policies change so citations stay current.

---

## 8. Audit, retention & compliance

- Every agent action writes an immutable row: agent, action, input, output,
  status, timestamp. Exposed at `GET /audit` and `GET /audit/export` (CSV).
- **Retention:** in production (Postgres) partition the audit table by month and
  archive old partitions to object storage (SCALING.md §3). Define a retention
  window with your compliance team.
- **Access control:** the audit/export endpoints should sit behind auth + RBAC
  before exposure to finance/compliance users (roadmap; see §11).
- **PII:** review what input text is stored; add redaction at ingest if policies
  require it (roadmap guardrail).

---

## 9. Operating the stack

### Health & readiness
- `GET /health` → `{status, environment, agents_registered, agents_active}`.
  Use it for load-balancer health checks and k8s liveness/readiness probes.
- Containers ship with healthchecks; `docker compose ps` shows health.

### Logs & live feed
- Backend logs to stdout (uvicorn). The dashboard's live updates come over the
  WebSocket `/ws/feed`.
- **Scale-out caveat:** the WebSocket registry is currently per-process. Behind
  multiple replicas, use the Redis Pub/Sub fan-out (SCALING.md G3) so live events
  reach all clients. For a single backend instance this is not an issue.

### Backups
- **SQLite (dev):** back up the `.db` file (WAL is enabled).
- **Postgres (prod):** standard `pg_dump` / PITR; back up Qdrant storage volume too.

---

## 10. Troubleshooting

| Symptom | Cause | Resolution |
|---------|-------|-----------|
| Dashboard shows **System Offline** | Backend down or CORS blocked | Check `/health`; confirm `CORS_ORIGINS` includes the dashboard origin. |
| Triggers return **unavailable: scrape** | `httpx`/`beautifulsoup4` missing or egress blocked | `pip install -r requirements.txt`; allow outbound to the target. |
| Answers always "degraded" / no AI text | Fireworks key/base URL/model allow-list incomplete | Check `/health.llm_config_issues`, set the missing values, restart, and verify quota. |
| "No relevant policy found" | No documents ingested / Qdrant down | Ingest policies (§7); check `QDRANT_URL`. |
| `database is locked` (SQLite) | High write concurrency on SQLite | Move to Postgres (`DATABASE_URL`); WAL+busy-timeout already mitigate. |
| Webhook returns **signature verification failed** | Wrong/missing `X-Webhook-Secret` | Send the configured `WEBHOOK_SECRET`. |
| PDF upload **error: no extractable text** | Scanned/image-only PDF | Use a text PDF or add OCR (roadmap). |

---

## 11. Production checklist

- [ ] `DATABASE_URL` → PostgreSQL (+ PgBouncer); back up DB and Qdrant.
- [ ] Put API behind a gateway with **TLS, auth (OIDC/JWT), rate limiting, WAF**.
- [ ] Set `WEBHOOK_SECRET` (or HMAC) and restrict scraper egress.
- [ ] Lock `CORS_ORIGINS` to your real dashboard domain(s).
- [ ] Add **Redis** for caching + WebSocket fan-out across replicas.
- [ ] Move agent execution to a **task queue** (keeps API latency flat under LLM calls).
- [ ] Wire **observability** (OTel, Prometheus/Grafana, LangSmith for LLM runs).
- [ ] Define **audit retention** + partitioning with compliance.
- [ ] CI green (`ruff`, `black`, `pytest`) before deploy; build & push images.

See [SCALING.md](./SCALING.md) for the full architecture, algorithms, and the
incremental rollout order.
