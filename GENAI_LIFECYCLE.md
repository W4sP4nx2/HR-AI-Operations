# GenAI Lifecycle

This document separates what the product executes today from future training
work. Inference is implemented. Pretraining is supplied by model providers.
Post-training is not performed. Human interaction labels are collected for
analysis but are never silently fed back into a model.

## Building blocks

| Layer | Input | Transformation | Output | Control |
|---|---|---|---|---|
| Intake | text, PDF, URL, typed numeric features | parsing, size limits, Unicode/whitespace normalization | typed agent input | Pydantic contracts |
| Safety | fuzzy user text and retrieved documents | control-character removal, injection detection, PII redaction for persistence | flags + redacted audit representation | guardrails |
| Context | chat history, policy chunks, tool results | bounded history, top-k retrieval, title boost | prompt context | token/character caps |
| Inference | transformed prompt + versioned system prompt | provider/model routing, controlled parameters | text or typed schema | role policy |
| Verification | schema, citations, confidence, safety state | hard gates + transparent weighted score | accept/review decision | human oversight |
| Collection | reroutes and manager decisions | append-only records, aggregation | analysis statistics | analyst/manager RBAC |

Authoritative code:

- Prompts: `backend/agents/prompts.py`
- Controls and transformations: `backend/core/genai_lifecycle.py`
- Provider routing: `backend/core/llm_factory.py`
- Lifecycle analysis API: `GET /lifecycle`
- Baseline comparisons: `backend/models/baseline_evaluation.py`

## Fuzzy inputs and transformations

`transform_fuzzy_input()` applies deterministic, recorded transformations:

1. NFKC Unicode normalization so full-width and compatibility characters have a
   stable representation.
2. Removal of non-printing control characters.
3. Horizontal-space and excessive-newline normalization.
4. Role-specific character truncation.
5. Prompt-injection signal detection.

The returned object states which transformations occurred. Metrics retain only
role and boolean flags, never prompt text. Transformation does not silently
remove protected meaning or pretend injection detection makes unsafe content
trusted.

## Prompts and controlled parameters

Every generative path references a `PromptSpec` with a stable id, semantic
version, text, and audit hash. Every role has an `InferencePolicy`:

| Role | Max input | Max output | Temperature | Timeout | Retries |
|---|---:|---:|---:|---:|---:|
| Chat | 12,000 chars | 800 tokens | 0.0-0.2 | 30s | 1 |
| Triage | 4,000 | 250 | 0.0 | 20s | 1 |
| Skill validator | 4,000 | 500 | 0.0 | 25s | 1 |
| Policy RAG | 16,000 | 600 | 0.0 | 30s | 1 |
| Attrition explanation | 2,000 | 250 | 0.0-0.1 | 20s | 0 |

Callers may request fewer tokens or a temperature inside the envelope. Requests
outside it are clamped. API credentials are not inference parameters and remain
request/provider scoped.

## Comparison and scoring

The three CPU-safe baselines remain the comparison floor:

- keyword triage,
- resume skill overlap,
- transparent attrition rules.

See `BASELINE_MODELS.md` for current metrics and discard gates.

`score_output()` reports:

- schema validity: 35%,
- grounding/citation evidence: 30%,
- safety gate: 25%,
- bounded confidence: 10%.

The weighted number is diagnostic. Schema and safety are hard gates; grounding
failure always requires review even if the weighted score appears high.

## Data collection and analysis

The product collects two append-only human signals:

- `triage_override` audit events when a person reroutes a ticket;
- accepted/rejected/edited retention feedback.

`GET /lifecycle` returns counts, distributions, baseline comparisons, prompt
versions, and lifecycle status to analysts. It deliberately reports
`training_readiness.ready=false` because:

- absence of an override is not a confirmed correct label;
- interaction telemetry is selection-biased;
- manager acceptance is not a ground-truth attrition outcome;
- consent, retention, temporal split, representativeness, and subgroup review
  are not yet established.

## Lifecycle stages

### 1. Inference: implemented

Transform input, assemble bounded context, select a harness-approved model, apply
controlled parameters, validate outputs, audit the action, and route uncertain
results to people.

### 2. Pretraining: external

The project does not pretrain foundation models. Fireworks or the self-hosted
AMD/vLLM service receives model identifiers only from `ALLOWED_MODELS`.

### 3. Post-training: not executed

A future LoRA/SFT/RFT job must consume a governed, versioned dataset and produce
an independently evaluated artifact. No production feedback loop trains itself.

### 4. Data labeling: implemented as collection

Human decisions are recorded append-only and analyzed. Promotion to training
data requires sampling review, adjudication guidance, dataset versioning,
train/validation/temporal-test splits, and bias approval.

## Telling points

- The project is honest about inference versus training.
- Model ids and provider hosts have no code defaults.
- A high scalar score cannot override failed schema, safety, or grounding gates.
- Labels are evidence to inspect, not automatic rewards.
- Deterministic baselines remain functional with no key, network, Torch, or GPU.
