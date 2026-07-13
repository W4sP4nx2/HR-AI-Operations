# Compact Project Context

Use this file when handing a narrow task to Qwen Coder, Codex, or another local
assistant. Paste this first, then paste only the specific file, function
signature, failing test, or error message needed for the task.

## Product

HR AI Command Center is an open-source, audit-first control plane for HR agent
workflows. It is not a general chatbot. The app routes HR cases, answers policy
questions from indexed evidence, screens resumes, coordinates onboarding,
produces attrition advisories, and writes reviewable audit records.

The product rule is:

> Fleet acts, policy evidence grounds, governance controls.

## Demo Flow

Prioritize these workflows for demos and pull requests:

1. Policy Q&A: upload or seed policies, embed chunks, retrieve top-k evidence,
   answer with citations, confidence, and audit.
2. Case triage: classify incoming HR requests, assign priority, create/update a
   case, escalate sensitive outcomes.
3. Resume screening: blind protected fields, score against a job description,
   show matched/missing skills, require recruiter review.
4. Onboarding orchestration: run staged tasks, pause at human approval, resume
   only after approve/reject.
5. Attrition advisory: produce local risk score and explanation, never trigger
   an adverse employment action automatically.

## Architecture Contract

- Backend: FastAPI, async routes, Pydantic models, agent modules, audit storage.
- Frontend: Next.js dashboard with auth, policies, agents, cases, analytics, and
  Batch status.
- Retrieval: Postgres + pgvector in production; local vector store for zero-dep
  development.
- Inference: deterministic fallback first; Fireworks online for interactive
  inference; Fireworks Batch for asynchronous bulk workloads; optional AMD/vLLM
  path only with named-hardware evidence.
- Security: model IDs and provider URLs are environment-injected. No hardcoded
  keys, hosts, or model defaults.
- Privacy: redact text PII before storage and model egress. Scanned resume image
  egress is disabled unless `ENABLE_RESUME_VLM=true`.
- Governance: every sensitive agent output must be auditable and human
  reviewable.

## Current Implementation Boundary

Implemented and test-covered:

- deterministic no-key application flow;
- policy RAG with chunk retrieval and citation guardrails;
- Fireworks model factory allowlist and structured request contracts;
- Fireworks Batch JSONL preparation, submit/status/watch plumbing, and metadata
  ledger;
- scanned-resume VLM path behind explicit consent/config gates;
- PII redaction before agent/model dispatch and audit persistence;
- onboarding human approval checkpoint;
- CPU vector benchmark.

Environment-gated before public performance claims:

- live Fireworks structured, VLM, and Batch runs;
- AMD/ROCm vector or vLLM benchmark on named hardware;
- distributed load test for large concurrency;
- provider cost evidence.

## Coding Rules

- Do not rewrite factories or shared clients unless the task is explicitly about
  those files.
- Keep changes narrow: one module, one test file, one behavior at a time.
- Use typed Pydantic outputs for agent contracts. Do not parse free-form model
  text when a JSON schema can be used.
- Preserve deterministic fallback behavior when provider credentials are absent.
- Add or update tests with every behavior change.
- Do not claim compliance, AMD speedup, cost savings, or production scale unless
  current evidence exists in the repo.

## Useful Commands

Backend:

```bash
cd backend
python -m black --check .
python -m ruff check .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -q
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

Security and release:

```bash
gitleaks dir . --no-banner --config .gitleaks.toml --redact --exit-code 1
python3 scripts/check_docs.py
python3 scripts/verify_platform_manifests.py
JWT_SECRET="$(openssl rand -hex 32)" docker compose -f docker-compose.prod.yml config --quiet
```

Vector benchmark:

```bash
cd backend
python -m scripts.benchmark_vector_search \
  --rows 10000 --dimension 384 --queries 30 --top-k 5 --enforce-target
```

Fireworks smoke test only in a credentialed environment:

```bash
cd backend
python -m scripts.fireworks_smoke
```

## Good Assistant Prompt Shape

Use this shape instead of pasting the whole repository:

```text
Context: HR AI Command Center. Preserve deterministic fallback, audit logging,
PII redaction, typed Pydantic outputs, and provider allowlist routing.

Task: <one narrow change>

Relevant contract:
<function signature, route, model, or test expectation>

Existing file:
<only the needed excerpt>

Return:
<patch or one function, plus the test to add>
```

## Stop Conditions

Cut or mock a feature for demo if it takes more than 30 minutes and is not in
the core flow: Policy Q&A, Case Triage, Resume Screening, Onboarding Approval,
or Audit Evidence.

Do not push to `main` until `OPEN_SOURCE_LAUNCH.md` and
`COMPETITIVE_QUALITY_GATE.md` are satisfied for the claims being published.
