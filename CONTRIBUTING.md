# Contributing

Thanks for your interest in the HR AI Command Center! This project aims to be a
**trustworthy, open-source AI layer for HR** — see [MISSION.md](./MISSION.md).
Contributions that uphold those principles are very welcome.

## Quick start

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m scripts.seed_data        # sample policies, cases, chats (no key needed)
uvicorn api.main:app --reload --port 8000

# Frontend
cd ../frontend && npm install
cp .env.local.example .env.local
npm run dev                        # http://localhost:3000
```

Everything runs with **zero secrets** in deterministic fallback mode. Add
`ANTHROPIC_API_KEY` (+ Qdrant) for LLM-grounded answers.

## Before you open a PR

```bash
# Backend (must be green — CI enforces these)
cd backend && source .venv/bin/activate
ruff check .          # lint
black --check .       # format
pytest tests/ -q      # tests

# Frontend
cd ../frontend && npm run build && npm run lint
```

- Match existing style: docstrings on public functions, typed signatures, the
  `{success, status, data, error}` response envelope on new endpoints.
- Add tests for new behaviour. Prefer the **fallback/deterministic path** so tests
  run without secrets (see `tests/` for patterns).
- Keep the **graceful-degradation** contract: a new capability must not crash when
  its optional dependency (Qdrant, an API key, scraper libs) is missing — return
  `unavailable`, don't raise.

## Project conventions

- **Backend**: FastAPI + async SQLAlchemy Core (`core/memory.py`). New persistence
  goes through `Memory`; new routes under `api/routes/`.
- **Agents/tools**: live in `agents/`; heavy deps are imported lazily.
- **Auth/RBAC**: protect sensitive routes with `Depends(require_role("..."))`.
- **Frontend**: Next.js 14 + Tailwind; brand palette
  `#5D1C6A / #CA5995 / #FFB090 / #FFF1D3`; minimalist, intuitive.

## Good first issues

- Wire the chat **session sidebar** to `/chat/sessions` (list/rename/delete).
- Build the **login screen** + avatar/role menu against `/auth`.
- Add **empty/loading/error states** per panel (see PIPELINE_AND_UX.md).
- A **connector** mock (Slack or ServiceNow) behind a clean interface.

## Reporting issues & security

- Bugs/features: open a GitHub issue with steps to reproduce.
- Security: please disclose privately first (see SECURITY.md if present) rather
  than opening a public issue.

## Code of conduct

Be respectful and constructive. This is a tool about treating people fairly —
let's hold the community to the same standard.
