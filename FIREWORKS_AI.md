# Fireworks AI Product Vision and Implementation Contract

## Vision

HR AI Command Center is an audit-first orchestration layer for HR work:

- **Policies ground decisions.**
- **Agents turn requests into reviewable work.**
- **Cases carry ownership and state.**
- **Humans approve sensitive outcomes.**
- **Fireworks provides the accelerated model inference plane.**

Fireworks does not replace the workflow engine, database, policy index, RBAC, or
audit trail. It powers bounded model tasks inside those controls. The product
continues to run in deterministic mode when no API key is configured.

Serverless is the default by design, not because it is easier. For this HR
system, Fireworks Serverless is the compliance-enforced inference plane:
interactive and batch model calls get pay-per-token cost control, managed model
updates, API-level structured output, and burst scaling while the application
keeps policy evidence, audit state, RBAC, and human approval in its own database.
Every schema-constrained Fireworks response is certified by
`core.fireworks_certifier.FireworksOutputCertifier` before it reaches HR
workflows.

Runtime proof comes from the A2A Certified Envelope protocol in
`core.a2a_envelope`. Provider-to-agent and agent-to-agent handoffs carry the
payload, certification result, latency, token count, model id, trace id, and
violation list. `/lifecycle/fireworks` exposes a rolling last-100 snapshot with
pass rate, average/p95 latency, PII redaction count, token count, recent
envelopes, and AMD GPU probe status.

## Workload routing

| Workload | Fireworks mode | Why |
|---|---|---|
| Policy Q&A, chat, triage | Serverless | Interactive, pay-per-token, streaming and tool calls |
| Resume/JD extraction | Serverless VLM | Images plus schema-constrained JSON |
| Bulk resume processing and evals | Batch | Async workload, lower unit cost, automatic prompt caching |
| Fine-tuned extraction or reserved latency | Dedicated | Version control, LoRA support, predictable capacity |

Routing algorithm:

1. If the result is not needed synchronously, use Batch.
2. If the model is custom/fine-tuned or capacity must be reserved, use Dedicated.
3. Otherwise, start on Serverless and promote only after measured rate-limit,
   latency, stability, or cost evidence.

The executable form is `core.fireworks.choose_serving_mode`.

## Serverless vs. bare metal boundary

Use Serverless for policy Q&A, triage, chat, batch resume screening, resume VLM
extraction, and attrition explanations. These are bursty, auditable,
schema-bound workloads where predictable per-token spend matters more than owning
an always-on GPU.

Use bare metal or self-hosted AMD vLLM only for:

- privacy-sensitive SFT/RLHF data processing where raw employee training data
  cannot leave the controlled environment;
- Triton/HIP kernel benchmarking and product bottleneck validation on named AMD
  hardware;
- sub-100ms latency-critical paths where serverless variance violates a measured
  SLA;
- dedicated capacity after production volume proves the fixed GPU cost is lower
  than serverless spend.

Never use Serverless for raw employee training-data experimentation,
uncertified outputs, or any flow where the schema, PII, confidence, and audit
objectives are unknown.

## Agent use cases

### Policy Q&A

`query -> redact -> embed -> pgvector top-k -> Fireworks synthesis -> citation/confidence -> audit`

- Retrieve only relevant policy chunks.
- Put stable system and policy context first to improve prompt-cache reuse.
- Hash the chat session before using it for `x-session-affinity` or `user`.
- Route confidence below `CONFIDENCE_THRESHOLD` to human review.

### Case triage

`request -> injection/PII guard -> Fireworks JSON schema -> routing rules -> case -> audit`

- Prefer a small allowlisted model.
- Require category, priority, owner, rationale, and confidence.
- Never let the model approve an adverse employment action.

### Resume parsing and screening

`PDF text extraction -> scanned-page detection -> page images -> Fireworks VLM -> typed fields -> blind scoring -> recruiter review`

- Fireworks VLMs accept images, not PDFs. Convert scanned pages before inference.
- Keep each request at 30 images or fewer and below the documented image limits.
- Use structured output for extraction; score candidates with deterministic,
  reviewable criteria after protected fields are removed.
- Measure field-level precision, recall, F1, missing-field rate, and recruiter
  override rate against a governed golden set.

### Bulk and evaluation jobs

`records -> validated JSONL -> Fireworks Batch -> results/errors -> evaluation gates`

Use:

```bash
cd backend
export ALLOWED_MODELS=tenant/model-id
python -m scripts.fireworks_prepare_batch input.json output.jsonl \
  --model tenant/model-id
```

This command needs no key and performs no network call. Upload and execute the
dataset only from an approved operator environment.

Live submit/status uses the same prepared JSONL with fully injected control-plane
configuration:

```bash
export FIREWORKS_API_KEY=...
export FIREWORKS_CONTROL_BASE_URL=...
export FIREWORKS_ACCOUNT_ID=...
python -m scripts.fireworks_batch_job submit output.jsonl \
  --job-id resume-demo-001 --model tenant/model-id \
  --input-dataset resume-demo-input --output-dataset resume-demo-output
python -m scripts.fireworks_batch_job status --job-id resume-demo-001
```

Batch jobs are asynchronous. The Analytics workspace shows `Pending` as an
expected queue state, explains that interactive screening remains available,
and polls a tracked job every 10 seconds until it reaches a terminal state.
Provider states are normalized before they reach the browser, and account paths
or credentials are never returned.

Fireworks documents the lifecycle as validating, pending, running, completed,
failed, or expired. A job that stays pending for more than 30 minutes should be
checked for model batch support, JSONL validity, and quota before escalation.
See [Fireworks Batch inference](https://docs.fireworks.ai/guides/batch-inference).

## Token cost and serverless usage telemetry

The product now exposes two separate cost surfaces because they answer different
questions:

| Surface | Source | What it proves |
|---|---|---|
| Application-observed estimate | `core.cost_attribution` and `/metrics/inference-usage` | Token budget, provider-call count, cache/prefilter savings, tier spend, and budget circuit-breaker state for workflows this app routed |
| Fireworks account billing | Fireworks billing usage export / `firectl billing get-usage` | Rated account usage grouped by serverless model, API key, deployment, or annotations |

In local preview the Analytics card must say `local estimate`, show `$0.000000`
when no live provider call occurred, and mark Fireworks billing export as not
ready unless `FIREWORKS_ACCOUNT_ID` and `FIREWORKS_API_KEY` are present. Live
Serverless requests include non-secret attribution tags:

```text
team=hr,project=hr-command-center,environment=<ENVIRONMENT>
```

These tags line up with Fireworks' documented custom usage grouping dimensions
without sending employee or case context to the billing plane.

## Functional requirements

| ID | Requirement | Acceptance |
|---|---|---|
| FW-001 | All live model construction uses one factory | Static guardrail finds no bypass |
| FW-002 | Keys, base URLs, and model IDs are injected | No provider host, key, or production model ID in runtime code |
| FW-003 | Only allowlisted models can be selected | Unknown model fails before network I/O |
| FW-004 | Chat sessions use privacy-safe cache affinity | Stable hashed token; raw session/employee ID absent |
| FW-005 | Extraction supports JSON Schema | Request contains `response_format.type=json_schema` |
| FW-006 | Resume vision input is bounded | 1-30 HTTPS/data-image pages; base64 payload below 10MB |
| FW-007 | Bulk jobs produce valid JSONL | Unique `custom_id`; valid `body`; errors are reviewed separately |
| FW-008 | Dedicated cold starts are explicit | `DEPLOYMENT_SCALING_UP` is recognized; workers use bounded backoff |
| FW-009 | No-key operation remains useful | RAG, triage, cases, scoring, and audits have deterministic paths |
| FW-010 | Fine-tuning is evidence-gated | Prompt/RAG baseline, golden set, bias gate, and cost case exist first |

Run the no-key contract:

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  -p pytest_asyncio.plugin tests/test_fireworks_workloads.py -q
```

Inspect the runtime contract at `GET /lifecycle/fireworks`. It reports readiness,
use cases, routing, and promotion gates without returning credentials.

## Hard scaling strategy

### Interactive traffic

- Keep FastAPI stateless and move agent work longer than the request budget to a
  queue.
- Use `x-session-affinity` for related requests and place stable prompt prefixes
  first.
- Cache policy retrieval by tenant, policy version, normalized query, and prompt
  version.
- Bound tokens, tool iterations, retries, concurrency, and per-tenant spend.
- Observe prompt, cached-prompt, generated-token, p50/p95 latency, tool failure,
  fallback, and human-escalation rates.

### Bulk traffic

- Buffer resume imports and evaluations into bounded JSONL datasets.
- Use deterministic custom IDs for idempotent reconciliation.
- Treat result and error datasets as separate workflow states.
- Retry only unfinished or retryable rows; do not replay successful decisions.

### Dedicated deployments

- Set `min_replica_count >= 1` for user-facing latency guarantees.
- Scale on the measured bottleneck: concurrent requests, prompt TPS, generated
  TPS, or RPS.
- A scale-from-zero request returns 503 and is not queued by Fireworks. Background
  workers may use bounded exponential backoff; interactive requests should return
  a clear unavailable/retry response rather than wait for minutes.

### GPU kernel boundary

The local Triton path already tests larger dimension tiles, multiple warps,
multiple rows per program, and grid mapping by
`ceil(candidate_count / rows_per_program)`. Keep it disabled until named-hardware
benchmarks prove correctness and at least `GPU_KERNEL_MIN_SPEEDUP` end-to-end.
Fireworks and pgvector remain the default production acceleration paths.

## Evaluation and fine-tuning gate

Start with prompting, retrieval, schemas, and a 100-500 example golden set.
Consider managed LoRA only when:

1. schema-valid output and field F1 remain below target;
2. failures are systematic rather than missing-policy or data-quality failures;
3. enough representative, consented, versioned examples exist;
4. bias, privacy, deletion, and human-oversight controls are documented;
5. projected volume justifies training and dedicated-serving cost.

Do not train on raw interaction telemetry. Manager edits and overrides are
analysis signals until they pass governance, sampling, and labeling review.

## Future sequence

1. Keep the current no-key tests and deterministic demo green.
2. Inject a Fireworks base URL and allowlisted model IDs; run the live smoke test.
3. Add scanned-PDF page conversion only when real resume samples demonstrate the
   text extractor is insufficient.
4. Add token/cache metrics and one guarded live integration test.
5. Run 50-user chat and bulk-resume load tests; record p95, cost, and fallback.
6. Move bulk workloads to Batch.
7. Move only proven steady/custom workloads to Dedicated.
8. Fine-tune only after the evaluation gate above passes.

## Fireworks references

- [Introduction](https://docs.fireworks.ai/getting-started/introduction)
- [Serverless overview and prompt caching](https://docs.fireworks.ai/serverless/overview)
- [Structured outputs](https://docs.fireworks.ai/structured-responses/structured-response-formatting)
- [Vision models and PDF page conversion](https://docs.fireworks.ai/guides/querying-vision-language-models)
- [Batch inference](https://docs.fireworks.ai/guides/batch-inference)
- [Dedicated autoscaling](https://docs.fireworks.ai/deployments/autoscaling)
- [Fine-tuning overview](https://docs.fireworks.ai/fine-tuning/finetuning-intro)
