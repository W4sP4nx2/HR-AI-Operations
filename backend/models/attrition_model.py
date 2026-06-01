"""Employee attrition predictor.

A scikit-learn ``RandomForestClassifier`` trained on the features:
    tenure_months, performance_score, absence_days, last_promotion_months,
    salary_band, manager_rating

If no real dataset is supplied the model trains on synthetic data generated at
startup. Predictions return an attrition risk score in [0, 1] plus the top
contributing risk factors (from feature importances weighted by the input).
Claude is used to produce a plain-English explanation of each prediction.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from core.config import settings

FEATURES = [
    "tenure_months",
    "performance_score",
    "absence_days",
    "last_promotion_months",
    "salary_band",
    "manager_rating",
]


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

    x = np.column_stack(
        [tenure, performance, absence, last_promo, salary_band, manager_rating]
    ).astype(float)

    # Latent risk: higher with low performance, high absence, long since promo,
    # low salary band and low manager rating.
    latent = (
        0.015 * last_promo
        + 0.06 * absence
        - 0.45 * performance
        - 0.30 * manager_rating
        - 0.20 * salary_band
        + 0.004 * (60 - np.clip(tenure, 0, 60))
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
        self.train()

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

        model = RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42, n_jobs=-1)
        model.fit(x, y)
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
        importances = dict(zip(FEATURES, self._model.feature_importances_, strict=False))
        # Direction-aware "badness" of each feature in [0, 1].
        badness = {
            "tenure_months": 1 - min(features["tenure_months"], 60) / 60,
            "performance_score": 1 - (features["performance_score"] - 1) / 4,
            "absence_days": min(features["absence_days"], 30) / 30,
            "last_promotion_months": min(features["last_promotion_months"], 60) / 60,
            "salary_band": 1 - (features["salary_band"] - 1) / 5,
            "manager_rating": 1 - (features["manager_rating"] - 1) / 4,
        }
        contributions = {f: round(importances[f] * badness[f], 4) for f in FEATURES}
        ranked = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
        return [{"factor": f, "contribution": c} for f, c in ranked[:3]]

    def _claude_explanation(
        self, score: float, factors: list[dict[str, Any]], features: dict[str, float]
    ) -> str:
        """Generate a plain-English explanation via Claude.

        Args:
            score: The attrition risk score.
            factors: Top risk factors.
            features: The raw input features.

        Returns:
            A short natural-language explanation. Falls back to a templated
            string if the Anthropic client is unavailable.
        """
        factor_names = ", ".join(f["factor"] for f in factors)
        from core.runtime_key import effective_api_key, llm_active

        if not llm_active():
            return (
                f"Estimated attrition risk is {score:.0%}. The main drivers are "
                f"{factor_names}. Consider a retention conversation and reviewing "
                f"recent recognition and growth opportunities."
            )
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=effective_api_key())
            prompt = (
                "You are an HR analytics assistant. In 2-3 sentences, explain this "
                "attrition prediction in plain English for a manager. Be supportive "
                "and action-oriented; do not expose raw model internals.\n\n"
                f"Risk score: {score:.2f}\nTop factors: {factor_names}\n"
                f"Employee features: {features}"
            )
            msg = client.messages.create(
                model=settings.claude_model,
                max_tokens=250,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
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
            self.train()
        row = np.array([[features[f] for f in FEATURES]], dtype=float)
        score = float(self._model.predict_proba(row)[0][1])
        factors = self._explain_factors(features)
        explanation = self._claude_explanation(score, factors, features)
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
            "needs_review": needs_review,
            "advisory_only": True,
        }


attrition_model = AttritionModel()
