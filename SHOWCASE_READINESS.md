# Showcase Readiness — A Senior Engineer's Honest Review

A deliberately critical assessment of why this project is **not yet ready to
showcase**, followed by a **pragmatic, right-sized plan** to get there. The bar
here is "a senior engineer would be comfortable putting their name on it publicly"
— not "enterprise-perfect." We explicitly avoid over-engineering for an OSS project.

---

## The argument: why it's not ready yet

The project demos well, but a senior reviewer kicking the tyres would find these
gaps. They fall into three buckets: **trust**, **correctness under real use**, and
**first-impression**.

### A. Trust & safety gaps (a reviewer will probe these first)
1. **Auth is advisory by default.** `AUTH_ENFORCE=false` means RBAC is decorative
   in the default run — anyone can approve onboarding or delete policies. Great for
   a zero-friction demo, but a reviewer will ask "so the roles do… nothing?" The
   story (advisory dev / enforced prod) is sound but **undocumented at the point of
   use** and there's no enforced-mode demo.
2. **No login UI gate on destructive actions.** The frontend never tells the user
   their role or that an action needs one; a 401/403 in enforced mode would surface
   as a generic failure, not "you need manager access."
3. **Webhook auth is a shared-secret stub.** Fine for v1, but it's labelled
   "production: use HMAC" and that's not done. A reviewer reads that as a TODO.
4. **Secrets hygiene unproven.** No `git filter`/secret-scan run documented; the
   dev `JWT_SECRET` ships in config. Needs an explicit "no secrets committed" gate
   before going public.

### B. Correctness under real use
5. **The full LLM path is under-tested.** 40 tests are green, but they almost all
   exercise the **deterministic fallback**. The actual Claude/Pydantic-AI streaming
   path, tool-call extraction, and the Google OAuth round-trip have **no automated
   coverage** and were only smoke-tested manually. That's the path a reviewer with
   an API key will actually run.
6. **No integration tests through the ASGI app.** Routes are tested via direct
   function calls; there's no `httpx.AsyncClient` test hitting the real app with
   middleware, auth headers, and error envelopes end-to-end.
7. **WebSocket fan-out is single-process.** Documented in SCALING.md, but if a
   reviewer runs two workers the live feed silently misbehaves. At minimum it needs
   a clear "single-instance only for now" note in the README.
8. **Frontend has no tests at all.** No type-check in CI for the frontend beyond the
   build; no component/interaction tests. A broken panel ships green.

### C. First impression (the showcase itself)
9. **README doesn't sell in 10 seconds.** No hero screenshot/GIF, no live demo
   link, no badges. The substance is in 9 separate `.md` files a visitor won't read.
10. **No deployed demo.** "Runs on your laptop" is great for contributors but a
    showcase needs a **one-click live URL** (or a recorded walkthrough) so a
    reviewer can try it without cloning.
11. **Empty/error/loading states are thin.** Several panels show a bare "No data";
    a reviewer notices missing skeletons, retry buttons, and toast feedback.
12. **CI doesn't run the frontend build or block on it**, and there's no status
    badge — so "CI passing" isn't visibly true.

### What's genuinely strong (don't redo these)
Clean async data layer (SQLite↔Postgres), validated agent contracts + registry,
graceful degradation, audit + approvals with reject-capture, RBAC core, Docker
healthchecks, and solid docs. The bones are good — this is polish, not a rewrite.

---

## The plan: right-sized, not over-engineered

Three tiers. **Tier 0 is the actual blocker list for showcase** — do only this to
ship. Tiers 1–2 are "nice before LinkedIn" and "later", explicitly deferred so we
don't gold-plate an OSS side project.

### Tier 0 — Required to showcase (≈ half a day)
- [ ] **README hero**: one-paragraph pitch + a **demo GIF** (record Chat → Cases →
      Approvals) + quick-start + links to the deep-dive docs. This is the single
      highest-leverage item.
- [ ] **Secret-scan gate**: run `gitleaks`/`git log -p | grep -i key`, confirm
      `.gitignore` covers `.env*`/`*.db`, and document "first user = admin" +
      "rotate `JWT_SECRET` in prod" in the README.
- [ ] **Frontend RBAC feedback**: show the user's role in the sidebar (done) and
      turn 401/403 into a clear "you need <role> access" toast instead of a generic
      error. Small, high-trust-signal.
- [ ] **Document the auth posture at the point of use**: a one-liner in the README
      and login screen — "advisory by default; set `AUTH_ENFORCE=true` to enforce
      roles" — so the RBAC isn't mistaken for decorative.
- [ ] **Frontend build in CI** + a CI status badge in the README.
- [ ] **A handful of API integration tests** via `httpx.AsyncClient` against the
      ASGI app: health, login→protected route (enforced mode 401 then 200 with
      token), one agent trigger, audit read. ~6 tests; covers the "real app" path.

### Tier 1 — Strongly recommended before sharing widely (≈ 1 day)
- [ ] **Full-LLM-path test** behind an env guard (skips without `ANTHROPIC_API_KEY`)
      so the streaming + tool-call path has at least one real assertion in CI when a
      key is present.
- [ ] **Empty/loading/error states** audited per panel (skeletons + retry).
- [ ] **A deployed demo** (Render/Fly/Railway free tier) or a 90-second Loom — a
      reviewer should not have to clone to see it work.
- [ ] **HMAC webhook verification** to retire the stub (it's small and removes a
      visible TODO).

### Tier 2 — Deliberately deferred (do NOT do for the showcase)
These are real but would be over-engineering an OSS portfolio piece right now:
Redis/queues/K8s, multi-tenancy, the connector marketplace, LangSmith eval
harness, Postgres in the default compose, model registry. They're already captured
in [SCALING.md](./SCALING.md) and [PIPELINE_AND_UX.md](./PIPELINE_AND_UX.md) as the
roadmap — pointing at a credible roadmap is *better* for a showcase than half-
building it.

### Anti-over-engineering guardrails
- Keep the **default run zero-secret and single-process**; just *say so*.
- Prefer **a GIF + a roadmap link** over building the scaled version.
- Add tests where a reviewer will actually click (integration + LLM path), not 100%
  coverage everywhere.
- No new infra (Redis/K8s) until there's a user asking for scale.

---

## Definition of "showcase-ready"
Tier 0 complete: a visitor lands on the README, sees it work in a GIF (or live),
trusts it (secrets clean, roles explained, CI badge green), and a senior reviewer
who clones it gets a passing `pytest` + `npm run build` and a working login in
under five minutes. That's the bar — and it's a half-day away, not a rewrite.
