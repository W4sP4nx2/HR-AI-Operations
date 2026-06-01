# Triage → Type-Safe Pydantic AI Classification — Migration Report

**Branch:** `refactor/pydantic-ai-triage` (off `main` @ `8a13d7a`)
**Status:** complete & green — **162 passed, 3 skipped**. Not yet merged to `main`.
**Commits:** `5a66e32` (probe) → `988d5c3` (migration) → `d22c976` (rename to `core/llm_factory.py`)

---

## 1. Why this migration

Triage previously classified by **string-scraping a CrewAI text answer**:

```python
out = str(crew.kickoff()).strip().upper()
for cat in CATEGORIES:
    if cat in out:        # brittle: "not a POLICY issue" → POLICY
        return cat
```

Substring matching over free text is fragile — the model can return prose, and a
category word inside a negation misfires. The replacement makes the classifier
**schema-constrained**: the model is *physically blocked* from returning an
arbitrary category.

## 2. The probe came first (de-risking the assumption)

Before writing any classifier code, an **isolated, CI-safe probe**
(`tests/test_pydantic_ai_probe.py`) verified the installed framework's mechanics
against **pydantic-ai-slim 1.104.0**. Findings (each asserted so a version bump
fails loudly):

| Question | Answer (1.104.0) |
|---|---|
| `agent.run(model_settings={'api_key': x})`? | ❌ **No** — `ModelSettings` holds inference params only (max_tokens, temperature, …), not credentials. |
| How to inject a dynamic BYOK key? | ✅ `AnthropicModel(name, provider=AnthropicProvider(api_key=key))` — a **per-request instance wrapper**. No network on construct. |
| Typed output? | ✅ `Agent(model, output_type=<BaseModel with Literal>)` is schema-constrained. |
| Retry-token-multiplier controllable? | ✅ `Agent(retries=…)` / `run(retries=…)`; `run(model=…)` allows one agent + per-request key. |

**Bonus catch — a silent production regression.** The probe revealed the existing
`chat_agent.build_pydantic_ai_agent` called `AnthropicModel(api_key=…)`, which
1.104 **rejects with `TypeError`**. It was swallowed by a bare `except`, so the
Chat Assistant **degraded to fallback even when a valid key was present** — with
no console signal. Fixed as part of this work.

## 3. What changed (file by file)

### `core/llm_factory.py` (new) — the unified request-scoped factory
```python
def anthropic_model_for_key(api_key: str | None) -> Any | None:
    if not api_key: return None
    # AnthropicModel has no api_key kwarg in 1.104 → provider wrapper:
    return AnthropicModel(settings.claude_model,
                          provider=AnthropicProvider(api_key=api_key))

def get_request_scoped_anthropic_model() -> Any | None:
    if not llm_active(): return None          # MOCK_LLM / DEMO_MODE / BYOK gate
    return anthropic_model_for_key(effective_api_key())
```
Construction makes **no network call**, so building per request is cheap and the
BYOK key stays bound to the single request frame (tenant isolation preserved).

### `agents/chat_agent.py` — regression fixed
Routes through `anthropic_model_for_key(api_key)` instead of the rejected
`AnthropicModel(api_key=…)`. Chat now actually builds with a key.

### `agents/triage_agent.py` — typed classifier
```python
class TriageDecision(BaseModel):
    category: Literal["BENEFITS","POLICY","ONBOARDING","PERFORMANCE","COMPLIANCE","URGENT"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
```
`_llm_classify` builds an `Agent(model, output_type=TriageDecision, retries=1)`
and `await`s it. The validated `rationale` + `confidence` populate the decision
dossier (`classifier_confidence`). CrewAI is removed from triage (still used by the
Resume Screener).

## 4. Defensive primitives (the operational reality check)

| Risk | Guard |
|---|---|
| **Token blow-up** from a huge pasted document on a routing check | Input sliced to `text[:4000]` *before* classification |
| **Retry token multiplier** (validation self-heal resubmits full payload) | `retries=1` — one self-heal, not the default 3–4 |
| **Hung call** | `asyncio.wait_for(..., timeout=20.0)` |
| **Cross-tenant key leak** | Fresh `AnthropicProvider(api_key=effective_api_key())` per request; never a detached background task |
| **Any failure** | Clean handled fallback to the deterministic keyword classifier — no unhandled error state |

## 5. Zero-secret behavior is unchanged

With no live key (the default for CI and demos), `get_request_scoped_anthropic_model()`
returns `None`, `_llm_classify` returns `None`, and the **deterministic keyword
classifier** runs. The eval goldens, `pass@1`, and `pass^k` URGENT-consistency
checks are all green and identical to before.

## 6. Tests

- `tests/test_pydantic_ai_probe.py` — 5 cases documenting the version mechanics.
- `tests/test_llm_factory.py` — 6 cases: factory builds (no network), gated-off →
  `None`, chat builds with a key (regression), triage falls back without a key,
  `TriageDecision` rejects a bad category.
- **Full suite: 162 passed, 3 skipped.** ruff + black + eslint clean.

## 7. Open items (decisions for the maintainer)

1. **⚠️ Model EOL — needs your input.** The configured default
   `settings.claude_model = "claude-sonnet-4-20250514"` reaches **end-of-life
   2026-06-15** (pydantic-ai already emits a `DeprecationWarning`). I have **not**
   guessed a replacement model ID: shipping an unverified model string is the exact
   silent-breakage class this migration set out to prevent. Please confirm the
   target model string (or set `CLAUDE_MODEL` in the environment — it overrides the
   default) and I'll bump it.
2. **Merge** `refactor/pydantic-ai-triage` → `main` when ready (self-contained,
   fully tested).
3. **Live round-trip** — the suite proves construction, gating, schema-constraint,
   and fallback; the one thing it can't cover without a key is an actual LLM call.
   Point a BYOK key at the preview and a live triage will confirm the typed path
   returns `classifier_confidence` in the dossier.

## 8. Recommended sequence

**Resolve (1) → merge (2) → optionally (3).** Bumping the model *before* merge
avoids landing a two-weeks-from-EOL default on trunk.
