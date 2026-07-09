# Deployment Evidence

_Updated: 2026-07-09. This file records what must be checked; it is not an
automated uptime monitor._

## Declared public surface

| Surface | Declared location | Release check |
|---|---|---|
| BYOK sandbox | `https://hr-frontend-sve4.onrender.com` | Verify HTTP response and one complete workflow |
| Repository | `https://github.com/W4sP4nx2/HR-AI-Operations` | Verify CI for the commit being released |
| Backend | Render-assigned service URL | Verify `/health`, `/metrics`, CORS and WebSocket behavior |

The public sandbox intentionally uses seeded data, advisory roles and no stored
server-side Fireworks key. A visitor can enter without login and may supply a
temporary request-scoped key. Enforced deployments use `AUTH_ENFORCE=true`.

## Local evidence for the current worktree

The authoritative commands are in
[OPEN_SOURCE_LAUNCH.md](./OPEN_SOURCE_LAUNCH.md). Record their output against the
commit being pushed; do not carry forward counts or green status from an older
commit.

Required evidence:

- backend lint and complete test suite;
- frontend lint and production build;
- documentation links and formatting;
- provider-bypass and platform-manifest checks;
- `linux/amd64` image manifests;
- secret scan;
- clean review of the intended diff.

## Deployment boundaries

- Render proves the web application path, not AMD execution.
- The AMD Compose/Kubernetes artifacts prove configuration readiness, not GPU
  utilization.
- Simulated scaling output demonstrates policy behavior, not live capacity.
- Fireworks Batch queue time is asynchronous and must not be described as an
  interactive latency result.

Add dated runtime observations here only when the endpoint and exact commit were
actually checked.
