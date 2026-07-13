"""Audit persistence helpers for runtime governance artifacts."""

from __future__ import annotations

from typing import Any

from core.a2a_envelope import A2AEnvelope
from core.memory import memory


async def record_action(
    *,
    agent: str,
    action: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    """Persist a privacy-safe material action for visible audit reporting."""
    return await memory.log_audit(agent, action, input_data, output_data, status)


async def persist_a2a_envelope(envelope: A2AEnvelope) -> dict[str, Any]:
    """Persist a certified envelope without storing the raw payload."""
    return await memory.log_audit(
        "a2a_envelope",
        "certified_handoff",
        {
            "trace_id": envelope.trace_id,
            "source_agent": envelope.source_agent,
            "target_agent": envelope.target_agent,
        },
        envelope.model_dump(mode="json", exclude={"payload"}),
        "success" if envelope.certification.is_valid else "error",
    )
