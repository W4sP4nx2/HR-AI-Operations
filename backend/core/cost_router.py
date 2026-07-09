"""Deterministic cost-tier routing before provider calls."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from core.config import settings


@dataclass(frozen=True)
class CostRoute:
    """Auditable model-tier decision derived before any LLM call."""

    tier: str
    selected_model: str
    reason: str
    matched_keyword: str | None = None


class CostRouter:
    """Choose the cheapest sufficient model from the injected allow-list."""

    ECONOMY_KEYWORDS = frozenset({"vacation", "leave", "benefits", "hours", "payroll"})
    PREMIUM_KEYWORDS = frozenset(
        {"termination", "harassment", "legal", "compliance", "discrimination"}
    )

    @classmethod
    def classify(cls, query: str, allowed_models: list[str] | None = None) -> CostRoute:
        """Classify query complexity and select an allowed model without defaults."""
        models = cls._models(allowed_models)
        query_lower = query.lower()

        premium = cls._first_match(query_lower, cls.PREMIUM_KEYWORDS)
        if premium:
            return CostRoute(
                tier="premium",
                selected_model=cls._largest_model(models),
                reason="high_stakes_hr_keyword",
                matched_keyword=premium,
            )

        economy = cls._first_match(query_lower, cls.ECONOMY_KEYWORDS)
        if economy:
            return CostRoute(
                tier="economy",
                selected_model=cls._smallest_model(models),
                reason="simple_policy_lookup_keyword",
                matched_keyword=economy,
            )

        return CostRoute(
            tier="standard",
            selected_model=cls._largest_model(models),
            reason="default_policy_synthesis",
        )

    @staticmethod
    def _models(allowed_models: list[str] | None) -> list[str]:
        if allowed_models is None:
            raw = os.environ.get("ALLOWED_MODELS", settings.allowed_models)
            allowed_models = [item.strip() for item in raw.split(",") if item.strip()]
        models = list(dict.fromkeys(model.strip() for model in allowed_models if model.strip()))
        if not models:
            raise RuntimeError("ALLOWED_MODELS is empty or unset - cost router needs injection")
        return models

    @staticmethod
    def _first_match(query_lower: str, keywords: frozenset[str]) -> str | None:
        return next((keyword for keyword in sorted(keywords) if keyword in query_lower), None)

    @classmethod
    def _smallest_model(cls, models: list[str]) -> str:
        return sorted(enumerate(models), key=lambda item: (cls._size_score(item[1]), item[0]))[0][1]

    @classmethod
    def _largest_model(cls, models: list[str]) -> str:
        return sorted(enumerate(models), key=lambda item: (cls._size_score(item[1]), item[0]))[-1][
            1
        ]

    @staticmethod
    def _size_score(model_id: str) -> float:
        scores: list[float] = []
        for value, suffix in re.findall(r"(\d+(?:\.\d+)?)\s*([bBmM])", model_id):
            multiplier = 1_000.0 if suffix.lower() == "b" else 1.0
            scores.append(float(value) * multiplier)
        return max(scores, default=0.0)
