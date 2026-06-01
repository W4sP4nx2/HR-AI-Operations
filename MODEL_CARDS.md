# Model Cards

One card per agent: what it does, inputs/outputs, data, limitations, fairness, and
the human-oversight workflow. Required for EU AI Act ("high-risk" HR systems), NYC
LL144, and general responsible-AI practice. Cards are derived from the validated
contracts in [`backend/agents/contracts.py`](./backend/agents/contracts.py).

> **Universal oversight rule:** no agent makes a fully automated adverse decision.
> Sensitive actions pause for a human; advisory outputs are labelled as such.

---

## Triage Agent (CrewAI / keyword fallback)
- **Purpose:** classify an HR ticket and route it.
- **Input → Output:** `TicketInput` → `TriageResult {category, case, resolution?}`.
- **Logic / data:** LLM classifier when a key is set; otherwise a transparent
  keyword classifier. No training data stored.
- **Fairness / safety:** harassment / discrimination / retaliation → **URGENT →
  human**, bypassing the manager. Every classification audited.
- **Limitations:** keyword fallback is literal; ambiguous tickets may mis-route →
  a human reviews non-auto-resolved cases.
- **Human oversight:** URGENT always escalates; only POLICY auto-resolves (via RAG).

## Policy Q&A Agent (LangGraph + RAG)
- **Purpose:** answer policy questions from ingested documents, with citations.
- **Input → Output:** `TicketInput` → `PolicyAnswer {answer, source_documents,
  confidence_score, needs_review}`.
- **Logic / data:** retrieval over *your* policy PDFs (pgvector top-k cosine, MiniLM/hashing embeddings);
  Claude synthesis when enabled. Answers grounded in retrieved text only.
- **Fairness / safety:** prompt-injection refused + logged; PII in queries redacted
  before audit; **`confidence < 0.7` → `needs_review`** (routed to a human).
- **Limitations:** quality depends on ingested docs; no docs → "no relevant policy"
  rather than a guess.
- **Human oversight:** low-confidence answers flagged; never an authoritative legal ruling.

## Resume Screener (CrewAI / embedding fallback)
- **Purpose:** score a resume against a JD as **decision support**.
- **Input → Output:** `ResumeInput` → `ResumeScore {score, recommendation,
  reasoning, matched_skills, missing_skills, blinded}`.
- **Logic / data:** semantic similarity + skill keyword match (0.6/0.4); CrewAI
  narrative when enabled. No candidate data retained beyond the audit summary.
- **Fairness / safety:** **demographic blinding** removes name, age/graduation
  year, pregnancy/maternity, gender, race, marital status **before scoring** →
  name-blind identical scores (CI-tested). Reasoning never cites age/year.
- **Limitations / metrics:** a heuristic scorer, **not** a validated predictor of
  job performance; intended to rank, not to reject. Disparity ratio target **< 1.1**
  (name-blind test asserts parity).
- **Human oversight:** **never auto-rejects** — a recruiter makes the call; FCRA
  adverse-action notices are a downstream human process.

## Onboarding Orchestrator (LangGraph)
- **Purpose:** run the new-hire checklist with a human checkpoint.
- **Input → Output:** `NewHireInput` → `OnboardingResult {status, task?, state?}`.
- **Logic / data:** deterministic state machine; durable pause for approval.
- **Fairness / safety:** state-changing steps require **manager approval**;
  approval **and** rejection captured in the audit with reason + actor id.
- **Limitations:** connectors (Workday/ServiceNow) are simulated until wired.
- **Human oversight:** nothing sensitive runs without explicit sign-off.

## Attrition Predictor (scikit-learn RandomForest)
- **Purpose:** flag retention risk to start a conversation — **advisory only**.
- **Input → Output:** `AttritionInput` (6 job features) → `AttritionResult
  {attrition_risk_score, top_risk_factors, explanation, needs_review, advisory_only}`.
- **Logic / data:** `RandomForestClassifier` (200 trees, depth 8). Ships trained on
  **synthetic data** for the demo; replace with your governed dataset before real use.
- **Features (no protected classes):** tenure, performance, absence days, months
  since promotion, salary band, manager rating. **No race/gender/age input.**
- **Fairness / safety:** high risk → `needs_review` for human bias review before any
  action; output framed as a prompt to talk, never punitive.
- **Limitations / metrics:** synthetic-data accuracy is **not** indicative of real
  performance; validate + monitor drift on your data (Model Risk Management). Block
  deployment if validation accuracy is below your bar.
- **Human oversight:** must never drive an automated adverse employment decision.

---

## Maintenance
When an agent changes, update its contract in `agents/contracts.py`, this card, and
the tests (`tests/test_agent_contracts.py`, `tests/test_compliance.py`). The
registry-completeness test fails if an agent ships without a spec.
