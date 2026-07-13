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
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    metadata: dict[str, Any] | None = None,
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
            metadata=metadata or {},
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
    metadata: dict[str, Any] | None = None,
    cost_query: str | None = None,
    persist: bool = True,
) -> A2AEnvelope:
    """Run a handoff function, certify its output, record telemetry, and persist audit.

    ``func`` may be sync or async and must accept one payload dict. Raw result
    data is only exposed through the envelope payload when certification passes.
    Audit persistence excludes that payload so historical compliance evidence
    does not store raw employee data.
    """
    started_at = time.perf_counter()
    envelope_metadata = dict(metadata or {})
    selected_model = model_id
    if cost_query:
        try:
            from core.cost_router import CostRouter

            route = CostRouter.classify(cost_query)
            selected_model = selected_model or route.selected_model
            envelope_metadata.update(
                {
                    "cost_tier": route.tier,
                    "selected_model": route.selected_model,
                    "cost_route_reason": route.reason,
                    "matched_keyword": route.matched_keyword,
                }
            )
        except Exception as exc:  # noqa: BLE001 - envelope still records the handoff
            envelope_metadata.update(
                {
                    "cost_route_error": type(exc).__name__,
                    "cost_route_reason": "unavailable",
                }
            )
    try:
        result = func(payload)
        if inspect.isawaitable(result):
            result = await result
        _add_cross_agent_consistency(result, envelope_metadata)
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

    _add_cost_metadata(
        payload=payload,
        certification=certified,
        metadata=envelope_metadata,
        token_count=token_count,
    )
    envelope = build_and_record_envelope(
        source_agent=source_agent,
        target_agent=target_agent,
        certification=certified,
        started_at=started_at,
        token_count=token_count,
        model_id=selected_model,
        metadata=envelope_metadata,
    )
    _record_cost_attribution(
        payload=payload,
        certification=certified,
        metadata=envelope_metadata,
        token_count=token_count,
    )
    if persist:
        try:
            from services.audit_service import persist_a2a_envelope

            await persist_a2a_envelope(envelope)
        except Exception:  # noqa: BLE001 - telemetry must not break product flow
            pass
    return envelope


def _add_cross_agent_consistency(result: Any, metadata: dict[str, Any]) -> None:
    source_category = metadata.get("source_category")
    source_priority = metadata.get("source_priority")
    expected_category = metadata.get("expected_target_category")
    expected_priority = metadata.get("expected_target_priority")
    if not any((source_category, source_priority, expected_category, expected_priority)):
        return

    payload = result.model_dump() if hasattr(result, "model_dump") else result
    if not isinstance(payload, dict):
        return
    target_category = payload.get("category") or payload.get("target_category") or expected_category
    target_priority = payload.get("priority") or payload.get("target_priority") or expected_priority

    checks: list[bool] = []
    if source_category and target_category:
        checks.append(str(source_category).upper() == str(target_category).upper())
    if source_priority and target_priority:
        checks.append(str(source_priority).upper() == str(target_priority).upper())
    if not checks:
        return

    consistent = all(checks)
    metadata["cross_agent_consistent"] = consistent
    if not consistent:
        metadata["human_review_required"] = True
        metadata["consistency_violation"] = {
            "source_category": source_category,
            "target_category": target_category,
            "source_priority": source_priority,
            "target_priority": target_priority,
        }


def _add_cost_metadata(
    *,
    payload: dict[str, Any],
    certification: CertifiedResult,
    metadata: dict[str, Any],
    token_count: int | None,
) -> None:
    tier = metadata.get("cost_tier")
    if not isinstance(tier, str) or not tier:
        return
    try:
        from core.cost_attribution import (
            estimate_cost_usd,
            estimate_payload_tokens,
            estimate_text_tokens,
        )

        input_tokens = estimate_payload_tokens(payload)
        output_tokens = (
            token_count
            if token_count is not None
            else estimate_text_tokens(certification.cleaned_output)
        )
        billable = (
            bool(metadata.get("provider_call", True))
            and not bool(metadata.get("cache_hit", False))
            and not bool(metadata.get("prefilter_skip", False))
        )
        attribution = estimate_cost_usd(
            tier,
            input_tokens=input_tokens if billable else 0,
            output_tokens=output_tokens if billable else 0,
        )
        metadata.update(
            {
                "estimated_spend_usd": attribution.cost_usd,
                "tokens_in_estimate": input_tokens,
                "tokens_out_estimate": output_tokens,
                "cost_per_1k": attribution.cost_per_1k,
            }
        )
    except Exception as exc:  # noqa: BLE001 - metadata must not break handoff
        metadata.setdefault("cost_attribution_error", type(exc).__name__)


def _record_cost_attribution(
    *,
    payload: dict[str, Any],
    certification: CertifiedResult,
    metadata: dict[str, Any],
    token_count: int | None,
) -> None:
    tier = metadata.get("cost_tier")
    if not isinstance(tier, str) or not tier:
        return
    try:
        from core.cost_attribution import (
            estimate_payload_tokens,
            estimate_text_tokens,
            record_cost_event,
        )

        output_tokens = (
            token_count
            if token_count is not None
            else estimate_text_tokens(certification.cleaned_output)
        )
        record_cost_event(
            tier=tier,
            input_tokens=estimate_payload_tokens(payload),
            output_tokens=output_tokens,
            provider_call=bool(metadata.get("provider_call", True)),
            cache_hit=bool(metadata.get("cache_hit", False)),
            prefilter_skip=bool(metadata.get("prefilter_skip", False)),
        )
    except Exception:  # noqa: BLE001 - telemetry cannot break the handoff
        return


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
                "metadata": event.metadata,
                "violations": event.certification.violations,
                "timestamp": event.timestamp.isoformat(),
            }
            for event in events[-10:]
        ],
    }


def recent_envelopes(limit: int = 100) -> list[A2AEnvelope]:
    """Return recent envelopes for derived governance metrics."""
    limit = max(1, min(limit, _MAX_EVENTS))
    with _LOCK:
        return list(_RECENT_ENVELOPES)[-limit:]


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
