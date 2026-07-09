"""Optional CrewAI/LangSmith bridge for certified runtime governance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.a2a_envelope import A2AEnvelope, certified_handoff

try:
    from langsmith import traceable
except Exception:  # noqa: BLE001 - LangSmith is optional in local/dev builds

    def traceable(*_args: Any, **_kwargs: Any):
        def decorator(func):
            return func

        return decorator


@traceable(name="crewai_certified_task")
async def run_certified_crewai_task(
    *,
    task_name: str,
    crew_input: dict[str, Any],
    executor: Callable[[dict[str, Any]], Any],
    objectives: dict[str, Any],
    source_agent: str = "crewai_task",
    target_agent: str = "crewai_consumer",
) -> A2AEnvelope:
    """Execute a CrewAI task through the A2A certifier and optional LangSmith metadata."""
    envelope = await certified_handoff(
        source_agent=source_agent,
        target_agent=target_agent,
        func=executor,
        payload=crew_input,
        objectives=objectives,
    )
    _record_langsmith_metadata(task_name, envelope)
    return envelope


def _record_langsmith_metadata(task_name: str, envelope: A2AEnvelope) -> None:
    try:
        from langsmith import Client

        client = Client()
        client.create_run(
            name=f"a2a_{task_name}",
            run_type="chain",
            inputs={
                "source_agent": envelope.source_agent,
                "target_agent": envelope.target_agent,
            },
            outputs={"certification": envelope.certification.model_dump(mode="json")},
            metadata={
                "trace_id": envelope.trace_id,
                "latency_ms": envelope.latency_ms,
                "is_valid": envelope.certification.is_valid,
                "violations": envelope.certification.violations,
                "model_id": envelope.model_id,
            },
        )
    except Exception:  # noqa: BLE001 - observability must never break the task
        return
