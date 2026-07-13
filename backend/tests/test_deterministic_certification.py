"""Zero-cost proof that governance works without Fireworks credentials."""

from __future__ import annotations

import pytest

from core.a2a_envelope import certified_handoff
from core.fireworks import fireworks_manifest
from tests.fixtures.mock_fireworks_responses import (
    INVALID_TRIAGE_RESPONSE,
    PII_CONTAMINATED_RESPONSE,
    TRIAGE_SCHEMA,
    VALID_TRIAGE_RESPONSE,
)


@pytest.mark.asyncio
async def test_mocked_fireworks_responses_validate_certification_gates(monkeypatch):
    persisted = []

    async def fake_persist(envelope):
        persisted.append(envelope.model_dump(mode="json", exclude={"payload"}))
        return {"id": envelope.trace_id}

    import services.audit_service as audit_service

    monkeypatch.setattr(audit_service, "persist_a2a_envelope", fake_persist)

    env1 = await certified_handoff(
        "triage_agent",
        "policy_qa_agent",
        lambda _payload: VALID_TRIAGE_RESPONSE,
        {},
        {"schema": TRIAGE_SCHEMA},
    )
    assert env1.certification.is_valid is True
    assert env1.payload["category"] == "BENEFITS"

    env2 = await certified_handoff(
        "triage_agent",
        "policy_qa_agent",
        lambda _payload: INVALID_TRIAGE_RESPONSE,
        {},
        {"schema": TRIAGE_SCHEMA},
    )
    assert env2.certification.is_valid is False
    assert env2.payload == {}

    env3 = await certified_handoff(
        "triage_agent",
        "policy_qa_agent",
        lambda _payload: PII_CONTAMINATED_RESPONSE,
        {},
        {"schema": TRIAGE_SCHEMA},
    )
    assert env3.certification.is_valid is False
    assert "123-45-6789" not in str(env3.payload)
    assert env3.certification.redaction_count > 0

    assert len(persisted) == 3
    assert all("payload" not in row for row in persisted)

    telemetry = fireworks_manifest()["runtime_telemetry"]["last_100_certifications"]
    assert telemetry["window"] >= 3
    assert telemetry["pass_rate"] is not None
    assert telemetry["pii_redactions"] >= 1
    assert telemetry["recent"][-1]["source_agent"] == "triage_agent"
