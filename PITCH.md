# Pitch Readiness — Features, Agents & What's Needed

Companion to [IMPLEMENTATION.md](./IMPLEMENTATION.md) (engineering) and
[SCALING.md](./SCALING.md) (architecture). This is the **stakeholder/investor**
view: what's demoable today, the features and agents that make it pitch-ready, and
a precise list of **what I need (Anthropic API + other services)** to get there.

---

## 1. The pitch

> **An AI command center for HR & people operations.** A team of specialised
> agents triage tickets, answer policy questions from your own documents, screen
> resumes, orchestrate onboarding, and flag attrition risk — every action audited,
> every sensitive step human-approved. It ingests work from **typed text, PDF
> attachments, scraped links, and inbound webhooks** from the tools you already
> use, and runs end-to-end on a laptop with **zero secrets** thanks to
> deterministic fallbacks.

**Demoable right now** (no API key, no cloud):
- Trigger any agent from text / PDF / URL and see a Success/Failed/Unavailable
  result with an "what was passed in" summary.
- Live case feed, human-in-the-loop approvals, audit trail + CSV export.
- Webhook ingestion from a simulated ATS / ticketing system.
- One env var flips the store from SQLite to PostgreSQL.

---

## 2. Pitch-ready feature roadmap

Ordered for maximum demo impact per unit of effort.

### Tier 1 — "wow" in a live demo (near-term)
- ✅ **Case detail drawer** *(shipped)* — click a case to see the full ticket and
  its chronological audit activity trail in a slide-over. Next: add the agent's
  reasoning and retrieved policy citations inline.
- **Conversational Policy Q&A** — a chat surface (and Slack/Teams bot) where
  employees ask questions; answers are RAG-grounded and audited.
- **Bulk resume screening** — drop a folder of PDFs against one JD → ranked,
  exportable shortlist with matched/missing skills.
- **Live "intake" visibility** — show, per trigger, exactly what text/file/URL the
  system received and how it was routed (already wired; surface it prominently).

### Tier 2 — enterprise credibility
- **Policy library manager** — upload/version/retire policy PDFs from the UI;
  answers cite the exact document version (compliance-grade traceability).
- **Configurable triage rules** — HR-defined routing & escalation without a deploy.
- **Role-based access (OIDC/SSO)** — admin / analyst / read-only; gate audit export.
- **Multi-tenancy** — per-tenant data isolation, quotas, and dashboards.
- **Compliance dashboard** — every automated decision, its input, and who approved
  it, exportable on demand (SOC2/GDPR-style).

### Tier 3 — moat
- **Connector marketplace** — Workday / ServiceNow / Okta / Slack adapters behind a
  stable interface (mock-first, real creds optional).
- **Eval & quality harness** — LangSmith datasets + offline regression gating CI so
  agent accuracy is measured, not asserted.
- **Multilingual** policy Q&A over one English corpus.

---

## 3. New agent implementations (expand the fleet)

The current five agents map cleanly to HR. For HR **and financial enterprises**,
the high-value additions:

| New agent | Framework fit | What it does | Risk posture |
|-----------|---------------|--------------|--------------|
| **Offboarding Orchestrator** | LangGraph + connectors | Revoke access, recover assets, finalise payroll — human-gated like onboarding. | Gated writes |
| **Benefits Advisor** | LangGraph (RAG) | Personalised benefits/enrollment guidance from plan docs. | Advisory |
| **Compliance/Policy Drift Monitor** | scheduled + RAG | Watches policy changes & flags answers that cite stale versions. | Advisory |
| **Expense / Invoice Triage** *(finance)* | CrewAI + PDF intake | Classify and validate uploaded invoices/expenses, flag anomalies for approval. | Gated writes |
| **Payroll Exception Handler** *(finance)* | LangGraph | Detect/route payroll discrepancies to a human with context. | Escalate |
| **Sentiment & Engagement Analyst** | scikit-learn + LLM | Trend survey/feedback sentiment; feed the attrition watchlist. | Advisory |
| **Interview Scheduler** | CrewAI + connectors | Coordinate panels/calendars off a shortlist. | Gated writes |

All reuse the existing spine: intake → agent → status envelope → audit →
(optional) human approval. The **finance** agents lean on the PDF intake already
built (invoices/expenses are documents).

---

## 4. What I need — Anthropic API

To move from deterministic fallbacks to full AI quality, and to support the
features above:

### Access & models
- **`ANTHROPIC_API_KEY`** with production quota (the app already reads it from env;
  currently configured to `claude-sonnet-4-20250514`).
- Confirm the **target Claude model(s)**: a capable model (Sonnet-class) for
  triage/policy synthesis/explanations, optionally a cheaper/faster model
  (Haiku-class) for high-volume classification to control cost.
- **Rate limits / spend caps** sized for the demo + pilot (triage and Q&A are the
  hot paths). A separate key per environment (dev / staging / prod).

### API capabilities to adopt (high ROI)
- **Prompt caching** — cache the system prompt + policy context across requests to
  cut latency and cost on repeated Q&A. *(Biggest cost lever.)*
- **Tool use (function calling)** — let agents call `qdrant_search`,
  `get_policy_doc`, and connector actions in a structured loop.
- **Citations** — ground Policy Q&A answers in the exact source spans for
  compliance-grade traceability.
- **Batch API** — bulk resume screening / attrition scoring at lower cost.
- **Files API** — handle large PDF policy/resume uploads natively.
- **Extended thinking** — for harder triage/compliance reasoning where warranted.
- **(Optional) Managed Agents / Agent SDK** — if we standardise the agent loop.

### Observability
- **LangSmith** (or equivalent) project + API key for tracing every agent/LLM run
  and building eval datasets (Tier 3 quality harness).

---

## 5. What I need — other services & access

| Need | Why | Notes |
|------|-----|-------|
| **PostgreSQL** instance (+ PgBouncer) | Production system of record | App is already Postgres-ready; just supply `DATABASE_URL`. |
| **Redis** | Cache, rate-limit, idempotency, WebSocket fan-out | Unlocks multi-replica scale (SCALING.md steps 2–4). |
| **Qdrant** (managed or self-hosted) | Real semantic policy retrieval | Set `QDRANT_URL`; ingest policy PDFs. |
| **Object storage (S3/MinIO)** | Policy PDFs, model artifacts, audit archive, exports | — |
| **Hosting / Kubernetes** | Run API + workers + frontend with autoscaling | Helm chart on the roadmap (IMPLEMENTATION.md §3). |
| **Domain + TLS** | Public dashboard + webhook endpoints | — |
| **OIDC/SSO provider** (Okta/Auth0/Entra) | RBAC + SSO for enterprise | Needed for multi-tenant pitch. |
| **Workday / ServiceNow sandbox creds** | Real onboarding/ticketing integration demo | Mock connectors exist; sandbox makes it real. |
| **Slack/Teams app creds** | Conversational Policy Q&A bot | Tier-1 demo feature. |
| **Sample/anonymised data** | Policy PDFs, resumes, tickets, attrition CSV | Makes the demo concrete and on-domain. |
| **Monitoring stack** | OTel + Prometheus/Grafana, alerting | Production readiness. |
| **Secret manager** (Vault/KMS) | Store keys/creds, rotation | Replace `.env` in prod. |

### Minimal set to make the *next* demo pitch-ready
1. `ANTHROPIC_API_KEY` (+ prompt caching, tool use, citations).
2. A **PostgreSQL** URL and a **Qdrant** instance with **sample policy PDFs** ingested.
3. **LangSmith** key for trace/eval visibility.
4. (Nice-to-have) **Slack app** creds for the conversational Q&A wow-moment.

Everything else degrades gracefully, so the app stays demoable while these land
incrementally.

---

## 6. Status snapshot for the pitch

- ✅ 5 agents, multi-modal intake (text/PDF/URL), inbound webhooks, status contract.
- ✅ Human-in-the-loop approvals + immutable audit + CSV export.
- ✅ Case detail drawer (ticket + audit activity trail) in the Cases panel.
- ✅ Postgres-ready, Docker-hardened, CI green (14/14 tests).
- ⏭ Next: Anthropic key + caching/tools/citations, Qdrant+policies, LangSmith,
  then the Tier-1 features (case drawer, Slack Q&A, bulk screening).
