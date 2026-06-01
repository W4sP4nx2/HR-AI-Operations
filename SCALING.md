# Scaling to 1M+ Requests — Architecture, Gaps & Roadmap

This document reviews the current system against a **million+ requests** open-source
production target, records the **gaps found** (and the ones already fixed), gives the
**target architecture + scaling algorithms**, and returns a **data flow diagram**.

> TL;DR — the app is correct and demo-ready, but it is built around two
> single-node assumptions that break horizontally: **SQLite** as the system of
> record and an **in-process WebSocket list**. The path to 1M+ is: make the API
> tier stateless, move state to Postgres + Redis + a queue, and run agent work
> off the request path.

---

## 1. Review — gaps found

Grounded in the actual code, ordered by how hard they bite at scale.

| # | Gap | Where | Impact at 1M+ | Status |
|---|-----|-------|---------------|--------|
| G1 | **SQLite single-writer**, fresh connection per call, rollback journal | `core/memory.py:_connect` | Every audit write (1 per agent action) takes a global DB lock → serialised writes, "database is locked" under load | ✅ **Mitigated** (WAL + busy_timeout); ⏭ migrate to Postgres |
| G2 | **No indexes** — `audit ORDER BY timestamp`, `cases WHERE category/status` | `core/memory.py:_init_schema` | Every list read is full-scan + temp-sort; degrades linearly as audit hits millions of rows | ✅ **Fixed** (6 indexes added) |
| G3 | **In-process WebSocket registry** (`self._connections: list`) | `api/websocket_manager.py` | A broadcast only reaches clients on the *same* process; with N replicas the live feed silently drops events | ⏭ Redis Pub/Sub fan-out |
| G4 | **Agents run inline in the request** (LLM/CrewAI/RAG, multi-second) | `api/routes/agents.py` | Long calls hold a worker; a burst exhausts the pool and stalls the event loop | ⏭ task queue + worker pool |
| G5 | **Heavy models per-process** (embedder, attrition RF trained at startup) | `models/`, `core/embeddings.py` | Each replica loads its own copy → memory blow-up; cold-start latency; non-reproducible model | ⏭ model registry + serving |
| G6 | **No auth / rate limiting / quotas** | `api/main.py` | Open endpoints can't survive abuse or multi-tenant fairness | ⏭ API gateway |
| G7 | **No pagination** (hardcoded `LIMIT 200`, no cursor) | `core/memory.py` list_* | Can't page deep history; large responses | ⏭ keyset pagination |
| G8 | **No caching** — `/health` + `/agents` polled every 10s by every browser | `api/main.py`, fleet panel | DB hit per poll × every open tab | ⏭ Redis read-through cache |
| G9 | **`@app.on_event("startup")`** deprecated; CORS list hardcoded | `api/main.py` | Minor; lifespan + config | ⏭ lifespan + env config |
| G10 | **No idempotency** on triage/case creation | triage flow | Agent retries create duplicate cases | ⏭ content-hash dedupe key |

### Fixed in this pass (verified)
- **G1 — WAL mode + `busy_timeout=5000` + `synchronous=NORMAL`** on every connection.
  Readers no longer block on the single writer; contended writes wait-and-retry
  instead of erroring. (`EXPLAIN`/`PRAGMA` confirmed `journal_mode=wal`.)
- **G2 — six indexes** on `audit(timestamp)`, `audit(agent_name,timestamp)`,
  `cases(category)`, `cases(status)`, `cases(created_at)`, `agent_tasks(status)`.
  The hot audit query now plans as `SCAN audit USING INDEX idx_audit_timestamp`
  (was scan + temp B-tree sort). Test suite still green (6/6).

These two are the difference between "falls over at hundreds of concurrent writes"
and "comfortable single-node throughput" — and they model the production direction
(WAL→Postgres MVCC, SQLite indexes→Postgres indexes).

---

## 2. Target architecture (stateless tier + shared backing services)

The single rule that unlocks horizontal scale: **the API process must hold no
state**. Everything stateful moves to a backing service that all replicas share.

```
                         ┌──────────────── Clients (browser, Slack, API) ────────────────┐
                         │   Next.js dashboard · employee chat · partner integrations     │
                         └───────────────────────────────┬───────────────────────────────┘
                                                          │  HTTPS / WSS
                                              ┌───────────▼───────────┐
                                              │   API Gateway / LB     │  TLS, WAF, JWT/OIDC,
                                              │  (NGINX/Envoy/Cloud)   │  rate-limit, routing
                                              └───────────┬───────────┘
                       ┌──────────────────────────────────┼──────────────────────────────────┐
                       ▼                                   ▼                                   ▼
            ┌───────────────────┐               ┌───────────────────┐               ┌───────────────────┐
            │ FastAPI replica 1 │   …  (HPA) …   │ FastAPI replica N │               │  WS gateway pods  │
            │  stateless, async │               │  stateless, async │               │ (sticky sessions) │
            └─────────┬─────────┘               └─────────┬─────────┘               └─────────┬─────────┘
                      │ enqueue job                       │                                   │ sub/pub
                      ▼                                    ▼                                   ▼
            ┌───────────────────────── Redis ─────────────────────────┐         ┌──── Redis Pub/Sub ────┐
            │ cache · rate-limit buckets · idempotency keys · job q     │◄───────┤  live-feed fan-out     │
            └───────────────────────────┬─────────────────────────────┘         └────────────────────────┘
                                        │ dequeue
                      ┌─────────────────▼─────────────────┐
                      │      Agent worker pool (Celery/Arq) │  runs LLM/RAG/CrewAI off the request path
                      │   autoscaled on queue depth (KEDA)  │
                      └───┬───────────────┬──────────────┬──┘
                          ▼               ▼              ▼
              ┌────────────────┐ ┌────────────────┐ ┌──────────────────┐
              │ Postgres       │ │ Qdrant cluster │ │ Model registry / │
              │ primary + read │ │ (sharded HNSW) │ │ serving (MLflow, │
              │ replicas + PgB │ │ vector search  │ │ embeddings svc)  │
              └────────────────┘ └────────────────┘ └──────────────────┘
                          │
                          ▼
              ┌────────────────────┐        ┌──────────────────────────┐
              │ Object store (S3)  │        │ Observability:            │
              │ policy PDFs, model │        │ OTel · Prometheus/Grafana │
              │ artifacts, exports │        │ · LangSmith (LLM traces)  │
              └────────────────────┘        └──────────────────────────┘
```

### Component swaps from today
| Today (single node) | Production (1M+) | Why |
|---------------------|------------------|-----|
| SQLite file | **Postgres** (primary + read replicas, PgBouncer) | MVCC concurrent writes, read fan-out, HA |
| In-process WS list | **Redis Pub/Sub** + WS gateway pods | broadcasts reach every replica's clients |
| Inline agent calls | **Task queue + worker pool** (Celery/Arq) | keep p99 API latency flat under LLM latency |
| Per-process models | **Model registry + embedding service** | one warm copy, versioned, reproducible |
| Local Qdrant | **Qdrant cluster** (sharded, replicated) | vector search beyond one node's RAM |
| `.env` secrets | **Vault / K8s Secrets** + ConfigMap | rotation, least privilege |

---

## 3. Scaling algorithms & techniques

The architecture is the skeleton; these are the algorithms that make each hop cheap.

1. **Audit as append-only, time-partitioned log.** Monthly Postgres partitions +
   **BRIN index** on `timestamp` (tiny, ideal for monotonic inserts). Roll old
   partitions to cold storage / S3 (Parquet) for cheap retention. Writes are
   **buffered and batch-flushed** (e.g. 50ms / 500-row window) to absorb spikes —
   audit is the highest-volume write path (1 per agent action).

2. **WebSocket fan-out via Redis Pub/Sub.** Each WS gateway subscribes to a
   `feed` channel and pushes only to *its* local sockets. Broadcast cost is
   `O(local_connections)` per node, not `O(total)`. Sticky sessions (consistent
   hashing on connection id) keep a client pinned to one pod.

3. **Agent execution off the request path.** `POST /agents/{name}/trigger`
   enqueues a job and returns `202 + job_id`; the worker runs RAG/LLM/CrewAI and
   publishes the result to Redis → WS (or the client polls `GET /jobs/{id}`).
   Keeps API p99 independent of model latency. **Bounded queue + backpressure**:
   shed or 429 when depth exceeds budget rather than melting down.

4. **Semantic answer cache.** Cache Policy-Q&A answers keyed by the **query
   embedding** (cosine ≥ 0.97 ⇒ cache hit). Cuts repeat LLM+retrieval cost — the
   most expensive path — to a Redis lookup.

5. **Read-through cache for hot, low-cardinality reads** (`/agents`, `/health`)
   with a short TTL (1–2s) + jitter to avoid thundering herds. Collapses
   "every tab every 10s" into one DB read per TTL window.

6. **Token-bucket rate limiting in Redis**, per API key / per tenant — fair
   multi-tenant sharing and abuse protection at the gateway.

7. **Idempotency keys.** Hash `(tenant, ticket_text)` → dedupe so retried triage
   doesn't create duplicate cases. Store key→result in Redis with a TTL.

8. **Connection pooling** (PgBouncer, transaction mode) so thousands of API/worker
   coroutines multiplex onto a small, bounded set of Postgres connections.

9. **Vector search = HNSW** (Qdrant default): sub-linear ANN. **Shard by tenant**;
   replicate shards for read throughput and HA.

10. **Autoscaling signals.** HPA on CPU for the API tier; **KEDA on queue depth**
    for workers (the correct signal when work is async). Scale-to-zero for idle
    tenants.

---

## 4. Data flow diagrams

### 4a. Policy Q&A request (read path, cached + async)
```
Employee ──▶ Gateway ──▶ FastAPI ──▶ [Redis semantic cache?]
  "vacation days?"  (JWT,rate-limit)        │ hit ─────────────▶ answer (≈ms)
                                            │ miss
                                            ▼
                                   enqueue job (Redis queue) ──▶ 202 + job_id
                                            │
                                   Worker pool dequeues
                                            ▼
                       embed(query) ─▶ Qdrant top-k ─▶ Claude synthesise
                                            ▼
                       write audit (batched) ─▶ Postgres
                       cache answer ─▶ Redis (by query embedding)
                       publish result ─▶ Redis Pub/Sub ─▶ WS ─▶ Employee
```

### 4b. Triage + live feed (write path, multi-replica fan-out)
```
Ticket ──▶ Gateway ──▶ FastAPI replica A
                          │ idempotency check (Redis): seen hash? ─▶ return cached case
                          │ new
                          ▼
                 enqueue ──▶ Worker: classify (keyword/LLM)
                          ├─ URGENT  ─▶ create case(status=escalated, assignee=human)
                          ├─ POLICY  ─▶ RAG auto-resolve ─▶ case(status=resolved)
                          └─ other   ─▶ create case(status=open)
                          ▼
                 INSERT case + audit ─▶ Postgres (primary)
                          ▼
                 PUBLISH "case.created" ─▶ Redis Pub/Sub
                          ▼
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   WS pod 1          WS pod 2            WS pod 3      ← every dashboard updates live,
 (its clients)     (its clients)       (its clients)     regardless of which replica wrote
```

### 4c. Onboarding (human-in-the-loop, durable state)
```
Start ─▶ Worker: validate ─▶ create_accounts ─▶ assign_training
                                                      │
                                          persist paused TASK ─▶ Postgres (agent_tasks)
                                                      │
                                          PUBLISH "approval.pending" ─▶ WS ─▶ Approvals panel
                                                      │
                              ┌──── human decision (Gateway, authz) ────┐
                              ▼                                          ▼
                    APPROVE: load state ─▶ resume                REJECT: load state ─▶
                    send_welcome ─▶ notify_manager               return to agent w/ reason
                              ▼                                          ▼
                    UPDATE task=approved + audit            UPDATE task=rejected + audit
                              ▼
                    PUBLISH "approval.resolved" ─▶ WS
```

---

## 5. Further feature improvements

### Product / platform features
- **Multi-tenancy** — tenant id on every row, row-level security in Postgres,
  per-tenant Qdrant shards, per-tenant quotas. Table stakes for open-source SaaS.
- **Pluggable connector framework** — `connectors/base.py` interface with
  Workday / ServiceNow / Slack / Okta adapters (mock-first, see IMPLEMENTATION.md §6).
- **Policy library manager** — versioned PDF upload, ingest API, citation by doc
  version (compliance-grade).
- **Bulk operations** — batch resume screening, bulk attrition scoring as queued jobs.
- **Configurable triage rules** — tenant-defined routing without a deploy.
- **Webhooks & public API** — let external systems subscribe to case/approval events.
- **RBAC** — admin / analyst / read-only roles; SSO (OIDC).
- **i18n** — multilingual policy Q&A over one English corpus.

### ML / agent quality
- **RAG re-ranking** (cross-encoder) + **citation offsets** for UI highlighting.
- **Eval harness** — LangSmith datasets + offline regression on RAG/triage accuracy
  gating CI.
- **Attrition lifecycle** — CSV/Workday-sourced training, scheduled retrain, model
  registry, drift monitoring, fairness checks.
- **Guardrails** — PII redaction in audit, prompt-injection defenses, output
  validation on LLM responses.

### Backends to add
| Backend | Role |
|---------|------|
| **PostgreSQL** (+ read replicas, PgBouncer) | system of record (replaces SQLite) |
| **Redis** | cache · rate-limit · idempotency · Pub/Sub · job broker |
| **Celery / Arq** workers | async agent execution |
| **Qdrant cluster** | sharded vector search |
| **S3 / MinIO** | policy PDFs, model artifacts, audit cold storage, CSV exports |
| **MLflow** (or similar) | model registry + versioning |
| **OpenTelemetry + Prometheus/Grafana** | metrics, traces, dashboards, alerts |
| **LangSmith** | LLM/agent run observability + evals |
| **Vault / KMS** | secret storage + rotation |
| **Kafka** *(optional, very high volume)* | durable event bus if Redis Pub/Sub is outgrown |

---

## 6. Rollout order (incremental, each step independently shippable)
1. ✅ **Postgres migration** (SQLAlchemy async + asyncpg) behind the existing
   `Memory` interface — **DONE**. The data layer is now dialect-agnostic async
   SQLAlchemy Core; the store is chosen by `DATABASE_URL` alone (SQLite for dev,
   Postgres for prod), with no change to any agent or route. Verified end-to-end
   against **both** SQLite and a live Postgres 16 container. See §7.
2. **Redis** + read-through cache for `/agents`, `/health` + token-bucket limiter.
3. **Task queue + workers** — move agent execution async; `/trigger` returns a job id.
4. **Redis Pub/Sub WebSocket fan-out** — make the live feed multi-replica safe.
5. **Auth (OIDC) + multi-tenancy** — tenant scoping + RBAC.
6. **Observability** — OTel traces, Prometheus metrics, LangSmith for LLM runs.
7. **K8s + autoscaling** — HPA (API) + KEDA (workers); Qdrant StatefulSet; see
   [IMPLEMENTATION.md](./IMPLEMENTATION.md) §3.

The `Memory` abstraction, the response envelope, the agent fallbacks, and the
WebSocket boundary mean every step above is **additive** — the app keeps working
at each stage, which is exactly what an open-source project needs so contributors
can run it on a laptop while operators run it at scale.

---

## 7. Step 1 — Postgres migration (shipped)

The data layer (`core/memory.py`) is now **async SQLAlchemy Core**, dialect-agnostic
across SQLite and PostgreSQL. The public method surface is unchanged, so all five
agents and every route are untouched.

**Switching backends is a single env var** — no code change:
```bash
# local dev (default) — SQLite via aiosqlite
DATABASE_URL=sqlite:///./hr_command_center.db

# production — PostgreSQL via asyncpg (driver suffix added automatically)
DATABASE_URL=postgresql://user:pass@db-host:5432/hrdb
```

**What it does**
- Picks the async driver automatically (`+aiosqlite` / `+asyncpg`); a bare path is
  treated as a SQLite file.
- SQLite: `NullPool` + per-connection **WAL / `synchronous=NORMAL` / `busy_timeout`**
  (concurrent readers, retry-on-contend). Postgres: default async pool — front it
  with **PgBouncer** in production.
- Schema + the six indexes (§1 G2) are created on first use via `metadata.create_all`
  on whichever dialect is configured.

**Verification (both backends, identical code path):**
- `pytest tests/` → **6/6 pass** on the async layer.
- Async smoke test (audit · cases · agents · tasks · WAL) → all assertions pass on
  **SQLite**.
- Same smoke test against a live **Postgres 16** container (asyncpg, `||` concat,
  `create_all` DDL) → all assertions pass.
- Live server boot + `triage → case + audit` round-trip on the new layer → OK.

New deps: `sqlalchemy[asyncio]>=2.0`, `aiosqlite`, `asyncpg` (in `requirements.txt`).

**Next:** add a Postgres service to `docker-compose` (profile-gated so the default
dev stack stays SQLite-only), then proceed to step 2 (Redis cache + rate limiting).
