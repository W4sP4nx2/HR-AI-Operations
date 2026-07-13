"""Contract and golden-evaluation tests for the CPU-safe baselines."""

from __future__ import annotations

from models.attrition_model import AttritionModel
from models.baseline_evaluation import evaluate_all
from models.naive_baselines import (
    attrition_rule_baseline,
    resume_overlap_baseline,
    triage_keyword_baseline,
)


def test_triage_urgent_override_and_default_are_explicit():
    urgent = triage_keyword_baseline.predict("A safety threat needs immediate action")
    assert urgent.category == "URGENT"
    assert urgent.matched_terms
    default = triage_keyword_baseline.predict("Can somebody help me understand this?")
    assert default.category == "POLICY"
    assert default.defaulted is True


def test_triage_fast_path_requires_urgent_or_unambiguous_multi_keyword_evidence():
    assert (
        triage_keyword_baseline.confident_predict("Urgent safety threat immediately").category
        == "URGENT"
    )
    benefits = triage_keyword_baseline.confident_predict("Question about health insurance benefits")
    assert benefits is not None
    assert benefits.category == "BENEFITS"
    assert triage_keyword_baseline.confident_predict("Question about benefits") is None
    assert triage_keyword_baseline.confident_predict("Benefits policy for remote work") is None


def test_resume_overlap_conservatively_blocks_negated_skills():
    result = resume_overlap_baseline.predict(
        ("python", "langgraph"),
        ("never", "used", "python", "langgraph"),
    )
    assert result.score == 0.0
    assert result.matched_skills == ()


def test_attrition_rule_ranks_stalled_profile_above_healthy_profile():
    healthy = attrition_rule_baseline.predict(
        {
            "tenure_months": 48,
            "performance_score": 4.5,
            "absence_days": 1,
            "last_promotion_months": 6,
            "salary_band": 4,
            "manager_rating": 4.7,
        }
    )
    stalled = attrition_rule_baseline.predict(
        {
            "tenure_months": 48,
            "performance_score": 2.3,
            "absence_days": 12,
            "last_promotion_months": 54,
            "salary_band": 2,
            "manager_rating": 1.5,
        }
    )
    assert stalled.score > healthy.score
    assert stalled.contributions[0][0] in {"disengagement_index", "manager_rating"}


def test_attrition_model_uses_rule_fallback_when_sklearn_is_unavailable(monkeypatch):
    model = object.__new__(AttritionModel)
    model._model = None
    model._trained = False

    def unavailable(*args, **kwargs):
        raise ImportError("scikit-learn unavailable")

    monkeypatch.setattr(model, "train", unavailable)
    monkeypatch.setattr(
        model,
        "_llm_explanation",
        lambda score, factors, features: "deterministic baseline explanation",
    )
    result = model.predict(
        {
            "tenure_months": 18,
            "performance_score": 2.0,
            "absence_days": 20,
            "last_promotion_months": 48,
            "salary_band": 1,
            "manager_rating": 1.5,
        }
    )
    assert result["attrition_risk_score"] > 0.5
    assert result["advisory_only"] is True
    assert result["top_risk_factors"]


def test_golden_evaluation_passes_without_training_or_gpu():
    report = evaluate_all()
    assert report["resource_contract"] == {
        "gpu": False,
        "network": False,
        "training": False,
        "total_golden_samples": 30,
    }
    assert report["all_gates_pass"] is True
    assert report["baselines"]["resume_skill_overlap"]["negation_guard"]["score"] == 0.0
