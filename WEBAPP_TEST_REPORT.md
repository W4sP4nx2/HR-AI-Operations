# Web App Test Report

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
