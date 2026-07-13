# Resume intelligence pipeline

The resume path is deliberately split into four independently testable stages:

```text
upload -> bounded format parser -> Fireworks JSON Schema extraction ->
skill ontology + quality gates -> blinded, human-reviewed screening
```

## Supported formats

`ResumeParserPipeline` accepts text/Markdown/CSV, PDF, DOC/DOCX, HTML,
LinkedIn-style JSON exports, and common image formats. Text PDFs use
layout-aware extraction; scanned PDFs and images first try optional local OCR,
then return an explicit `vision_fallback_required` signal for the Fireworks
vision path. Encrypted PDFs accept a request-scoped password. Legacy binary
`.doc` files use an optional sandboxed `antiword`/`catdoc` converter and return a
precise capability-unavailable response when the converter is absent.

The parser caps uploads at `MAX_UPLOAD_SIZE_MB` and extracted text at the LLM
input budget. It never stores a PDF password, raw image payload, or contact
field in the screening text sent to the existing resume scorer.

## Structured Fireworks extraction

`services.resume_extractor.ExtractedResume` is the single strict Pydantic/JSON
Schema contract. The model is injected through `FIREWORKS_RESUME_MODEL` (or the
existing `FIREWORKS_VISION_MODEL`) and must appear in `ALLOWED_MODELS`; no model
ID is silently selected from source code.

For the current [Fireworks Gemma 4 26B A4B IT catalog entry](https://fireworks.ai/models/fireworks/gemma-4-26b-a4b-it), the technical model path
is `accounts/fireworks/models/gemma-4-26b-a4b-it`. Fireworks currently lists
that model as vision-capable and deploy-on-demand rather than Serverless, so the
operator must create/verify the deployment before using it. A Serverless demo
should inject a currently available Serverless model instead.

## Skill and quality gates

`SkillOntologyMapper` canonicalizes aliases such as `py`, `python3`, `k8s`, and
`sklearn` while retaining the original string and confidence. It does not infer
skills from arbitrary prose. `ResumeQualityChecker` scores completeness and date
consistency, then flags warnings or low scores for human review. These gates
provide evidence for the judge without turning extraction into an autonomous
employment decision.

## Batch path

`ResumeBatchProcessor` prepares deterministic, idempotent `custom_id` records
for Fireworks Batch inference. Preparation is network-free; unreadable files
are reported in `skipped` rather than silently dropped. Each row uses the same
strict extraction schema, bounded tokens, and an advisory system instruction.
`submit_batches()` performs the credentialed handoff through the existing
`FireworksBatchClient`: it creates input/output datasets, uploads each JSONL
chunk, and submits one job per bounded chunk. `poll_job()` applies a maximum
poll count and normalizes asynchronous state. The operator supplies
`FIREWORKS_API_KEY`, `FIREWORKS_CONTROL_BASE_URL`, and `FIREWORKS_ACCOUNT_ID`
through a secret manager. Batch state must remain visible as `validating`,
`pending`, `running`, `completed`, or a terminal failure state.

For local parser evidence, run:

```bash
python backend/scripts/benchmark_resume_pipeline.py path/to/fixtures --json
```

The report records parser-only p50/p95/max latency, skipped files, and explicit
`model_calls: 0` / `network_calls: 0`. It is not an end-to-end Fireworks or GPU
throughput claim; use representative, consented fixtures and named hardware
before presenting the `<2 sec` or `1,000+ resumes/day` target as measured.

## OSINT boundary

The OSINT objective is implemented as a consent-gated adapter boundary, not a
scraper. `POST /osint/search` requires manager authority, explicit subject
consent, an allowed professional purpose, HTTPS allowlisted sources, and strips
protected-trait fields. `OSINT_ENABLED` is false by default. No LinkedIn
scraping, Google dorking, sanctions inference, cultural-fit score, or automated
employment decision is enabled by this repository.

## Judge demo

1. Upload a text PDF, DOCX, HTML, and a scanned image; show parser source type
   and any explicit OCR/vision fallback warning.
2. Run structured extraction and show the schema-valid JSON with missing values
   represented as `null`/empty lists.
3. Show `py -> Python` and `k8s -> Kubernetes`, preserving the original form.
4. Show a quality grade and a human-review flag for a missing phone or ambiguous
   date.
5. Prepare a batch manifest, show deterministic IDs and skipped-file reasons,
   then explain that provider submission/polling is credential-gated.

Safe claim: **Fireworks-powered structured resume intelligence with bounded
multi-format parsing, cost-aware Batch preparation, and human review gates.**
