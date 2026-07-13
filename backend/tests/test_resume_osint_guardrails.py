"""Tests for the opt-in, consent-gated professional OSINT boundary."""

from __future__ import annotations

import pytest


def test_osint_requires_consent_and_allowlisted_https_source() -> None:
    from services.osint_guardrails import OSINTPolicyError, validate_request

    with pytest.raises(OSINTPolicyError, match="consent"):
        validate_request(
            subject="candidate-1",
            purpose="professional_credential_review",
            consent=False,
            sources=["https://github.com/example"],
        )
    with pytest.raises(OSINTPolicyError, match="allowlisted"):
        validate_request(
            subject="candidate-1",
            purpose="professional_credential_review",
            consent=True,
            sources=["https://example.invalid/profile"],
        )


def test_osint_drops_protected_traits_and_builds_review_graph(monkeypatch) -> None:
    monkeypatch.setenv("OSINT_ALLOWED_DOMAINS", "github.com")
    from services.osint_guardrails import build_graph, build_observations

    observations = build_observations(
        subject="candidate-1",
        source="https://github.com/example",
        claims={"repository": "hr-demo", "religion": "redact", "language": "Python"},
        confidence=0.8,
    )
    assert len(observations) == 2
    graph = build_graph(observations)
    assert graph["automated_decision"] is False
    assert graph["requires_human_review"] is True
    assert all("religion" not in edge["claim"] for edge in graph["edges"])


def test_osint_disabled_by_default() -> None:
    from services.osint_guardrails import osint_enabled

    assert osint_enabled() is False


def test_osint_route_is_explicitly_unavailable_without_adapter() -> None:
    import asyncio

    from api.routes.osint import OSINTQuery, search_osint

    response = asyncio.run(
        search_osint(
            OSINTQuery(
                subject="candidate-1",
                purpose="professional_credential_review",
                consent=True,
                sources=["https://github.com/example"],
            ),
            {},
        )
    )
    assert response["status"] == "unavailable"
    assert response["data"]["capability"] == "osint_adapter"
