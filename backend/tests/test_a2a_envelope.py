"""A2A envelope telemetry carries certification and NFR evidence."""

from __future__ import annotations

import time

import pytest

from core.a2a_envelope import build_and_record_envelope, certified_handoff, telemetry_snapshot
from core.fireworks_certifier import CertifiedResult


def test_a2a_envelope_records_certification_latency_tokens_and_redactions():
    started_at = time.perf_counter()
    certification = CertifiedResult(
        is_valid=True,
        cleaned_output='{"answer":"ok"}',
        confidence=0.9,
        violations=[],
        redaction_count=2,
    )

    envelope = build_and_record_envelope(
        source_agent="policy_qa_agent",
        target_agent="retention_resolver",
        certification=certification,
        started_at=started_at,
        token_count=42,
        model_id="tenant/model",
    )
    snapshot = telemetry_snapshot(1)

    assert envelope.payload == {"answer": "ok"}
    assert snapshot["window"] == 1
    assert snapshot["pass_rate"] == 1.0
    assert snapshot["pii_redactions"] >= 2
    assert snapshot["token_count"] >= 42
    assert snapshot["recent"][-1]["source_agent"] == "policy_qa_agent"


@pytest.mark.asyncio
async def test_certified_handoff_filters_invalid_payload_and_persists(monkeypatch):
    persisted = []

    async def fake_persist(envelope):
        persisted.append(envelope.model_dump(mode="json", exclude={"payload"}))
        return {"id": "audit-1"}

    import services.audit_service as audit_service

    monkeypatch.setattr(audit_service, "persist_a2a_envelope", fake_persist)

    async def executor(_payload):
        return {
            "answer": "email jane@example.com",
            "confidence_score": 0.9,
        }

    envelope = await certified_handoff(
        source_agent="triage_agent",
        target_agent="policy_qa_agent",
        func=executor,
        payload={"ticket_text": "raw employee text"},
        objectives={
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["answer", "confidence_score"],
                "additionalProperties": False,
            },
            "require_pii_free": True,
        },
    )

    assert envelope.certification.is_valid is False
    assert envelope.payload == {}
    assert "pii_detected" in envelope.certification.violations
    assert persisted
    assert "payload" not in persisted[0]
