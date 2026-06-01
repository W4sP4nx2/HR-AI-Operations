# Skills Evidence — LLMs · Vector DBs · Cost Optimization · Open Source

How the **HR AI Command Center** demonstrates three competency areas, with
concrete file/feature references you can open and verify.

---

## 1. LLMs, fine-tuning & vector databases

### Large language models
- **Multi-framework agent orchestration** over Claude: LangGraph state machines
  (`policy_qa_agent`, `onboarding_agent`), CrewAI crews (`triage_agent`,
  `resume_screener_agent`), and a **Pydantic AI** tool-using chat agent
  (`agents/chat_agent.py`) that calls `search_policy`, `triage_ticket`,
  `get_case_status`, `list_open_cases`, `check_attrition`.
- **Tool/function calling** with typed tool signatures and structured JSON returns;
  **streaming** responses over SSE (`POST /chat/stream`) with token + tool-call events.
- **Systematic LLM I/O contracts** — every agent has a validated Pydantic
  input/output schema (`agents/contracts.py`, `AGENT_SPECS`), checked in CI
  (`tests/test_agent_contracts.py`). LLM outputs are validated, not trusted blindly.
- **Graceful degradation** — deterministic fallbacks when no API key is present, so
  the system is testable and demoable without spend.

### Vector databases & RAG
- **End-to-end RAG pipeline** (`pipelines/rag_pipeline.py`): pypdf extraction →
  token-approximate chunking (512/50) → **sentence-transformers MiniLM embeddings**
  → **Qdrant** vector store (cosine, top-k=5) → Claude synthesis with citations.
- **Vector store abstraction** (`core/vectorstore.py`): collection management,
  upsert, similarity search, and filtered scroll — with graceful empty-result
  degradation when Qdrant is offline.
- **Policy ingestion control plane** — upload PDFs (`POST /policies/ingest`),
  registry table tracking chunks/char counts, list/delete (data control).
- **Embedding engineering** (`core/embeddings.py`): a deterministic **hashing
  bag-of-words fallback embedding** when sentence-transformers is unavailable —
  keeps cosine similarity meaningful with zero heavy deps.

### Fine-tuning / classical ML adjacency
- A trained **scikit-learn `RandomForestClassifier`** for attrition with feature
  attribution and plain-English explanations (`models/attrition_model.py`) — the
  model-lifecycle muscle (train, predict, explain, version) that transfers directly
  to fine-tuning workflows. Roadmap: dataset upload + scheduled retrain + model
  registry (MLflow) in [SCALING.md](./SCALING.md).

> **Stack:** Anthropic Claude · Pydantic AI · LangGraph · CrewAI ·
> sentence-transformers · Qdrant · scikit-learn.

---

## 2. Cost optimization for AI workloads

Cost is designed in, not bolted on. Evidence and plan:

### Already built
- **Zero-spend by default** — the entire system runs in a **deterministic fallback
  mode** (keyword triage, hashing-embedding scoring, templated explanations) with
  **no API key**, so development, CI, and demos cost **$0**. LLM calls happen only
  when explicitly enabled.
- **Capability-aware execution** — a `degraded|full` mode flag and an
  `ok|error|unavailable` status contract mean the app never silently burns calls on
  a misconfigured path.
- **Lean retrieval** — bounded top-k (5), char-capped intake (20k) to keep prompt
  sizes and token spend predictable.
- **Right-sized models** — config-driven model selection so a cheaper/faster model
  can serve high-volume classification while a capable model handles synthesis.

### Designed & documented (see [PITCH.md](./PITCH.md) §4, [PIPELINE_AND_UX.md](./PIPELINE_AND_UX.md))
- **Prompt caching** (Anthropic) on the system prompt + policy context — the single
  biggest lever for repeated Q&A; called out as a first-adopt feature.
- **Semantic answer cache** — key Policy-Q&A answers by query embedding
  (cosine ≥ 0.97 ⇒ cache hit), collapsing the most expensive path to a Redis lookup.
- **Batch API** for bulk resume screening / attrition scoring at lower unit cost.
- **Read-through cache** (TTL + jitter) for hot polled endpoints, and **token-bucket
  rate limiting** per user/tenant to cap runaway spend.
- **Async task queue + autoscaling on queue depth (KEDA)** — pay for compute only
  when work exists; scale-to-zero for idle tenants ([SCALING.md](./SCALING.md)).
- **Audit cold-storage tiering** — partition + archive old audit data to cheap
  object storage rather than hot DB.

> The throughline: **make the expensive path optional, cached, batched, and
> right-sized** — and prove value before spending.

---

## 3. Open-source contributions & AI initiatives

This project is built **to be open-sourced and contributed to**:

- **MIT licensed** ([LICENSE](./LICENSE)) and self-hostable (SQLite → Postgres, no
  lock-in).
- **Contributor-ready** — [CONTRIBUTING.md](./CONTRIBUTING.md) with quick start,
  the CI gates (`ruff`/`black`/`pytest`), conventions, and labelled **good first
  issues**.
- **Reproducible onboarding** — `python -m scripts.seed_data` generates sample
  policies, cases, and a chat transcript so a new contributor sees a working system
  in one command, **with zero secrets**.
- **Launch-ready** — [OPEN_SOURCE_LAUNCH.md](./OPEN_SOURCE_LAUNCH.md): pre-flight
  secret/secret-scan checklist, GitHub setup, topics, and a ready-to-post LinkedIn
  announcement.
- **Engineering rigor that invites collaboration** — typed contracts, a tested CI
  pipeline (lint + test + Docker build), graceful-degradation guarantees, and a
  documented architecture ([IMPLEMENTATION.md](./IMPLEMENTATION.md),
  [SCALING.md](./SCALING.md), [AGENT_PLAYBOOK.md](./AGENT_PLAYBOOK.md)).
- **Mission-driven** ([MISSION.md](./MISSION.md)) — an *AI research/ethics* stance
  baked into the product: human-in-the-loop by default, audit everything, advisory-
  not-punitive AI, least privilege. The kind of "trustworthy AI" initiative the
  community needs more of.

### Direct upstream surface area
The project deliberately uses and exercises active OSS AI projects —
**Pydantic AI, LangGraph, CrewAI, Qdrant, sentence-transformers, FastAPI** —
producing real-world usage, reproductions, and a reference implementation that can
feed issues/PRs back upstream.

---

## One-line summary

> A production-shaped, MIT-licensed AI system that builds **RAG over a vector DB**,
> **orchestrates LLM agents with validated contracts**, is **engineered for $0-by-
> default and a documented cost-optimization path**, and ships **open-source-ready**
> with seed data, CI, contributor docs, and a trustworthy-AI mission.

| JD requirement | Strongest evidence |
|----------------|--------------------|
| LLMs / fine-tuning / vector DBs | RAG + Qdrant + MiniLM (`rag_pipeline.py`), Pydantic AI tool agent, RandomForest model lifecycle |
| Cost optimization for AI workloads | $0 fallback mode + prompt caching, semantic cache, batching, KEDA autoscaling plan |
| Open-source / AI initiatives | MIT + CONTRIBUTING + seed + launch guide + trustworthy-AI MISSION |
