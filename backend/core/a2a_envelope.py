"""Certified A2A envelope and rolling runtime telemetry.

Agents and provider adapters should pass certified envelopes instead of raw
payloads when one component hands output to another. The envelope is deliberately
small and JSON-serializable so it can be persisted to audit storage later without
another schema redesign.
"""

from __future__ import annotations

import inspect
import json
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from core.fireworks_certifier import CertifiedResult, FireworksOutputCertifier

_MAX_EVENTS = 100
_LOCK = Lock()
_RECENT_ENVELOPES: deque["A2AEnvelope"] = deque(maxlen=_MAX_EVENTS)


class A2AEnvelope(BaseModel):
    """Mandatory contract for inter-agent or provider-to-agent communication."""

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    source_agent: str
    target_agent: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any]
    certification: CertifiedResult
    latency_ms: float | None = Field(default=None, ge=0.0)
    token_count: int | None = Field(default=None, ge=0)
    model_id: str | None = None


def payload_from_certification(certification: CertifiedResult) -> dict[str, Any]:
    """Return a dict payload only when certification passed."""
    if not certification.is_valid:
        return {}
    try:
        payload = json.loads(certification.cleaned_output)
    except json.JSONDecodeError:
        return {"output": certification.cleaned_output}
    return payload if isinstance(payload, dict) else {"output": payload}


def record_a2a_envelope(envelope: A2AEnvelope) -> A2AEnvelope:
    """Record one envelope in a process-local rolling window."""
    with _LOCK:
        _RECENT_ENVELOPES.append(envelope)
    return envelope


def build_and_record_envelope(
    *,
    source_agent: str,
    target_agent: str,
    certification: CertifiedResult,
    started_at: float,
    token_count: int | None = None,
    model_id: str | None = None,
) -> A2AEnvelope:
    """Build and record an envelope from a certification result."""
    return record_a2a_envelope(
        A2AEnvelope(
            source_agent=source_agent,
            target_agent=target_agent,
            payload=payload_from_certification(certification),
            certification=certification,
            latency_ms=max(0.0, (time.perf_counter() - started_at) * 1000),
            token_count=token_count,
            model_id=model_id,
        )
    )


async def certified_handoff(
    source_agent: str,
    target_agent: str,
    func: Callable[[dict[str, Any]], Any],
    payload: dict[str, Any],
    objectives: dict[str, Any],
    token_count: int | None = None,
    model_id: str | None = None,
    persist: bool = True,
) -> A2AEnvelope:
    """Run a handoff function, certify its output, record telemetry, and persist audit.

    ``func`` may be sync or async and must accept one payload dict. Raw result
    data is only exposed through the envelope payload when certification passes.
    Audit persistence excludes that payload so historical compliance evidence
    does not store raw employee data.
    """
    started_at = time.perf_counter()
    try:
        result = func(payload)
        if inspect.isawaitable(result):
            result = await result
        certified = FireworksOutputCertifier().certify(
            _serialize_for_certification(result),
            objectives,
        )
        if not isinstance(certified, CertifiedResult):
            certified = CertifiedResult(
                is_valid=False,
                cleaned_output="{}",
                confidence=0.0,
                violations=["schema_validation_failed"],
            )
    except Exception as exc:  # noqa: BLE001 - envelope carries failure evidence
        certified = CertifiedResult(
            is_valid=False,
            cleaned_output="{}",
            confidence=0.0,
            violations=[f"handoff_exception:{type(exc).__name__}"],
        )

    envelope = build_and_record_envelope(
        source_agent=source_agent,
        target_agent=target_agent,
        certification=certified,
        started_at=started_at,
        token_count=token_count,
        model_id=model_id,
    )
    if persist:
        try:
            from services.audit_service import persist_a2a_envelope

            await persist_a2a_envelope(envelope)
        except Exception:  # noqa: BLE001 - telemetry must not break product flow
            pass
    return envelope


def telemetry_snapshot(limit: int = 100) -> dict[str, Any]:
    """Return aggregate and recent certification telemetry."""
    limit = max(1, min(limit, _MAX_EVENTS))
    with _LOCK:
        events = list(_RECENT_ENVELOPES)[-limit:]

    total = len(events)
    passed = sum(1 for event in events if event.certification.is_valid)
    latencies = sorted(event.latency_ms for event in events if event.latency_ms is not None)
    token_count = sum(event.token_count or 0 for event in events)
    redactions = sum(event.certification.redaction_count for event in events)
    violations: dict[str, int] = {}
    for event in events:
        for violation in event.certification.violations:
            violations[violation] = violations.get(violation, 0) + 1

    return {
        "window": total,
        "pass_rate": (passed / total) if total else None,
        "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "pii_redactions": redactions,
        "token_count": token_count,
        "violations": violations,
        "recent": [
            {
                "trace_id": event.trace_id,
                "source_agent": event.source_agent,
                "target_agent": event.target_agent,
                "is_valid": event.certification.is_valid,
                "confidence": event.certification.confidence,
                "latency_ms": event.latency_ms,
                "token_count": event.token_count,
                "model_id": event.model_id,
                "violations": event.certification.violations,
                "timestamp": event.timestamp.isoformat(),
            }
            for event in events[-10:]
        ],
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percentile))))
    return values[index]


def _serialize_for_certification(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "model_dump_json"):
        return str(result.model_dump_json())
    return json.dumps(result, default=str)
