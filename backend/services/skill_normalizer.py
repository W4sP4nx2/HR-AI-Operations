"""Deterministic skill ontology mapping for resume and job-description data.

The normalizer intentionally does not infer a skill from arbitrary prose.  It
only canonicalizes an explicitly extracted skill string, preserves the source
form, and returns a confidence of ``0.7`` for unknown terms so downstream
review can distinguish a known mapping from a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedSkill:
    """Canonical skill plus provenance for an audit-friendly UI."""

    name: str
    original: str
    category: str | None
    confidence: float

    def as_dict(self) -> dict[str, str | float | None]:
        return {
            "name": self.name,
            "original": self.original,
            "category": self.category,
            "confidence": self.confidence,
        }


class SkillOntologyMapper:
    """Map common aliases while preserving unknown skills for review."""

    DEFAULT_MAPPINGS: dict[str, str] = {
        "py": "Python",
        "python3": "Python",
        "python programming": "Python",
        "js": "JavaScript",
        "javascript": "JavaScript",
        "ecmascript": "JavaScript",
        "ts": "TypeScript",
        "typescript": "TypeScript",
        "fast api": "FastAPI",
        "fastapi": "FastAPI",
        "reactjs": "React",
        "react.js": "React",
        "vue": "Vue.js",
        "vuejs": "Vue.js",
        "postgres": "PostgreSQL",
        "postgresql": "PostgreSQL",
        "psql": "PostgreSQL",
        "mongo": "MongoDB",
        "mongodb": "MongoDB",
        "k8s": "Kubernetes",
        "kube": "Kubernetes",
        "kubernetes": "Kubernetes",
        "aws": "Amazon Web Services",
        "amazon web services": "Amazon Web Services",
        "gcp": "Google Cloud Platform",
        "google cloud": "Google Cloud Platform",
        "sklearn": "Scikit-learn",
        "scikit learn": "Scikit-learn",
        "scikit-learn": "Scikit-learn",
        "pytorch": "PyTorch",
        "tensorflow": "TensorFlow",
        "ci/cd": "CI/CD",
        "cicd": "CI/CD",
        "git": "Git",
        "github": "GitHub",
        "gitlab": "GitLab",
    }

    CATEGORIES: dict[str, tuple[str, ...]] = {
        "Programming Languages": ("Python", "JavaScript", "TypeScript", "Java", "Go", "Rust"),
        "Frameworks": ("FastAPI", "Django", "Flask", "React", "Vue.js", "Angular"),
        "Databases": ("PostgreSQL", "MongoDB", "Redis", "MySQL", "Elasticsearch"),
        "Cloud/DevOps": (
            "Amazon Web Services",
            "Google Cloud Platform",
            "Docker",
            "Kubernetes",
            "CI/CD",
            "Terraform",
        ),
        "ML/AI": ("TensorFlow", "PyTorch", "Scikit-learn", "NLP", "Computer Vision"),
    }

    def __init__(self, mappings: dict[str, str] | None = None) -> None:
        self.mappings = {self._key(k): v for k, v in (mappings or self.DEFAULT_MAPPINGS).items()}
        self._category_by_name = {
            skill: category
            for category, skills in self.CATEGORIES.items()
            for skill in skills
        }

    def normalize(self, skills: list[str] | tuple[str, ...]) -> list[NormalizedSkill]:
        """Normalize, deduplicate, and deterministically sort extracted skills."""
        output: list[NormalizedSkill] = []
        seen: set[str] = set()
        for original in skills:
            if not isinstance(original, str):
                continue
            cleaned = re.sub(r"\s+", " ", original.strip())
            if not cleaned:
                continue
            key = self._key(cleaned)
            canonical = self.mappings.get(key, cleaned)
            canonical = self._title_unknown(canonical)
            identity = self._key(canonical)
            if identity in seen:
                continue
            seen.add(identity)
            output.append(
                NormalizedSkill(
                    name=canonical,
                    original=cleaned,
                    category=self._category_by_name.get(canonical),
                    confidence=1.0 if key in self.mappings else 0.7,
                )
            )
        return sorted(output, key=lambda item: (item.category or "Z", item.name.lower()))

    def normalize_names(self, skills: list[str] | tuple[str, ...]) -> list[str]:
        """Return only canonical names for existing screening call sites."""
        return [item.name for item in self.normalize(skills)]

    def calculate_match_score(
        self,
        candidate_skills: list[NormalizedSkill | dict[str, object] | str],
        required_skills: list[str] | tuple[str, ...],
    ) -> float:
        """Calculate exact canonical overlap; empty requirements score zero."""
        required = {self._key(item.name) for item in self.normalize(required_skills)}
        if not required:
            return 0.0
        candidate_names: list[str] = []
        for item in candidate_skills:
            if isinstance(item, NormalizedSkill):
                candidate_names.append(item.name)
            elif isinstance(item, str):
                candidate_names.append(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                candidate_names.append(item["name"])
        candidate = {self._key(item) for item in self.normalize_names(candidate_names)}
        return len(required & candidate) / len(required)

    @staticmethod
    def _key(value: str) -> str:
        return re.sub(r"[^a-z0-9+#./-]+", " ", value.lower()).strip()

    @staticmethod
    def _title_unknown(value: str) -> str:
        if value in {"C++", "C#", "CI/CD", "GitHub", "GitLab", "PyTorch", "FastAPI"}:
            return value
        return value if any(character.isupper() for character in value[1:]) else value.title()
