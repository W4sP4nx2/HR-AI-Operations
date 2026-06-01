# Launch Plan — Demo, Open-Source Criteria & Path to Hosting

Compact, actionable. Ties together the existing docs ([WALKTHROUGH](./WALKTHROUGH.md),
[DEPLOYMENT](./DEPLOYMENT.md), [COMPLIANCE](./COMPLIANCE.md),
[OPEN_SOURCE_LAUNCH](./OPEN_SOURCE_LAUNCH.md)).

---

## A. Demo setup (5 minutes, zero secrets)

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed_data            # 5 policies, 6 cases, chat transcript
uvicorn api.main:app --reload --port 8000
# Frontend
cd ../frontend && npm install && npm run dev      # http://localhost:3000
```

Two ways to run the demo:

| Mode | Env | Shows |
|------|-----|-------|
| **Explore** (default) | `AUTH_ENFORCE=false` | One login sees the whole console (top bar: "demo · open access") |
| **Product** | `AUTH_ENFORCE=true` | Role split: employee → chat-only; HR → full console |

### Demo script (8 beats, ~6 min)
1. **Login** → land on the dashboard. (Product mode: log in as `employee@acme.com` to show **chat-only HR Assistant**, then as `admin@acme.com` for the **full Command Center**.)
2. **Chat → policy Q&A:** "How many vacation days do I get?" → cited answer (or "basic mode" without a key).
3. **Chat → triage:** "I'm being harassed by my manager" → **URGENT → escalated → human** (bypasses manager).
4. **Cases** → live feed updates; click a case → **detail drawer** with the audit activity trail.
5. **Policies** → drag-drop a PDF → ingested + listed (manager+).
6. **Fleet → Resume Screener:** attach a resume + JD → score + **"blinded" fairness** badge; mention name-blind identical scores.
7. **Approvals:** trigger Onboarding → **pause** → Approve/Reject (reason captured in audit).
8. **Audit** → every action above, PII-redacted → **Export CSV**. Close on the compliance story.

> Guarantee resilience: `MOCK_LLM=true` (zero LLM spend, no external flake) or
> `DEMO_MODE=true` for a fully deterministic, cached run.

---

## B. Live setup (Render Blueprint, ~15 min)

1. **Pre-flight (must pass):** `cd backend && ruff check . && black --check . && pytest -q`
   and `cd frontend && npm run build`. Confirm no secrets in git (`gitleaks` / CI).
2. **Push to GitHub** (public). CI runs lint · test · **compliance gate** · build · secret-scan.
3. **Render → New + → Blueprint → select repo** (`render.yaml`): provisions Postgres,
   **auto-generates `JWT_SECRET`**, builds the **lean prod images** (no torch/CrewAI →
   small, fast, free-tier-friendly).
4. **Set dashboard secrets:** `ANTHROPIC_API_KEY` (optional), `ADMIN_EMAIL`/`ADMIN_PASSWORD`
   (first-run admin), `CORS_ORIGINS` (frontend URL), and the frontend's
   `NEXT_PUBLIC_API_BASE` / `NEXT_PUBLIC_WS_URL` (the backend URL). Redeploy.
5. **Enforced by default in prod:** `render.yaml` sets `AUTH_ENFORCE=true`, so the
   role split + RBAC are live. Verify `/health` → `auth_enforced: true`.

Backend entry point: `uvicorn api.main:app` (Dockerfile.prod `CMD`). Same pattern
maps to Fly.io / Railway via `*/Dockerfile.prod`. Full details: [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## C. Success criteria for open-sourcing (Definition of Done)

Ship when **all** are true — measurable, not vibes.

**Compact & packaged**
- [x] Lean prod image installs `requirements-prod.txt` (no torch/CrewAI/LangGraph); boots without them.
- [x] One-command demo data: `python -m scripts.seed_data`.
- [x] Multi-stage **non-root** Dockerfiles + `docker-compose.prod.yml` + `render.yaml`.
- [x] Single entry point (`uvicorn api.main:app`); `.env.example` documents every flag.

**Quality gates (CI blocks merge)**
- [x] `ruff` + `black` clean; **70 tests** pass; frontend `build` passes.
- [x] **Compliance gate** job: bias disparity-ratio < 1.1 + security suite.
- [x] **gitleaks** secret scan; no secrets in history; `.env*`/`*.db` gitignored.

**Trust & docs**
- [x] MIT LICENSE · CONTRIBUTING · SECURITY · COMPLIANCE · MODEL_CARDS.
- [x] PII redacted at write (audit + chat); RBAC + role-split; human-in-the-loop on adverse actions.
- [ ] **README hero GIF** (record the 8-beat demo) — the one remaining must-do.
- [ ] Repo topics + Issues/Discussions enabled + a `good first issue` or two.

**Clarity**
- [x] 10-second README hook + quick start + docs index.
- [x] Clear use cases (§D of WALKTHROUGH + the demo script above).

> **Go/no-go:** every box except the GIF + repo-settings is done. Record the GIF,
> flip the repo public, and it's launch-ready.

---

## D. Next steps — app → hosted (sequenced, additive)

Each step is independently shippable; the app keeps working between them.

1. **Record demo GIF + go public** (Tier-0 from SHOWCASE_READINESS). *← do first.*
2. **Deploy live** (Render Blueprint above) → share the URL + LinkedIn post draft.
3. **Per-user case ownership** so employees see *their* cases (today org-scoped by role).
4. **Embeddable employee chat widget** (Slack/Teams/portal) — make the dashboard HR-only.
5. **Redis** → read-through cache + rate-limit + **WebSocket Pub/Sub** (multi-replica live feed).
6. **Task queue** (Arq/Celery) → agent work off the request path; `/trigger` returns a job id.
7. **Scheduled retention purge** + Postgres audit partitioning (close the GDPR auto-erasure gap).
8. **LangSmith** tracing/eval harness; **Workday/ServiceNow** connectors (mock-first).
9. **Multi-tenancy** (tenant id + row-level security) for SaaS; then **K8s + autoscaling**.

Full architecture & rationale: [SCALING.md](./SCALING.md) · [PIPELINE_AND_UX.md](./PIPELINE_AND_UX.md) · [PRODUCT.md](./PRODUCT.md).

---

## One-line status

> **Code-complete and gated** (70 tests, compliance CI, lean packaging, Render
> blueprint). The only blockers to a public launch are **a demo GIF** and
> **flipping the repo public + setting deploy secrets** — everything else is shipped.
