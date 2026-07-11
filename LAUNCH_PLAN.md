# Launch Plan — Demo, Open-Source Criteria & Path to Hosting

Compact, actionable. The release gate is
[OPEN_SOURCE_LAUNCH.md](./OPEN_SOURCE_LAUNCH.md); deployment and compliance
details live in [DEPLOYMENT.md](./DEPLOYMENT.md) and
[COMPLIANCE.md](./COMPLIANCE.md).

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

Two access modes:

| Mode | Env | Shows |
|------|-----|-------|
| **Open-access evaluation** (default) | `AUTH_ENFORCE=false` | No login required; choose a seeded persona |
| **Product** | `AUTH_ENFORCE=true` | Role split: employee → chat-only; HR → full console |

### Demo script (8 beats, ~6 min)
1. **Enter** through the persona launchpad. In enforced mode, sign in as a
   viewer and an HR operator to show the role boundary.
2. **Chat → policy Q&A:** "How many vacation days do I get?" → cited answer (or "basic mode" without a key).
3. **Chat → triage:** "I'm being harassed by my manager" → **URGENT → escalated → human** (bypasses manager).
4. **Cases** → live feed updates; click a case → **detail drawer** with the audit activity trail.
5. **Policies** → drag-drop a PDF → ingested + listed (manager+).
6. **Fleet → Resume Screener:** attach a resume + JD → score + **"blinded" fairness** badge; mention name-blind identical scores.
7. **Approvals:** trigger Onboarding → **pause** → Approve/Reject (reason captured in audit).
8. **Audit** → every action above, PII-redacted → **Export CSV**. Close on the compliance story.

> For a deterministic run with zero model spend, set `MOCK_LLM=true`.

---

## B. Release setup (Docker Compose or AMD overlay)

1. **Pre-flight (must pass):** run every step in
   [OPEN_SOURCE_LAUNCH.md](./OPEN_SOURCE_LAUNCH.md).
2. **Push to GitHub** (public). CI runs lint · test · **compliance gate** · build · secret-scan.
3. **Run the production Compose stack** with Postgres/pgvector and the lean prod
   images; set `JWT_SECRET`, `ADMIN_*`, `CORS_ORIGINS`, and provider settings in
   the environment. See [DEPLOYMENT.md](./DEPLOYMENT.md).
4. **For AMD inference**, apply `docker-compose.amd.yml` on a compatible AMD
   host and run `make judge-amd-live` only when the required hardware and
   credentials are present.
5. **Choose the access posture deliberately:** local demos may use
   `AUTH_ENFORCE=false`; private or production deployments must set
   `AUTH_ENFORCE=true` and verify it through `/health`.

Backend entry point: `uvicorn api.main:app` (Dockerfile.prod `CMD`). Same pattern
maps to Fly.io / Railway via `*/Dockerfile.prod`. Full details: [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## C. Success criteria for open-sourcing (Definition of Done)

Ship when **all** are true — measurable, not vibes.

**Compact & packaged**
- [x] Lean prod image installs `requirements-prod.txt` (no torch/CrewAI/LangGraph); boots without them.
- [x] One-command demo data: `python -m scripts.seed_data`.
- [x] Multi-stage **non-root** Dockerfiles + `docker-compose.prod.yml` + AMD overlay.
- [x] Single entry point (`uvicorn api.main:app`); `.env.example` documents every flag.

**Quality gates (CI blocks merge)**
- [x] Backend lint and complete tests; frontend lint and production build.
- [x] **Compliance gate** job: bias and security suites.
- [x] **gitleaks** secret scan; no secrets in history; `.env*`/`*.db` gitignored.

**Trust & docs**
- [x] MIT LICENSE · CONTRIBUTING · SECURITY · COMPLIANCE · MODEL_CARDS.
- [x] PII redacted at write (audit + chat); RBAC + role-split; human-in-the-loop on adverse actions.
- [ ] **README hero GIF** (record the 8-beat demo) — the one remaining must-do.
- [ ] Repo topics + Issues/Discussions enabled + a `good first issue` or two.

**Clarity**
- [x] 10-second README hook + quick start + docs index.
- [x] Clear use cases in [USECASES.md](./USECASES.md) and the demo script above.

> **Go/no-go:** run the current pre-push checklist and verify the exact release
> commit. Do not inherit an older green status.

---

## D. Next steps — app → hosted (sequenced, additive)

Each step is independently shippable; the app keeps working between them.

1. **Record the walkthrough** using synthetic data.
2. **Run the approved Docker Compose path** and verify the release commit.
3. **Per-user case ownership** so employees see *their* cases (today org-scoped by role).
4. **Embeddable employee chat widget** (Slack/Teams/portal) — make the dashboard HR-only.
5. **Redis** → read-through cache + rate-limit + **WebSocket Pub/Sub** (multi-replica live feed).
6. **Task queue** (Arq/Celery) → agent work off the request path; `/trigger` returns a job id.
7. **Scheduled retention purge** + Postgres audit partitioning (close the GDPR auto-erasure gap).
8. **LangSmith** tracing/eval harness; **Workday/ServiceNow** connectors (mock-first).
9. **Multi-tenancy** (tenant id + row-level security) for SaaS; Kubernetes and
   autoscaling remain future-state work after a measured scale requirement.

Full architecture & rationale: [SCALING.md](./SCALING.md) · [PIPELINE_AND_UX.md](./PIPELINE_AND_UX.md) · [PRODUCT.md](./PRODUCT.md).

---

## One-line status

> **Release candidate:** lean packaging, CI gates, and Docker Compose plus an
> optional AMD overlay exist. Kubernetes templates are future-state only. Public
> release still requires the current
> pre-push checklist, endpoint verification, and review of all intended changes.
