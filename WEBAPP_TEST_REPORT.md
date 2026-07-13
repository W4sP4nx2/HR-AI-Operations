# Web App Test Report

## 2026-07-11 Revalidation

Current source-level and application-object checks after the ETL/3D work:

| Scenario | Result | Evidence |
|---|---|---|
| Frontend lint, TypeScript, production bundle | Pass | `npm run lint && npm run build` |
| 3D topology and bias radar wiring | Pass at build/contract level | `Governance3D` consumes capability and bias APIs; no default cost-savings number remains |
| BYOK settings affordance | Pass at build/contract level | Key input renders in launchpad/top bar; key remains module-memory-only and is added only to inference headers |
| PTO chat through governed application object | Pass | Certified 25-day answer, `policy_pto_2024` citation, confidence `0.74`, no PII violation |
| Bias dashboard payload | Pass | 10,000 records; race impact ratio `0.7126`; compliance headline emitted |
| Postgres/pgvector and MinIO | Pass | `docs/evidence/local-etl-integration.json` |
| Fresh interactive browser render | Pass | Local preview on `http://127.0.0.1:3001`; dashboard loaded with seeded 12-policy/50-case state |
| Browser CORS/WebSocket transport | Pass | Port `3001` preflight returned `200`; live feed WebSocket accepted |
| Browser PTO chat | Pass | `How many PTO days do I have?` returned the active 2024 policy and `25 days PTO` in deterministic mode |
| Browser 3D governance visuals | Pass at runtime | Analytics rendered two WebGL canvases (`547x420`, `417x420`) and showed the Four-Fifths compliance alert |
| Employee role boundary | Pass at runtime | Switching to Employee reduced navigation to Chat only |
| Preview seed contract | Pass | `scripts/local_preview.sh` idempotently seeds policies, cases, and hashing vectors before starting both services |

The browser run above is the current checkout evidence. A screenshot export is
not used as a provider, performance, or compliance claim; the DOM state, API
responses, WebSocket handshake, canvas dimensions, and visible compliance alert
are the authoritative checks.

Date: 2026-07-09
Frontend: `http://localhost:3000`
Backend observed: `http://localhost:8000`

## Result Summary

| Scenario | Result | Evidence |
|---|---|---|
| Open the product without login | Pass | Open-access banner, role switcher, navigation, and Chat rendered without authentication |
| Recover the local preview | Pass | Removed the global PostCSS override that deleted Next 16's pinned private dependency; the restarted frontend now compiles and serves the app |
| Load Cases | Pass | 131 records loaded with category and status filters |
| Filter Cases to `URGENT` | Pass | The view selected `URGENT` and rendered five case IDs, all with `URGENT` cards |
| Load Policies | Pass | Ten ingested policy documents rendered with chunk counts and dates |
| Desktop layout | Pass | 1440 × 900 check showed stable sidebar geometry and no content overlap |
| Mobile layout | Pass | 390 × 844 check showed no horizontal overflow; the navigation drawer exposed every workspace |
| Browser console | Pass | No warning or error entries during the tested flows |
| Chat: list open `URGENT` cases | Source passes; stale runtime fails | Current regression test applies the category, but the old port-8000 process still returns all 17 active cases and omits the current tool-result `category` field |
| Re-test current backend in browser | Blocked | Permission to stop or replace the stale backend process was unavailable during this run |

Screenshots:

- [Desktop workspace](./docs/webapp-tests-desktop.jpg)
- [Mobile navigation](./docs/webapp-tests-mobile-menu.jpg)
- [Earlier chat result](./docs/webapp-test-chat-result.png)

## Preview Failure and Fix

The frontend initially returned `500 Internal Server Error`. The Next development
log showed that `frontend/package.json` globally overrode PostCSS to `8.5.16`.
Next 16 pins `8.4.31` and resolves it from its own dependency path; npm had
deduplicated that copy away.

The fix removes the global override. The resulting tree keeps:

- project PostCSS: `8.5.16`
- Next private PostCSS: `8.4.31`

This restores CSS compilation without downgrading the project's direct
dependency.

## Runtime Findings

- The Cases workspace applies its own `URGENT` filter correctly.
- The stale chat backend does not reflect the current fallback parser. Its
  response lacks the `category` field that the checked-in code adds, proving
  this is runtime drift rather than a second source defect.
- The Cases view still renders a large active result set. Pagination or
  virtualization remains prudent before the dataset grows materially.
- Health reports process availability, not the freshness of loaded source.
  Deployment metadata or a build revision in `/health` would make runtime drift
  visible.

## Required Runtime Re-check

After restarting the backend from the current checkout:

1. Ask “List all open URGENT cases” and verify every returned row is `URGENT`.
2. Ask “How many vacation days do I get?” and verify either a cited answer or
   the bounded timeout response appears within 15 seconds.
3. Confirm `/health` reports the expected provider and configuration.
