# Pipeline Improvements & UX Research

Concrete, prioritised improvements to the data/agent pipeline, plus where to pull
**UX research and patterns from GitHub** so the dashboard keeps pace with the best
open-source agent/chat UIs.

---

## 1. Pipeline improvements

### P0 — correctness & trust (do first)
- **Idempotency keys** on triage/webhook intake — hash `(tenant, text)` so retries
  don't create duplicate cases. Store key→case in Redis/DB with a TTL.
- **Async agent execution** — move LLM/RAG/CrewAI work off the request path onto a
  task queue (Arq/Celery); `/trigger` returns a job id, result via WS/poll. Keeps
  p99 latency flat under model latency.
- **Audit write batching** — buffer audit inserts (50ms / 500-row window) so the
  highest-volume write path absorbs spikes. Partition the table by month (Postgres)
  with a BRIN index on `timestamp`.

### P1 — RAG quality
- **Semantic answer cache** — key Policy-Q&A answers by the query embedding
  (cosine ≥ 0.97 ⇒ hit). Cuts the most expensive path to a Redis lookup.
- **Cross-encoder re-ranking** after Qdrant top-k for sharper retrieval.
- **Citations with char offsets** so the UI highlights the exact source span.
- **Chunking upgrade** — token-aware (tiktoken) + structure-aware splitting
  (headings/sections) instead of fixed word windows.
- **Incremental re-ingest** — detect changed policy docs by hash; re-embed only
  the delta; version citations to the doc revision.

### P2 — agent depth & evaluation
- **Prompt caching** (Anthropic) on the system prompt + policy context — biggest
  cost lever once an API key is set.
- **Eval harness** — golden datasets for triage accuracy and RAG groundedness;
  run offline in CI (LangSmith or `promptfoo`) to gate regressions.
- **Tool-call streaming** in chat — surface each tool call as it happens (the UI
  already renders tool badges; stream them live in full mode).
- **Guardrails** — PII redaction at audit-write time; prompt-injection checks on
  scraped/web content; output validation on LLM JSON.

### P3 — platform
- **Redis** for cache, rate-limit (token bucket per user/tenant), idempotency,
  and **WebSocket Pub/Sub fan-out** across replicas.
- **Connector framework** — `connectors/base.py` interface; Workday/ServiceNow/
  Slack/Okta adapters (mock-first).
- **Multi-tenancy** — tenant id on every row, row-level security, per-tenant
  Qdrant shards and quotas.

See [SCALING.md](./SCALING.md) for the architecture and the incremental rollout
order; this list is the *pipeline-level* slice of it.

---

## 2. Getting UX research & patterns from GitHub

The dashboard is custom (Next.js + Tailwind, brand palette). To keep its UX
current, mine these open-source projects for **interaction patterns**, not code to
copy wholesale. For each, note the specific thing worth studying.

### Chat / assistant UX
| Repo (search on GitHub) | What to study |
|-------------------------|---------------|
| `vercel/ai-chatbot` | Streaming message UX, tool/generative-UI rendering, message actions (copy/retry/edit). |
| `assistant-ui/assistant-ui` | A React primitives library purpose-built for AI chat — message threads, tool-call UIs, attachments. Strong reference for our ChatPanel. |
| `Hacker0x01` / `lobehub/lobe-chat` | Session list + history management, model/role switching, settings UX. |
| `open-webui/open-webui` | Document/RAG attach-and-cite UX, conversation organisation, admin controls. |
| `mckaywrigley/chatbot-ui` | Minimal, clean chat layout; folders/prompts organisation. |

### Agent / ops dashboards
| Repo | What to study |
|------|---------------|
| `langchain-ai/langsmith` (docs/UI) | Run/trace timelines, tool-call inspection, eval views — directly relevant to our Audit + activity-trail drawer. |
| `langflow-ai/langflow`, `FlowiseAI/Flowise` | Visualising agent/graph runs; node status states (idle/running/error) — mirrors our Fleet badges. |
| `tremorlabs/tremor` | Dashboard/analytics components (KPI cards, charts) for the Analytics panel. |
| `shadcn/ui` | Accessible primitives (drawer/sheet, dialog, command palette) — patterns for the case detail drawer and a future ⌘K command bar. |

### Design systems & accessibility
| Resource | Why |
|----------|-----|
| `github/primer` (Primer Design System) | Enterprise data-dense UI patterns, accessibility, empty/loading states. |
| `adobe/react-spectrum` (React Aria) | Best-in-class accessible behaviours for menus, tables, dialogs. |
| `tailwindlabs/tailwindcss` discussions/showcase | Layout/spacing patterns consistent with our stack. |

### How to actually use these
1. **Audit our flows against them** — open each panel (Chat, Cases, Fleet,
   Approvals) and compare the empty state, loading state, error state, and the
   "what just happened" feedback to the references above.
2. **Steal interaction patterns, keep our brand** — palette
   (`#5D1C6A / #CA5995 / #FFB090 / #FFF1D3`) and minimalist direction stay; adopt
   patterns like message actions, a session sidebar, and a ⌘K command palette.
3. **Run lightweight usability tests** — 5 users × the 6 core flows (ask a policy,
   triage a ticket, screen a resume, approve onboarding, review audit, upload a
   policy). Capture time-to-task and confusion points; file as issues.
4. **Accessibility pass** — keyboard nav, focus traps in the drawer/modals, ARIA
   on the chat log, colour-contrast check on the brand palette.

### Concrete UX backlog (from the above)
- [ ] Chat: session sidebar (list/rename/delete) wired to the new `/chat/sessions`.
- [ ] Chat: message actions (copy, retry) + streaming tool badges in full mode.
- [ ] Global ⌘K command palette (jump to panel, trigger agent, search cases).
- [ ] Empty/loading/error states audited per panel (skeletons, retry buttons).
- [ ] Keyboard + screen-reader pass on drawer, dialogs, and the chat log.
- [ ] Auth: login screen + avatar/role menu + Google button (wired to `/auth`).
