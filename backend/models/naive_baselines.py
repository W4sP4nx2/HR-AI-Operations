"""Tiny, deterministic baselines for three product decision paths.

These models deliberately avoid torch, network calls, model downloads, and
training jobs. They are useful as auditable fallbacks and evaluation floors,
not as evidence that an HR decision is valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

TRIAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "URGENT": (
        "urgent",
        "asap",
        "emergency",
        "immediately",
        "harass",
        "discriminat",
        "retaliat",
        "safety",
        "lawsuit",
        "threat",
    ),
    "BENEFITS": ("benefit", "insurance", "401k", "pto", "vacation", "leave", "health"),
    "ONBOARDING": (
        "onboard",
        "new hire",
        "first day",
        "orientation",
        "laptop",
        "access",
    ),
    "PERFORMANCE": ("performance", "review", "promotion", "raise", "pip", "feedback"),
    "COMPLIANCE": (
        "compliance",
        "audit",
        "gdpr",
        "policy violation",
        "regulation",
        "legal",
    ),
    "POLICY": ("policy", "handbook", "rule", "guideline", "dress code", "remote work"),
}


@dataclass(frozen=True)
class TriageBaselineResult:
    category: str
    matched_terms: tuple[str, ...]
    defaulted: bool


class KeywordTriageBaseline:
    """Priority keyword classifier used when no live language model is active."""

    def __init__(self, keywords: Mapping[str, Sequence[str]] = TRIAGE_KEYWORDS) -> None:
        self._keywords = {category: tuple(terms) for category, terms in keywords.items()}

    def predict(self, text: str) -> TriageBaselineResult:
        lower = text.lower()
        urgent_hits = tuple(term for term in self._keywords["URGENT"] if term in lower)
        if urgent_hits:
            return TriageBaselineResult("URGENT", urgent_hits, False)

        hits = {
            category: tuple(term for term in terms if term in lower)
            for category, terms in self._keywords.items()
            if category != "URGENT"
        }
        category = max(hits, key=lambda name: len(hits[name]))
        if hits[category]:
            return TriageBaselineResult(category, hits[category], False)
        return TriageBaselineResult("POLICY", (), True)

    def confident_predict(self, text: str) -> TriageBaselineResult | None:
        """Return a cheap route only when the lexical evidence is unambiguous."""
        result = self.predict(text)
        if result.category == "URGENT" and result.matched_terms:
            return result
        lower = text.lower()
        category_hits = {
            category: tuple(term for term in terms if term in lower)
            for category, terms in self._keywords.items()
            if category != "URGENT"
        }
        nonempty = [hits for hits in category_hits.values() if hits]
        if len(nonempty) == 1 and len(result.matched_terms) >= 2:
            return result
        return None

    def reason(self, text: str, category: str | None = None) -> str:
        result = self.predict(text)
        selected = category or result.category
        if selected == result.category and result.matched_terms:
            if selected == "URGENT":
                return f"Matched urgent signal '{result.matched_terms[0]}' in the ticket text."
            return (
                f"Matched {selected.title()} keyword(s): " f"{', '.join(result.matched_terms[:3])}."
            )
        if result.defaulted:
            return (
                "No strong keyword signal in the text; defaulted to POLICY for a "
                "document lookup. Low confidence - consider human review."
            )
        return f"Classified as {selected} by the deterministic keyword baseline."


@dataclass(frozen=True)
class ResumeOverlapResult:
    score: float
    matched_skills: tuple[str, ...]
    missing_skills: tuple[str, ...]


class SkillOverlapBaseline:
    """Exact/stem overlap floor for resume-to-job skill coverage."""

    @staticmethod
    def _present(skill: str, resume_terms: set[str]) -> bool:
        if skill in resume_terms:
            return True
        if len(skill) < 4:
            return False
        return any(
            term.startswith(skill) or skill.startswith(term)
            for term in resume_terms
            if len(term) >= 4
        )

    def predict(
        self,
        required_skills: Iterable[str],
        resume_terms: Iterable[str],
    ) -> ResumeOverlapResult:
        required = tuple(dict.fromkeys(skill.lower() for skill in required_skills if skill))
        terms = {term.lower() for term in resume_terms if term}
        matched = tuple(skill for skill in required if self._present(skill, terms))
        missing = tuple(skill for skill in required if skill not in matched)
        score = len(matched) / len(required) if required else 0.0
        return ResumeOverlapResult(score, matched, missing)


@dataclass(frozen=True)
class AttritionBaselineResult:
    score: float
    contributions: tuple[tuple[str, float], ...]


class AttritionRuleBaseline:
    """Transparent risk index over the six approved job-related features."""

    _WEIGHTS: dict[str, float] = {
        "tenure_months": 0.05,
        "performance_score": 0.15,
        "absence_days": 0.10,
        "last_promotion_months": 0.15,
        "salary_band": 0.10,
        "manager_rating": 0.20,
        "disengagement_index": 0.25,
    }

    def predict(self, features: Mapping[str, float]) -> AttritionBaselineResult:
        required = {
            "tenure_months",
            "performance_score",
            "absence_days",
            "last_promotion_months",
            "salary_band",
            "manager_rating",
        }
        missing = sorted(required - features.keys())
        if missing:
            raise ValueError(f"missing attrition feature(s): {', '.join(missing)}")

        tenure = float(features["tenure_months"])
        performance = float(features["performance_score"])
        absence = float(features["absence_days"])
        promotion = float(features["last_promotion_months"])
        salary = float(features["salary_band"])
        manager = float(features["manager_rating"])
        disengagement = max(promotion, 0.0) / max(manager, 0.1)

        badness = {
            "tenure_months": 1 - min(max(tenure, 0.0), 60.0) / 60.0,
            "performance_score": 1 - (min(max(performance, 1.0), 5.0) - 1.0) / 4.0,
            "absence_days": min(max(absence, 0.0), 30.0) / 30.0,
            "last_promotion_months": min(max(promotion, 0.0), 60.0) / 60.0,
            "salary_band": 1 - (min(max(salary, 1.0), 5.0) - 1.0) / 4.0,
            "manager_rating": 1 - (min(max(manager, 1.0), 5.0) - 1.0) / 4.0,
            "disengagement_index": min(disengagement, 30.0) / 30.0,
        }
        contributions = tuple(
            sorted(
                ((name, round(self._WEIGHTS[name] * value, 6)) for name, value in badness.items()),
                key=lambda item: item[1],
                reverse=True,
            )
        )
        return AttritionBaselineResult(
            score=round(sum(value for _, value in contributions), 6),
            contributions=contributions,
        )


triage_keyword_baseline = KeywordTriageBaseline()
resume_overlap_baseline = SkillOverlapBaseline()
attrition_rule_baseline = AttritionRuleBaseline()
