"""Optional CrewAI/LangSmith bridge for certified runtime governance.

CrewAI is an execution adapter for bounded narrative tasks.  The adapter never
decides authorization and never sends raw HR payloads to LangSmith.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from typing import Any

from core.a2a_envelope import A2AEnvelope, certified_handoff
from core.cost_guard import TokenBudgetGuard

CREWAI_USE_CASES = {
    "resume_narrative": "Summarize evidence from an already blinded profile for a human reviewer.",
    "evidence_digest": "Turn certified skill evidence into a short review note.",
    "conflict_flag": "Identify conflicting evidence and route it to human review.",
    "hierarchical_resume_review": (
        "Talent Review Manager delegates to Resume Evidence Analyst and Fairness Policy Guard."
    ),
    "hierarchical_policy_case": (
        "HR Operations Manager delegates to Case Triage Analyst and Policy Grounding Guard."
    ),
}


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
    cost_query = _cost_query(task_name, crew_input)
    envelope = await certified_handoff(
        source_agent=source_agent,
        target_agent=target_agent,
        func=executor,
        payload=crew_input,
        objectives=objectives,
        cost_query=cost_query,
    )
    attribution = crewai_cost_attribution(task_name, crew_input, envelope)
    envelope.metadata.update(
        {
            "integration": "crewai",
            "task_name": task_name,
            "estimated_cost_usd": attribution.cost_usd,
            "tokens_in_estimate": attribution.tokens_in,
            "tokens_out": attribution.tokens_out,
            "cost_per_1k": attribution.cost_per_1k,
        }
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
                "trace_id": envelope.trace_id,
            },
            outputs={
                "certification": {
                    "is_valid": envelope.certification.is_valid,
                    "confidence": envelope.certification.confidence,
                    "redaction_count": envelope.certification.redaction_count,
                    "violations": envelope.certification.violations,
                }
            },
            metadata={
                "trace_id": envelope.trace_id,
                "latency_ms": envelope.latency_ms,
                "is_valid": envelope.certification.is_valid,
                "violations": envelope.certification.violations,
                "model_id": envelope.model_id,
                "raw_payload_sent": False,
                **envelope.metadata,
            },
        )
    except Exception:  # noqa: BLE001 - observability must never break the task
        return


def _cost_query(task_name: str, crew_input: dict[str, Any]) -> str:
    for key in ("query", "question", "ticket_text", "task"):
        value = crew_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return task_name


def crewai_available() -> bool:
    """Return whether the optional CrewAI package is importable."""
    return importlib.util.find_spec("crewai") is not None


def _estimated_input_tokens(crew_input: dict[str, Any]) -> int:
    messages = [{"role": "user", "content": str(value)} for value in crew_input.values()]
    return TokenBudgetGuard().estimate_messages(messages)


def crewai_cost_attribution(task_name: str, crew_input: dict[str, Any], envelope: A2AEnvelope):
    """Return deterministic cost attribution for tests and optional dashboards."""
    from agents.langsmith_cost_tracker import estimate_cost_usd

    tier = str(envelope.metadata.get("cost_tier") or "standard")
    return estimate_cost_usd(
        tier,
        tokens_in=_estimated_input_tokens(crew_input),
        tokens_out=envelope.token_count or 0,
    )
