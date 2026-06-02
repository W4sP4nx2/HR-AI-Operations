# Deployment Status — HR AI Operations

_Checked: 2026-06-02. Branch `main` @ `1165fb7`, clean and in sync with `origin/main`._

## Live

| | |
|---|---|
| **Live demo (BYOK sandbox)** | **https://hr-frontend-sve4.onrender.com** — verified **HTTP 200** |
| Frontend | Render **Static Site** (always-on CDN) — Render appended the `-sve4` suffix (the global-subdomain collision flagged pre-deploy) |
| Backend | Render **Web Service**, `plan: standard` (no cold-start); URL is Render-assigned. Operator-verified: `/metrics` → `active_cases: 3`, `cases_total: 8` |
| Public UI | **System Healthy**, live sync, **3 active cases** |
| Repo | https://github.com/W4sP4nx2/HR-AI-Operations (public) |

## `main` health (checked locally)

- ✅ **pytest: 179 passed, 3 skipped** (the 3 skips are the optional pgvector integration tests).
- ✅ **ruff** clean · **black** clean (86 files).
- ✅ Working tree clean; `main` ↔ `origin/main` in sync.
- ℹ️ One benign warning unchanged: pydantic-ai's model-EOL deprecation notice (`claude-sonnet-4-20250514`, EOL 2026-06-15). Not a failure.

## What shipped since the GitHub push (`a47b05b..1165fb7`, 9 commits)

The header-falsely-offline bug fix and surrounding deploy hardening:

- **`9b7cf00` — probe response compatibility.** Frontend operational probes now
  tolerate **both** raw JSON **and** the `{ success, data }` envelope (`probeRequest`
  in `frontend/lib/api.ts`), so `/health` and `/metrics` parse regardless of which
  backend build is deployed.
- **`1165fb7` — telemetry success = system health.** The status hook treats a
  successful `/metrics` / `/cases` / WebSocket signal as a valid health signal, so a
  single brittle `/health` probe can no longer leave the header falsely **offline**.
- Supporting: `4353b08` raw health/metrics probes · `29056a7` status fallback ·
  `ab87206` realtime status sync · `a4fa6e7` showcase WS origin allow ·
  `2f75c02` disable public policy uploads in showcase · `542bc49` lint format ·
  `facec08` backend plan → standard.

## CORS / origins (deployed)

`backend/core/config.py` + `api/main.py` allow the real frontend origins
(`hr-frontend-sve4.onrender.com` **and** the bare `hr-frontend.onrender.com`), with a
WebSocket origin check matching the CORS allowlist, and a safety net that expands a
stray `["*"]` back to the known showcase origins.

## Verified by the operator

- `npm run lint` passed · `npm run build` passed.
- Render frontend deploy for `1165fb7` is **live**.
- Public UI shows **System Healthy**, live sync, **3 active cases**.
- Backend `/metrics` confirms `active_cases: 3`, `cases_total: 8`.

## Known non-blocking noise

- **Next.js custom-font warning** (`no-page-custom-font` in `app/layout.tsx`) — cosmetic; does not block lint/build.
- **npm audit / Render vulnerability notices** — transitive advisories; did not block build or deploy.

Neither affects CI (green) or the running deploy.

## Mission alignment (still intact in production)

- **Zero-trust BYOK:** the public instance ships **no global `ANTHROPIC_API_KEY`** —
  live LLM only via a visitor's own key (`X-Client-LLM-Key`, request-scoped
  contextvar, never persisted). Without a key, every feature works in deterministic
  fallback. (`MOCK_LLM/DEMO_MODE=true` → server $0; BYOK overrides for live calls.)
- **Audited:** every action still lands in the immutable audit log; `/metrics` is a
  pure query over it.
- **Open demo:** `AUTH_ENFORCE=false` exposes the persona Launchpad on seeded
  fake data only.

## Open items

- **Free Postgres expiry** (~30 days) if the DB is on Render's free tier — refresh before it lapses (backend is on `standard`, but check the DB plan).
- **Model EOL 2026-06-15** — set `CLAUDE_MODEL` to a current model before then (documented in `.env.production.example`).
- ✅ **README live link + repo homepage** updated to `hr-frontend-sve4.onrender.com`.
