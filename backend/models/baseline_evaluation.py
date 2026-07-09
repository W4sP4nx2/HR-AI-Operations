"""Resource-bounded golden evaluation for the three naive baselines."""

from __future__ import annotations

from typing import Any, Sequence

from models.naive_baselines import (
    attrition_rule_baseline,
    resume_overlap_baseline,
    triage_keyword_baseline,
)

TRIAGE_GOLDEN: tuple[tuple[str, str], ...] = (
    ("My health insurance enrollment was rejected", "BENEFITS"),
    ("How many vacation days do I receive?", "BENEFITS"),
    ("Where is the remote work policy?", "POLICY"),
    ("What does the employee handbook say about travel?", "POLICY"),
    ("Our new hire needs laptop access on the first day", "ONBOARDING"),
    ("Please schedule orientation for the new hire", "ONBOARDING"),
    ("I need feedback for my performance review", "PERFORMANCE"),
    ("Can we discuss promotion criteria?", "PERFORMANCE"),
    ("Please audit our GDPR retention process", "COMPLIANCE"),
    ("Is this policy violation a compliance issue?", "COMPLIANCE"),
    ("I am being harassed by my manager", "URGENT"),
    ("There was a safety threat in the office", "URGENT"),
    ("Retaliation started after I reported discrimination", "URGENT"),
    # Deliberate hard case: the baseline has no payroll vocabulary and should
    # expose the miss instead of giving us a suspiciously perfect benchmark.
    ("My paycheck is missing this month", "BENEFITS"),
)

RESUME_GOLDEN: tuple[tuple[tuple[str, ...], tuple[str, ...], int, str], ...] = (
    (
        ("python", "fastapi", "postgres"),
        ("python", "fastapi", "postgres"),
        1,
        "strong_match",
    ),
    (("react", "typescript"), ("vue", "javascript"), 0, "unrelated_stack"),
    (("aws", "terraform"), ("aws", "terraform", "linux"), 1, "cloud_match"),
    (("kubernetes",), ("docker", "compose"), 0, "missing_orchestrator"),
    (("c++", "linux"), ("c++", "linux", "cmake"), 1, "systems_match"),
    # Lexical overlap cannot understand negation. This is an expected failure
    # and the reason the product keeps the separate skill-validation guard.
    (
        ("python", "langgraph"),
        ("never", "used", "python", "langgraph"),
        0,
        "negation_trap",
    ),
)

ATTRITION_GOLDEN: tuple[tuple[dict[str, float], int], ...] = (
    (
        {
            "tenure_months": 48,
            "performance_score": 4.5,
            "absence_days": 1,
            "last_promotion_months": 6,
            "salary_band": 4,
            "manager_rating": 4.7,
        },
        0,
    ),
    (
        {
            "tenure_months": 72,
            "performance_score": 4.0,
            "absence_days": 2,
            "last_promotion_months": 12,
            "salary_band": 4,
            "manager_rating": 4.2,
        },
        0,
    ),
    (
        {
            "tenure_months": 24,
            "performance_score": 3.8,
            "absence_days": 3,
            "last_promotion_months": 8,
            "salary_band": 3,
            "manager_rating": 4.0,
        },
        0,
    ),
    (
        {
            "tenure_months": 60,
            "performance_score": 4.8,
            "absence_days": 0,
            "last_promotion_months": 3,
            "salary_band": 5,
            "manager_rating": 4.9,
        },
        0,
    ),
    (
        {
            "tenure_months": 36,
            "performance_score": 3.6,
            "absence_days": 4,
            "last_promotion_months": 14,
            "salary_band": 3,
            "manager_rating": 3.8,
        },
        0,
    ),
    (
        {
            "tenure_months": 14,
            "performance_score": 1.8,
            "absence_days": 24,
            "last_promotion_months": 38,
            "salary_band": 1,
            "manager_rating": 1.5,
        },
        1,
    ),
    (
        {
            "tenure_months": 52,
            "performance_score": 2.2,
            "absence_days": 18,
            "last_promotion_months": 55,
            "salary_band": 2,
            "manager_rating": 1.4,
        },
        1,
    ),
    (
        {
            "tenure_months": 20,
            "performance_score": 2.0,
            "absence_days": 20,
            "last_promotion_months": 42,
            "salary_band": 1,
            "manager_rating": 2.0,
        },
        1,
    ),
    (
        {
            "tenure_months": 44,
            "performance_score": 2.5,
            "absence_days": 12,
            "last_promotion_months": 58,
            "salary_band": 2,
            "manager_rating": 1.6,
        },
        1,
    ),
    (
        {
            "tenure_months": 8,
            "performance_score": 1.5,
            "absence_days": 28,
            "last_promotion_months": 30,
            "salary_band": 1,
            "manager_rating": 1.2,
        },
        1,
    ),
)


def _binary_metrics(
    labels: Sequence[int], scores: Sequence[float], threshold: float
) -> dict[str, float]:
    predictions = [int(score >= threshold) for score in scores]
    true_positive = sum(p == 1 and y == 1 for p, y in zip(predictions, labels, strict=True))
    true_negative = sum(p == 0 and y == 0 for p, y in zip(predictions, labels, strict=True))
    positives = sum(labels)
    negatives = len(labels) - positives
    recall = true_positive / positives if positives else 0.0
    specificity = true_negative / negatives if negatives else 0.0
    brier = sum((score - label) ** 2 for score, label in zip(scores, labels, strict=True))
    return {
        "balanced_accuracy": round((recall + specificity) / 2, 4),
        "positive_recall": round(recall, 4),
        "brier_score": round(brier / len(labels), 4),
    }


def _average_precision(labels: Sequence[int], scores: Sequence[float]) -> float:
    ranked = sorted(zip(scores, labels, strict=True), key=lambda item: item[0], reverse=True)
    positives = sum(labels)
    if not positives:
        return 0.0

    hits = 0
    precision_sum = 0.0
    reviewed = 0
    index = 0
    while index < len(ranked):
        score = ranked[index][0]
        group_labels: list[int] = []
        while index < len(ranked) and ranked[index][0] == score:
            group_labels.append(ranked[index][1])
            index += 1
        group_hits = sum(group_labels)
        reviewed += len(group_labels)
        hits += group_hits
        if group_hits:
            precision_sum += group_hits * (hits / reviewed)
    return round(precision_sum / positives, 4)


def _macro_f1(expected: Sequence[str], predicted: Sequence[str]) -> tuple[float, dict[str, float]]:
    labels = sorted(set(expected))
    per_class: dict[str, float] = {}
    for label in labels:
        true_positive = sum(
            truth == label and guess == label
            for truth, guess in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            truth != label and guess == label
            for truth, guess in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            truth == label and guess != label
            for truth, guess in zip(expected, predicted, strict=True)
        )
        denominator = 2 * true_positive + false_positive + false_negative
        per_class[label] = round(2 * true_positive / denominator if denominator else 0.0, 4)
    return round(sum(per_class.values()) / len(per_class), 4), per_class


def evaluate_triage() -> dict[str, Any]:
    expected = [label for _, label in TRIAGE_GOLDEN]
    predicted = [triage_keyword_baseline.predict(text).category for text, _ in TRIAGE_GOLDEN]
    macro_f1, per_class = _macro_f1(expected, predicted)
    urgent_total = expected.count("URGENT")
    urgent_recall = (
        sum(
            truth == "URGENT" and guess == "URGENT"
            for truth, guess in zip(expected, predicted, strict=True)
        )
        / urgent_total
    )
    errors = [
        {"text": text, "expected": truth, "predicted": guess}
        for (text, truth), guess in zip(TRIAGE_GOLDEN, predicted, strict=True)
        if truth != guess
    ]
    return {
        "samples": len(expected),
        "macro_f1": macro_f1,
        "urgent_recall": round(urgent_recall, 4),
        "per_class_f1": per_class,
        "errors": errors,
        "gate": macro_f1 >= 0.80 and urgent_recall == 1.0,
    }


def evaluate_resume_overlap() -> dict[str, Any]:
    labels: list[int] = []
    scores: list[float] = []
    by_case: dict[str, float] = {}
    for required, terms, label, case_name in RESUME_GOLDEN:
        result = resume_overlap_baseline.predict(required, terms)
        labels.append(label)
        scores.append(result.score)
        by_case[case_name] = result.score
    average_precision = _average_precision(labels, scores)
    return {
        "samples": len(labels),
        "average_precision": average_precision,
        "scores_by_case": by_case,
        "known_failure": {
            "case": "negation_trap",
            "score": by_case["negation_trap"],
            "reason": "lexical overlap does not establish demonstrated experience",
        },
        "gate": average_precision >= 0.70,
    }


def evaluate_attrition_rule() -> dict[str, Any]:
    labels = [label for _, label in ATTRITION_GOLDEN]
    scores = [attrition_rule_baseline.predict(features).score for features, _ in ATTRITION_GOLDEN]
    metrics = _binary_metrics(labels, scores, threshold=0.5)
    return {
        "samples": len(labels),
        **metrics,
        "score_range": [round(min(scores), 4), round(max(scores), 4)],
        "gate": metrics["balanced_accuracy"] >= 0.80 and metrics["brier_score"] <= 0.20,
    }


def evaluate_all() -> dict[str, Any]:
    """Run all golden checks without training, network calls, or GPU imports."""
    results = {
        "triage_keyword": evaluate_triage(),
        "resume_skill_overlap": evaluate_resume_overlap(),
        "attrition_rule": evaluate_attrition_rule(),
    }
    return {
        "resource_contract": {
            "gpu": False,
            "network": False,
            "training": False,
            "total_golden_samples": sum(result["samples"] for result in results.values()),
        },
        "baselines": results,
        "all_gates_pass": all(result["gate"] for result in results.values()),
    }
