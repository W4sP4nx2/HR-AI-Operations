# Deployment Evidence

_Updated: 2026-07-11. This file records what must be checked; it is not an
automated uptime monitor._

## Declared release surface

| Surface | Declared location | Release check |
|---|---|---|
| Local frontend | `http://127.0.0.1:3001` via `make preview` | Verify the current checkout renders and completes one workflow |
| Local backend | `http://127.0.0.1:8010` via `make preview` | Verify `/health`, `/metrics`, CORS and WebSocket behavior |
| Repository | `https://github.com/W4sP4nx2/HR-AI-Operations` | Verify CI for the commit being released |

There is no current hosted demo surface. The local preview uses seeded data,
advisory roles and no stored server-side Fireworks key. A local operator may
supply a temporary request-scoped key. Enforced deployments use
`AUTH_ENFORCE=true`.

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

- The AMD Compose overlay proves configuration readiness, not GPU utilization.
- Kubernetes/GitOps files are future-state templates and are not part of the
  current release acceptance path.
- Simulated scaling output demonstrates policy behavior, not live capacity.
- Fireworks Batch queue time is asynchronous and must not be described as an
  interactive latency result.

Add dated runtime observations here only when the endpoint and exact commit were
actually checked.
