# Fireworks Usage, Model Choice, and Guardrail Evaluation

## Verdict

The Fireworks dashboard showing `0 req/s` does not mean the integration is
broken. `CURRENT 0 req/s` is an instantaneous rate, not a cumulative usage
counter. Fireworks Serverless rate limiting is token-based: total prompt TPM,
uncached prompt TPM, and generated TPM. Requests can still receive `429` or
`503` even when an observed rate appears low because limits are adaptive and
load shedding is separate from rate limiting.

References:

- [Fireworks Serverless rate limits](https://docs.fireworks.ai/serverless/rate-limits)
- [Fireworks Serverless overview](https://docs.fireworks.ai/serverless/overview)
- [Fireworks account quotas](https://docs.fireworks.ai/guides/quotas_usage/account-quotas)

## Why `glm-5p2`

This is the actual decision chain:

```text
runtime ALLOWED_MODELS
  -> runtime settings selected_model, when active and allow-listed
  -> card family preference match
  -> role size ranking
  -> Fireworks request
```

`glm-5p2` is not hardcoded in the repository. It was injected into the live
process allow-list and selected by runtime settings. With only one allowed model
it becomes the model for every route, regardless of role. For a standard or
premium policy route, the cost router intentionally selects the largest allowed
model.

Therefore:

- `glm-5p2` is a valid current live route.
- It is GLM 5.2, not Gemma 4 26B-A4B.
- The current code proves configuration and one live request, not that GLM 5.2
  is better than a smaller model.
- The architecture diagram should say `Fireworks Serverless / GLM 5.2` unless
  the allow-list is changed to a tested Gemma model.

The defensible product argument is quality-first policy synthesis: policy Q&A
has grounding, citations, structured output, and human-review triggers, so a
larger model is a reasonable default while the gold-set comparison is pending.
It is not a measured latency or cost-optimality claim.

## What Counts as Usage

```text
request
  -> input tokens
  -> cached input tokens, when provider prompt cache hits
  -> generated output tokens
  -> response status: 2xx, 429, 503, or other error
  -> request latency and provider rate-limit headers
```

Fireworks bills Serverless by input tokens, cached input tokens, and generated
tokens. The provider exposes prompt/generated usage and rate-limit headers on
responses. The application currently records a local estimate:

```text
estimated_usd = (input_tokens + output_tokens) / 1000 * local_tier_rate
```

The dashboard's `provider_calls`, `input_tokens`, `output_tokens`, cache rate,
and estimated dollars are application-observed telemetry. They are not the
Fireworks account invoice or account credit balance. Account billing and quota
data must be read from the Fireworks dashboard or `firectl quota list`.

Current live evidence already obtained:

| Signal | Result | Meaning |
|---|---:|---|
| Live provider calls | 1 | One request reached Fireworks |
| Observed tokens | 160 | Application response usage estimate |
| Local cost estimate | `$0.000144` | Internal estimate, not invoice |
| Chat mode | `full` | Provider response completed |
| Certification | passed | Structured response passed local certifier |
| Dashboard current req/s | `0` when idle | Expected instantaneous state |

## Guardrail Chain

```text
input
  -> auth/RBAC
  -> Unicode/control normalization
  -> PII redaction + prompt-injection signal
  -> input token budget
  -> model allow-list validation
  -> cost tier / budget circuit breaker
  -> provider request
  -> JSON schema validation
  -> PII re-check and redaction
  -> confidence / required-field / forbidden-field checks
  -> grounding and citation checks for RAG
  -> certified A2A envelope
  -> audit + metrics
```

Implemented guardrails include:

- Provider construction stays in explicit choke points.
- Model IDs must come from `ALLOWED_MODELS`.
- Input and output token budgets are bounded before provider spend.
- Static system context must precede user context for cache locality.
- JSON-schema responses are certified before another agent consumes them.
- PII is checked again after generation.
- RAG answers require source/grounding evidence.
- Budget breaker can force economy routing and extend cache TTL.
- Human review remains available for low confidence, urgent, conflicting, or
  high-risk outcomes.
- No detached background task retains request-scoped provider keys.

## Evaluation Status

| Evaluation | Status | What it proves |
|---|---|---|
| Model allow-list and request shape | Tested | Unapproved IDs, malformed schemas, and invalid sampling values fail locally |
| Certifier schema/PII behavior | Tested | Invalid structured output is rejected or redacted |
| Cost attribution math | Tested | Tier totals, cache skips, token estimates, and local budget state are coherent |
| Cost-control A/B benchmark | Tested | Controlled path reduces avoidable calls in the deterministic benchmark |
| No hardcoded provider clients/hosts | Tested | Static guard prevents provider bypasses |
| No detached key-bearing tasks | Tested | AST guard blocks `create_task`, `ensure_future`, and `BackgroundTasks` in guarded paths |
| Live Fireworks chat | Verified once | One real response completed with `glm-5p2` |
| Fireworks dashboard parity | Not proven | Local ledger is not linked to provider billing export |
| Provider rate-limit headers | Gap | Current app does not expose a dedicated header ledger for prompt/generated limits |
| 429/503 load behavior | Not proven | Needs controlled load test and retry/backoff evidence |
| GLM 5.2 versus smaller model | Not proven | Needs a fixed HR gold set and latency/cost comparison |
| Fireworks Batch completion | Not proven | Current product state is pending, not completed |

## Promotion Evaluation for `glm-5p2`

Run the same redacted set through `glm-5p2` and a smaller allow-listed model.
Do not compare only green UI states.

```text
golden HR questions/tickets
  -> identical prompt and RAG context
  -> model A: glm-5p2
  -> model B: smaller candidate
  -> certifier
  -> groundedness/citation scorer
  -> latency and token capture
  -> human adjudication for disagreements
```

Required measurements:

```text
schema_pass_rate          = valid_structured_outputs / total_outputs
grounded_rate             = cited_answers_supported / cited_answers
citation_precision        = supported_citations / returned_citations
fallback_rate             = fallback_requests / total_requests
human_escalation_rate     = escalated_cases / total_cases
provider_cost_per_case    = provider_spend / completed_cases
p50/p95_latency           = percentile(end_to_end_latency)
```

Proposed promotion gates, pending business approval:

- `schema_pass_rate = 100%` for structured agent contracts
- `grounded_rate >= 99%` on the policy gold set
- zero PII leakage in certified outputs
- no regression in urgent-ticket recall
- smaller model must reduce cost or latency without exceeding the approved
  quality-loss threshold
- 429 and 503 handling must be observable and bounded

These are proposed release gates, not current pass claims.

## Rate-Limit Operations Playbook

1. Watch Fireworks `429` separately from `503`; a `429` is quota/rate pressure,
   while a `503` can be provider load shedding.
2. Record response status, model, request ID, input/output tokens, cached tokens,
   latency, and rate-limit headers without storing prompt or key material.
3. Retry `429` with bounded exponential backoff and jitter.
4. Treat repeated `503` as capacity pressure; fall back or use a tested
   Priority/dedicated route rather than retrying indefinitely.
5. Keep prompt prefixes stable and preserve hashed session affinity to improve
   cache locality.
6. Compare provider telemetry with the local ledger; never label local estimates
   as account usage.

## Immediate Engineering Gaps

1. Add a provider-response telemetry record for `fireworks-prompt-tokens`,
   `fireworks-cached-prompt-tokens`, `X-Ratelimit-*`, HTTP status, request ID,
   and latency.
2. Add a redacted live smoke test that asserts the configured model and records
   usage metadata without printing the key or prompt.
3. Run a 50-100 case model comparison for GLM 5.2 versus the intended smaller
   candidate.
4. Add a controlled 429/503 test with fake provider responses before changing
   retry counts.
5. Connect Fireworks billing/quota export separately from application metrics.

Until those gaps are closed, the correct claim is:

> Fireworks Serverless is live and guarded for one verified GLM 5.2 route. The
> application measures local token/cost estimates and certification outcomes;
> provider account usage, rate-limit behavior under load, and model superiority
> remain evidence-gated.
