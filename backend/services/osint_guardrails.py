"""Consent and minimisation rules for any future professional OSINT adapter.

This module intentionally contains no scraper and no network client.  Public
web data can still become sensitive personal data, and automated employment
decisions based on it create a high-risk workflow.  The adapter boundary below
requires explicit consent, a documented purpose, source allow-listing, and
removes protected-trait fields before a graph can be rendered.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

PROTECTED_FIELDS = frozenset(
    {
        "age",
        "birth_date",
        "disability",
        "gender",
        "health",
        "nationality",
        "political_affiliation",
        "race",
        "religion",
        "sexual_orientation",
        "union_membership",
    }
)

ALLOWED_PURPOSES = frozenset({"professional_credential_review", "public_work_sample_review"})


class OSINTPolicyError(ValueError):
    """A request violates the explicit professional-OSINT policy."""


@dataclass(frozen=True)
class OSINTRequest:
    subject: str
    purpose: str
    consent: bool
    sources: tuple[str, ...]


@dataclass(frozen=True)
class OSINTObservation:
    subject: str
    source: str
    claim: str
    confidence: float
    collected_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "source": self.source,
            "claim": self.claim,
            "confidence": self.confidence,
            "collected_at": self.collected_at,
        }


def osint_enabled() -> bool:
    """OSINT remains opt-in even when an adapter is later installed."""
    return os.environ.get("OSINT_ENABLED", "false").strip().lower() == "true"


def validate_request(
    *,
    subject: str,
    purpose: str,
    consent: bool,
    sources: list[str] | tuple[str, ...],
) -> OSINTRequest:
    normalized_subject = re.sub(r"\s+", " ", subject.strip())
    normalized_purpose = purpose.strip().lower()
    if not normalized_subject:
        raise OSINTPolicyError("subject is required")
    if not consent:
        raise OSINTPolicyError("explicit subject consent is required")
    if normalized_purpose not in ALLOWED_PURPOSES:
        raise OSINTPolicyError(
            "OSINT purpose must be professional_credential_review or public_work_sample_review"
        )
    cleaned_sources = tuple(_validate_source(source) for source in sources)
    if not cleaned_sources:
        raise OSINTPolicyError("at least one allowlisted source is required")
    return OSINTRequest(normalized_subject, normalized_purpose, True, cleaned_sources)


def sanitize_claims(claims: dict[str, Any]) -> dict[str, str]:
    """Keep only reviewable string claims and drop protected traits."""
    sanitized: dict[str, str] = {}
    for key, value in claims.items():
        normalized_key = re.sub(r"[^a-z0-9_]+", "_", str(key).lower()).strip("_")
        if normalized_key in PROTECTED_FIELDS:
            continue
        if isinstance(value, str) and value.strip():
            sanitized[normalized_key] = value.strip()[:2000]
    return sanitized


def build_observations(
    *,
    subject: str,
    source: str,
    claims: dict[str, Any],
    confidence: float = 0.5,
) -> list[OSINTObservation]:
    """Turn operator-supplied evidence into auditable observations."""
    source = _validate_source(source)
    if not 0.0 <= confidence <= 1.0:
        raise OSINTPolicyError("confidence must be between 0 and 1")
    now = datetime.now(UTC).isoformat()
    return [
        OSINTObservation(subject, source, f"{key}: {value}", confidence, now)
        for key, value in sanitize_claims(claims).items()
    ]


def build_graph(observations: list[OSINTObservation]) -> dict[str, Any]:
    """Build a minimal professional graph without deriving hidden relationships."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for observation in observations:
        subject_id = f"subject:{observation.subject.lower()}"
        source_id = f"source:{observation.source.lower()}"
        nodes.setdefault(subject_id, {"id": subject_id, "type": "person_or_entity"})
        nodes.setdefault(source_id, {"id": source_id, "type": "source"})
        edges.append(
            {
                "source": subject_id,
                "target": source_id,
                "type": "professional_observation",
                "claim": observation.claim,
                "confidence": observation.confidence,
                "collected_at": observation.collected_at,
            }
        )
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "automated_decision": False,
        "requires_human_review": True,
    }


def _validate_source(source: str) -> str:
    normalized = source.strip().lower()
    if not normalized:
        raise OSINTPolicyError("source is required")
    parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
    if parsed.scheme != "https" or not parsed.hostname:
        raise OSINTPolicyError("OSINT sources must use HTTPS")
    allowed = {
        item.strip().lower()
        for item in os.environ.get("OSINT_ALLOWED_DOMAINS", "github.com,orcid.org").split(",")
        if item.strip()
    }
    host = parsed.hostname.lower().removeprefix("www.")
    if host not in allowed and not any(host.endswith("." + domain) for domain in allowed):
        raise OSINTPolicyError("source domain is not allowlisted")
    return host
