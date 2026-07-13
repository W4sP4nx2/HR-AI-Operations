"""Agentic behavior evals — the four "how do we know it's *working*" workflows.

Unit tests prove schema/syntax; these grade **behavior** on the deterministic
no-key path (CI-safe, reproducible). Two kinds of test live here:

  * **Guarantees** — real properties we assert hold.
  * **Boundaries** — we assert deliberate product limits (for example, no text
    sentiment in attrition features) so they remain explicit and reviewable.
"""

from __future__ import annotations

import asyncio


# --------------------------------------------------------------------------- #
# 1. Policy RAG — the "Negative Space" test (absent policy → refuse, don't invent)
# --------------------------------------------------------------------------- #
def test_negative_space_refuses_instead_of_fabricating() -> None:
    """A hyper-specific, absent scenario must trigger the refusal path — never a
    stitched-together fake rule."""
    from pipelines.rag_pipeline import rag_pipeline

    answer, mode = rag_pipeline._synthesize(
        "What is our policy on charging personal electric unicycles in the server room?",
        [],  # nothing retrieved → the absent-policy case
    )
    assert mode == "no_context"
    assert "don't cover that" in answer.lower()
    # It must not have fabricated a specific rule.
    for invented in ("you may", "is permitted", "is prohibited", "allowed to"):
        assert invented not in answer.lower()


# --------------------------------------------------------------------------- #
# 2. Triage — Adversarial Intention (emotional register)
# --------------------------------------------------------------------------- #
def test_triage_escalates_harassment_in_any_register() -> None:
    """The real invariant: a genuine compliance/safety matter escalates whether
    phrased coldly or in panic — the underlying signal, not the tone, decides."""
    from agents.triage_agent import triage_agent

    for phrasing in (
        "I wish to formally report a harassment matter.",  # cold/formal
        "HELP i am being harassed at work please someone!!!",  # panicked
        "harassment complaint regarding my manager",  # terse
    ):
        assert triage_agent._keyword_classify(phrasing) == "URGENT", phrasing


def test_triage_routine_policy_question_stays_policy_when_calm() -> None:
    """A plainly-worded policy question routes to POLICY (no false escalation)."""
    from agents.triage_agent import triage_agent

    assert triage_agent._keyword_classify("What is the remote work policy?") == "POLICY"


def test_emotional_decoration_does_not_override_policy_intent() -> None:
    """Urgency modifiers alone do not override an explicit policy question."""
    from agents.triage_agent import triage_agent

    calm = triage_agent._keyword_classify("What is the remote work policy?")
    panicked = triage_agent._keyword_classify(
        "URGENT!! I need the remote work policy ASAP, this is an emergency!!!"
    )
    assert calm == "POLICY"
    assert panicked == "POLICY"
    assert calm == panicked


# --------------------------------------------------------------------------- #
# 3. Resume Screener — Counter-Factual Competency (negative-context keywords)
# --------------------------------------------------------------------------- #
def test_screener_discounts_negative_context() -> None:
    """The deterministic path removes nearby-negated skills before scoring."""
    from agents.resume_screener_agent import ResumeScreenerAgent

    jd = "Senior engineer: production FastAPI, LangGraph multi-agent pipelines, Python, async."
    laundered = (
        "Assisted a team that attempted FastAPI but abandoned it due to scale issues. "
        "Have read books on LangGraph but have not built production pipelines. "
        "Familiar with Python and async in theory."
    )
    r = ResumeScreenerAgent()._embedding_score(jd, laundered)
    assert "fastapi" not in r["matched_skills"]
    assert "langgraph" not in r["matched_skills"]


# --------------------------------------------------------------------------- #
# 4. Attrition — the Contextual Dialect premise doesn't apply (design boundary)
# --------------------------------------------------------------------------- #
def test_attrition_is_structured_features_only_not_sentiment() -> None:
    """DESIGN BOUNDARY: the attrition predictor consumes only the six numeric
    job features — it never parses employee text/sentiment. This is deliberate
    (sentiment-on-communications is a protected-class-proxy bias risk), so the
    'contextual dialect' sentiment test is out of scope by construction."""
    from agents.contracts import AttritionInput
    from models.attrition_model import FEATURES

    assert FEATURES == [
        "tenure_months",
        "performance_score",
        "absence_days",
        "last_promotion_months",
        "salary_band",
        "manager_rating",
    ]
    # The input contract is entirely numeric — no free-text/sentiment field.
    for name, field in AttritionInput.model_fields.items():
        assert field.annotation in (int, float), f"{name} is not numeric"


def test_attrition_prioritizes_quiet_disengagement_after_calibration() -> None:
    """The calibrated model should not let absence spikes drown out slow-burn risk.

    The public input boundary remains six numeric job signals, but the model now
    adds an internal ``disengagement_index`` interaction term. A quietly stalled
    profile (4 years no promotion + low manager rating) should score higher than
    a one-off loud absence spike with otherwise healthier context.
    """
    from models.attrition_model import attrition_model

    quiet_stalled = {
        "tenure_months": 30,
        "performance_score": 3.0,
        "absence_days": 3,
        "last_promotion_months": 48,
        "salary_band": 2,
        "manager_rating": 2.0,
    }
    loud_spike = {
        "tenure_months": 30,
        "performance_score": 3.0,
        "absence_days": 25,
        "last_promotion_months": 10,
        "salary_band": 3,
        "manager_rating": 3.5,
    }
    quiet = attrition_model.predict(quiet_stalled)["attrition_risk_score"]
    quiet_factors = attrition_model.predict(quiet_stalled)["top_risk_factors"]
    loud = attrition_model.predict(loud_spike)["attrition_risk_score"]

    assert quiet > loud
    assert "disengagement_index" in {f["factor"] for f in quiet_factors}


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(asyncio.sleep(0))
