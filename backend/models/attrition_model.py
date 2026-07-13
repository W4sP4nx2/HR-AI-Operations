"""Employee attrition predictor.

A scikit-learn ``RandomForestClassifier`` trained on the public features:
    tenure_months, performance_score, absence_days, last_promotion_months,
    salary_band, manager_rating

If no real dataset is supplied the model trains on synthetic data generated at
startup. Predictions return an attrition risk score in [0, 1] plus the top
contributing risk factors (from feature importances weighted by the input).
The configured live provider can produce a plain-English explanation.

The public contract deliberately remains six job-related numeric signals. The
model internally adds one engineered interaction term, ``disengagement_index``,
so slow-burn risk (long promotion stall + poor manager relationship) is visible
to the tree splits without introducing free-text or protected attributes.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from agents.prompts import ATTRITION_EXPLANATION
from core.config import settings
from models.naive_baselines import attrition_rule_baseline

FEATURES = [
    "tenure_months",
    "performance_score",
    "absence_days",
    "last_promotion_months",
    "salary_band",
    "manager_rating",
]

ENGINEERED_FEATURES = ["disengagement_index"]
MODEL_FEATURES = [*FEATURES, *ENGINEERED_FEATURES]

FACTOR_DISPLAY = {
    "tenure_months": "tenure",
    "performance_score": "performance",
    "absence_days": "absence",
    "last_promotion_months": "time since promotion",
    "salary_band": "salary band",
    "manager_rating": "manager relationship",
    "disengagement_index": "slow-burn disengagement",
}

# These are planning assumptions, not payroll data. The API returns the basis
# alongside every estimate so an HR team can replace the band midpoints and
# multiplier with finance-approved values before using the feature in a live
# planning workflow.
SALARY_BAND_MIDPOINTS = {
    1: 55_000,
    2: 75_000,
    3: 95_000,
    4: 125_000,
    5: 165_000,
}
REPLACEMENT_COST_MULTIPLIER = 0.45


def disengagement_index(last_promotion_months: float, manager_rating: float) -> float:
    """Return the engineered slow-burn disengagement signal.

    Args:
        last_promotion_months: Months since the employee's last promotion.
        manager_rating: Manager-relationship score in the 1-5 range.

    Returns:
        A non-negative interaction term that rises when career stagnation and a
        weak manager relationship co-occur.
    """
    return float(max(last_promotion_months, 0.0) / max(manager_rating, 0.1))


def estimate_business_impact(score: float, salary_band: float) -> dict[str, Any]:
    """Return an explicit, replaceable planning estimate for retention impact.

    The model does not receive compensation records. This helper therefore uses
    a documented salary-band midpoint and replacement-cost multiplier as a
    planning proxy, and returns both the full potential cost and its
    risk-weighted exposure. It must not be presented as payroll truth.
    """
    band = min(5, max(1, int(round(salary_band))))
    midpoint = SALARY_BAND_MIDPOINTS[band]
    potential_cost = round(midpoint * REPLACEMENT_COST_MULTIPLIER / 1000) * 1000
    risk_weighted = round(potential_cost * max(0.0, min(1.0, score)) / 1000) * 1000
    if score >= 0.66:
        action = "Schedule a retention interview and HRBP review this week."
    elif score >= 0.33:
        action = "Schedule a manager check-in and review growth opportunities."
    else:
        action = "Keep the employee in the regular engagement check-in cadence."
    return {
        "estimated_replacement_cost_usd": int(potential_cost),
        "risk_adjusted_exposure_usd": int(risk_weighted),
        "recommended_action": action,
        "assumption": (
            f"Salary band {band} midpoint ${midpoint:,.0f} × "
            f"{REPLACEMENT_COST_MULTIPLIER:.0%} replacement-cost planning factor; "
            "replace with finance-approved assumptions before operational use."
        ),
    }


def _augment_matrix(x: np.ndarray) -> np.ndarray:
    """Append engineered model features to a six-column public feature matrix."""
    if x.shape[1] == len(MODEL_FEATURES):
        return x.astype(float)
    if x.shape[1] != len(FEATURES):
        raise ValueError(
            f"Expected {len(FEATURES)} or {len(MODEL_FEATURES)} columns, got {x.shape[1]}"
        )
    di = x[:, FEATURES.index("last_promotion_months")] / np.maximum(
        x[:, FEATURES.index("manager_rating")], 0.1
    )
    return np.column_stack([x, di]).astype(float)


def generate_synthetic_data(n: int = 2000, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate a synthetic attrition dataset.

    The label is derived from a latent risk function so the trained model learns
    sensible, monotonic relationships (e.g. long time since promotion and low
    manager rating increase attrition risk).

    Args:
        n: Number of samples.
        seed: RNG seed for reproducibility.

    Returns:
        Tuple ``(X, y)`` of features and binary labels.
    """
    rng = np.random.default_rng(seed)
    tenure = rng.integers(1, 120, n)
    performance = rng.uniform(1, 5, n)
    absence = rng.integers(0, 30, n)
    last_promo = rng.integers(0, 60, n)
    salary_band = rng.integers(1, 6, n)
    manager_rating = rng.uniform(1, 5, n)

    public_x = np.column_stack(
        [tenure, performance, absence, last_promo, salary_band, manager_rating]
    ).astype(float)
    disengagement = last_promo / np.maximum(manager_rating, 0.1)
    x = _augment_matrix(public_x)

    # Explicit slow-burn calibration: separately-common signals become higher
    # risk when they intersect (promotion stall + weak manager relationship).
    promotion_stall = np.clip((last_promo - 18) / 42, 0, 1)
    manager_strain = np.clip((3.5 - manager_rating) / 2.5, 0, 1)
    slow_burn = promotion_stall * manager_strain

    # Latent risk: higher with low performance, high absence, long since promo,
    # low salary band and low manager rating. The interaction term keeps a quiet
    # stalled profile from being dominated by the louder absence spike signal.
    latent = (
        0.015 * last_promo
        + 0.035 * absence
        - 0.45 * performance
        - 0.30 * manager_rating
        - 0.20 * salary_band
        + 0.004 * (60 - np.clip(tenure, 0, 60))
        + 0.055 * disengagement
        + 1.25 * slow_burn
    )
    prob = 1 / (1 + np.exp(-latent))
    y = (rng.uniform(0, 1, n) < prob).astype(int)
    return x, y


class AttritionModel:
    """Random-forest attrition risk predictor with Claude explanations."""

    def __init__(self) -> None:
        """Initialise and train the model on synthetic data by default."""
        self._model = None
        self._trained = False
        try:
            self.train()
        except ImportError:
            # Lean/offline builds retain an explicit, interpretable fallback.
            self._trained = False

    def train(self, x: np.ndarray | None = None, y: np.ndarray | None = None) -> dict[str, Any]:
        """Train (or retrain) the classifier.

        Args:
            x: Optional feature matrix; synthetic data is generated if omitted.
            y: Optional label vector; synthetic labels generated if omitted.

        Returns:
            A dict with training metadata (sample count, train accuracy).
        """
        from sklearn.ensemble import RandomForestClassifier

        if x is None or y is None:
            x, y = generate_synthetic_data()

        x = _augment_matrix(np.asarray(x, dtype=float))

        slow_burn_weight = np.clip(
            ((x[:, MODEL_FEATURES.index("last_promotion_months")] - 18) / 42),
            0,
            1,
        ) * np.clip(
            (3.5 - x[:, MODEL_FEATURES.index("manager_rating")]) / 2.5,
            0,
            1,
        )
        sample_weight = 1 + (2.0 * slow_burn_weight)

        model = RandomForestClassifier(n_estimators=240, max_depth=8, random_state=42, n_jobs=1)
        model.fit(x, y, sample_weight=sample_weight)
        self._model = model
        self._trained = True
        accuracy = float(model.score(x, y))
        return {"samples": int(len(y)), "train_accuracy": round(accuracy, 4)}

    def _explain_factors(self, features: dict[str, float]) -> list[dict[str, Any]]:
        """Compute the top risk factors for a single prediction.

        Combines global feature importances with how extreme each input is to
        surface the most influential drivers.

        Args:
            features: Mapping of feature name to value.

        Returns:
            A list of the top three risk-factor dicts sorted by contribution.
        """
        importances = dict(zip(MODEL_FEATURES, self._model.feature_importances_, strict=False))
        di = disengagement_index(features["last_promotion_months"], features["manager_rating"])
        # Direction-aware "badness" of each feature in [0, 1].
        badness = {
            "tenure_months": 1 - min(features["tenure_months"], 60) / 60,
            "performance_score": 1 - (features["performance_score"] - 1) / 4,
            "absence_days": min(features["absence_days"], 30) / 30,
            "last_promotion_months": min(features["last_promotion_months"], 60) / 60,
            "salary_band": 1 - (features["salary_band"] - 1) / 5,
            "manager_rating": 1 - (features["manager_rating"] - 1) / 4,
            "disengagement_index": min(di, 30) / 30,
        }
        contributions = {f: float(round(importances[f] * badness[f], 4)) for f in MODEL_FEATURES}
        ranked = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
        return [{"factor": f, "contribution": c} for f, c in ranked[:3]]

    def _model_row(self, features: dict[str, float]) -> np.ndarray:
        """Return the one-row model matrix including engineered features."""
        public = np.array([[features[f] for f in FEATURES]], dtype=float)
        return _augment_matrix(public)

    def _llm_explanation(
        self, score: float, factors: list[dict[str, Any]], features: dict[str, float]
    ) -> str:
        """Generate a plain-English explanation via the configured live provider.

        Args:
            score: The attrition risk score.
            factors: Top risk factors.
            features: The raw input features.

        Returns:
            A short natural-language explanation. Falls back to a templated
            string if the provider is unavailable.
        """
        factor_names = ", ".join(FACTOR_DISPLAY.get(f["factor"], f["factor"]) for f in factors)
        from core.llm_factory import run_text_completion
        from core.runtime_key import llm_active

        if not llm_active():
            return (
                f"Estimated attrition risk is {score:.0%}. The main drivers are "
                f"{factor_names}. Consider a retention conversation and reviewing "
                f"recent recognition and growth opportunities."
            )
        try:
            prompt = (
                f"Risk score: {score:.2f}\nTop factors: {factor_names}\n"
                f"Employee features: {features}"
            )
            answer = run_text_completion(
                prompt,
                role="attrition_explanation",
                system_prompt=ATTRITION_EXPLANATION.text,
                max_tokens=250,
            )
            if answer is None:
                raise RuntimeError("provider returned no completion")
            return answer
        except Exception as exc:  # noqa: BLE001
            return (
                f"Estimated attrition risk is {score:.0%}; key drivers: {factor_names}. "
                f"(LLM explanation unavailable: {exc})"
            )

    def predict(self, features: dict[str, float]) -> dict[str, Any]:
        """Predict attrition risk for a single employee.

        Args:
            features: Mapping of the six required feature names to values.

        Returns:
            Dict with ``attrition_risk_score``, ``top_risk_factors`` and
            ``explanation``.
        """
        if not self._trained:
            try:
                self.train()
            except ImportError:
                baseline = attrition_rule_baseline.predict(features)
                score = baseline.score
                factors = [
                    {"factor": factor, "contribution": contribution}
                    for factor, contribution in baseline.contributions[:3]
                ]
            else:
                row = self._model_row(features)
                score = float(self._model.predict_proba(row)[0][1])
                factors = self._explain_factors(features)
        else:
            row = self._model_row(features)
            score = float(self._model.predict_proba(row)[0][1])
            factors = self._explain_factors(features)
        explanation = self._llm_explanation(score, factors, features)
        business_impact = estimate_business_impact(score, features["salary_band"])
        # High-risk predictions are flagged for human bias review before any
        # action (EEOC disparate-impact safeguard). The model takes NO protected
        # attributes (race/gender/age) as input — only the six job features.
        # Uses a *dedicated* threshold calibrated to this model's output
        # distribution (healthy ≈0.05 … severe ≈0.45), NOT the RAG cosine floor —
        # reusing 0.7 there meant needs_review never fired.
        needs_review = score >= settings.attrition_review_threshold
        return {
            "attrition_risk_score": round(score, 4),
            "top_risk_factors": factors,
            "explanation": explanation,
            "business_impact": business_impact,
            "needs_review": needs_review,
            "advisory_only": True,
        }


attrition_model = AttritionModel()
