# Pre-Push and Release Checklist

This is the authoritative checklist before pushing to `main`, publishing an
image, or recording a showcase. Run it from the repository root unless a step
says otherwise.

## 0. Keep the release scope small

Before asking another assistant or reviewer to help, use [CONTEXT.md](./CONTEXT.md)
plus the one module or failing test involved. Do not paste the whole repository
into a model. The release narrative is:

> Audit-first HR agent workflows, deterministic fallback, Fireworks acceleration,
> and optional AMD evidence gates.

The demo-critical path is Policy Q&A -> Case Triage -> Resume Screening ->
Onboarding Approval -> Audit Evidence. Cut, mock, or defer work outside that path
if it blocks the release.

## 0.1 Qwen sandbox loop

Use `main` as the last-known-good branch and `dev` as the hackathon integration
branch. Qwen should work on one file or one module at a time.

### Checkpoint

```bash
git switch main
git status --short
git pull --ff-only origin main
git branch dev 2>/dev/null || true
git switch dev
```

If the worktree already contains uncommitted project work, review and commit a
checkpoint before experimenting. Do not run `git checkout .` or `git restore .`
against a mixed worktree unless every changed file is disposable.

```bash
git status --short
git diff --stat
# Commit only reviewed release work:
git add -p
git commit -m "checkpoint: demo-ready HR AI command center"
```

### Qwen prompt contract

Use this prompt shape:

```text
I am working on the dev branch.
Here is the current content of <file_name>.
Update only this file to implement <feature>.
Preserve deterministic fallback, audit logging, PII redaction, typed outputs,
and provider allowlist routing.
Do not refactor other files unless necessary.
Return the patch and the test I should run.
```

### Accept or reject a Qwen patch

After pasting Qwen's code:

```bash
git diff --stat
python3 scripts/check_docs.py              # docs-only changes
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -p pytest_asyncio.plugin backend/tests -q
```

If it works:

```bash
git add -p
git commit -m "feat: <small feature>"
```

If it breaks, discard only the files Qwen touched:

```bash
git restore -- path/to/file.py path/to/test_file.py
```

When in doubt, save the failed patch instead of deleting it:

```bash
git diff > /tmp/qwen-failed.patch
```

### Merge back to main

Only merge after the full checklist in this file and
[COMPETITIVE_QUALITY_GATE.md](./COMPETITIVE_QUALITY_GATE.md) pass for the claims
being published.

```bash
git switch main
git pull --ff-only origin main
git merge --ff-only dev
git push origin main
```

## 1. Review the intended change

```bash
git status --short
git diff --check
git diff --stat
git diff
```

- Confirm every changed and untracked file belongs in the release.
- Do not discard unrelated work from another contributor.
- Remove generated caches, local databases and secrets.
- Update status or test counts only from this run.

## 2. Documentation

```bash
python3 scripts/check_docs.py
```

- `README.md` describes current behavior.
- [MISSION.md](./MISSION.md) and [PRODUCT.md](./PRODUCT.md) agree with it.
- Dated evidence files do not present old observations as current status.
- Diagrams and screenshots referenced by the README exist.
- No author biography, placeholder identity or personal promotion remains.

## 3. Static and provider guardrails

```bash
python3 scripts/verify_platform_manifests.py
cd backend
ruff check .
python -m pytest -p pytest_asyncio.plugin \
  tests/test_provider_guardrails_static.py \
  tests/test_image_platform_verifier.py \
  tests/test_platform_manifests.py -q
cd ..
```

Confirm that provider hosts and model IDs remain environment-injected and that
no direct client bypass was introduced.

## 4. Complete backend verification

Use an environment containing the base requirements, PyTorch and
`pytest-asyncio`; the optional kernel tests need PyTorch even on CPU.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -p pytest_asyncio.plugin backend/tests -q
```

Record passed, skipped and warning counts. Re-run the kernel correctness files
on the AMD instance before trusting any GPU benchmark:

```bash
python3 -m pytest -p pytest_asyncio.plugin \
  backend/tests/test_fused_cosine_score.py \
  backend/tests/test_curriculum.py -v
```

## 5. Frontend verification

```bash
cd frontend
npm run lint
npm run build
cd ..
```

For user-facing changes, also exercise the affected workflow in the browser at
desktop and mobile widths.

## 6. Packaging and deployment

```bash
docker compose config --quiet
```

For the AMD overlay, inject non-production validation values and validate the
production merge with `--profile amd`. Do not add defaults for provider hosts,
keys or allowed models.

Before publishing an image, inspect its manifest and confirm a
`linux/amd64` entry. Apple Silicon builds must use an explicit
`--platform linux/amd64` or a multi-platform builder.

```bash
python3 scripts/verify_image_platform.py \
  "$REGISTRY/hr-command-center-backend:$TAG"
python3 scripts/verify_image_platform.py \
  "$REGISTRY/hr-command-center-frontend:$TAG"
```

## 7. Secrets and external smoke tests

```bash
gitleaks dir . --no-banner --config .gitleaks.toml --redact --exit-code 1
```

- Never print or commit provider keys.
- Run `python -m scripts.fireworks_smoke` only in a credentialed environment.
- Verify the declared public frontend, backend health and one end-to-end
  workflow for the exact release commit.
- Capture AMD evidence only on named AMD hardware.

## 8. Final push decision

Push only when:

- all required checks pass;
- skips and warnings are understood;
- the documentation describes the same product the code implements;
- unsupported scale, GPU or provider claims are absent;
- the final diff has been reviewed.

Do not push if the only evidence is local intent. The following claims need
current artifacts:

| Claim | Required before publishing |
|---|---|
| Live Fireworks support | Credentialed smoke test or guarded skip clearly documented |
| Scanned resume VLM | Explicit `ENABLE_RESUME_VLM=true` run with approved image egress |
| Fireworks Batch value | Prepared JSONL plus one live job ID or marked credential-gated |
| AMD acceleration | Named GPU, ROCm/Triton versions, p50/p95, error/recall, memory |
| Large-scale readiness | Load-test result, provider quota, database saturation notes |
| Compliance readiness | Audit export, RBAC mode, retention proof, bias methodology |

This checklist prepares a push; it does not perform one.
