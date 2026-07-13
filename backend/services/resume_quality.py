"""Deterministic quality gates for extracted resume data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from services.resume_extractor import ExtractedResume


@dataclass(frozen=True)
class ResumeQualityReport:
    """Quality result that can be shown to a recruiter and stored in an audit."""

    score: int
    grade: str
    issues: tuple[str, ...]
    needs_human_review: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "quality_grade": self.grade,
            "issues": list(self.issues),
            "needs_human_review": self.needs_human_review,
        }


class ResumeQualityChecker:
    """Score completeness and consistency; never decides candidate suitability."""

    def __init__(self, *, human_review_threshold: int = 70) -> None:
        if not 0 <= human_review_threshold <= 100:
            raise ValueError("human_review_threshold must be between 0 and 100")
        self.human_review_threshold = human_review_threshold

    def check(self, resume: ExtractedResume) -> ResumeQualityReport:
        score = 100
        issues: list[str] = []
        if not resume.email:
            issues.append("Missing email address")
            score -= 15
        if not resume.phone:
            issues.append("Missing phone number")
            score -= 10
        if not resume.work_experience:
            issues.append("No work experience listed")
            score -= 25
        elif len(resume.work_experience) == 1:
            issues.append("Limited work experience (one position)")
            score -= 8
        if not resume.skills:
            issues.append("No skills listed")
            score -= 20
        elif len(resume.skills) < 3:
            issues.append("Very few skills listed")
            score -= 8
        if not resume.education:
            issues.append("No education listed")
            score -= 10
        if resume.has_gaps and not resume.gap_explanation:
            issues.append("Unexplained employment gap detected")
            score -= 12
        if resume.total_years_experience > 50:
            issues.append("Unrealistic total years of experience")
            score -= 20
        for experience in resume.work_experience:
            if _date_order_invalid(experience.start_date, experience.end_date):
                issues.append(f"Invalid dates at {experience.company or 'unknown company'}")
                score -= 10
                break
        score = max(0, min(100, score))
        return ResumeQualityReport(
            score=score,
            grade=self._grade(score),
            issues=tuple(issues),
            needs_human_review=score < self.human_review_threshold or bool(resume.warnings),
        )

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"


def _date_order_invalid(start: str | None, end: str | None) -> bool:
    """Validate YYYY-MM dates while treating unknown/free-form dates as reviewable."""
    if not start or not end or end.lower() in {"present", "current", "now"}:
        return False
    try:
        start_date = _parse_month(start)
        end_date = _parse_month(end)
    except ValueError:
        return False
    return end_date < start_date


def _parse_month(value: str) -> date:
    year, month = value.strip()[:7].split("-")
    return date(int(year), int(month), 1)
