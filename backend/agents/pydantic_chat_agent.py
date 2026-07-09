"""Governed Pydantic AI chat wrapper.

The existing chat agent owns tool dispatch and deterministic fallback. This
module adds the stricter conversation contract: every non-streaming chat turn is
normalized into a typed schema, certified, cost-routed, and exposed with a trace
id before the UI persists or renders the assistant answer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from core.a2a_envelope import A2AEnvelope, certified_handoff
from core.chat_schemas import ChatResponse, chat_response_objectives, normalize_chat_result
from core.cost_router import CostRoute, CostRouter
from core.genai_lifecycle import controlled_parameters, policy_for
from core.runtime_key import llm_active

STRUCTURED_CHAT_PROMPT = """You are an HR assistant.
- Answer only from provided policy or workflow context.
- Keep answers under 500 characters.
- Cite specific policy ids when policy context is used.
- Flag sensitive HR actions for human review.
- Never provide legal advice or make adverse employment decisions."""


@dataclass
class PydanticChatDeps:
    """Runtime context for future typed chat tools."""

    session_id: str = ""
    history: list[dict[str, str]] = field(default_factory=list)


def route_chat_message(user_query: str) -> CostRoute:
    """Return the auditable cost route for one chat turn."""
    return CostRouter.classify(user_query)


def build_structured_chat_agent(user_query: str, session_id: str = "") -> Any | None:
    """Build a typed Pydantic AI agent for live structured chat.

    This constructor performs no network call. It is intentionally separate from
    ``handle_chat_message`` so tests can validate schema wiring without spending
    provider credits. The live non-streaming endpoint currently certifies the
    existing tool-aware chat result; this typed agent is the next step for moving
    the same contract directly into provider structured output.
    """
    if not llm_active():
        return None
    try:
        from pydantic_ai import Agent
    except Exception:  # noqa: BLE001 - optional dependency absent
        return None

    from core.llm_factory import get_request_scoped_model

    route = _route_or_none(user_query)
    if route is None:
        return None
    model = get_request_scoped_model(role=_role_for_route(route), session_id=session_id)
    if model is None:
        return None
    return Agent(
        model,
        output_type=ChatResponse,
        system_prompt=STRUCTURED_CHAT_PROMPT,
        deps_type=PydanticChatDeps,
        retries=policy_for("chat").retries,
    )


async def run_typed_provider_chat(
    user_query: str,
    *,
    policy_context: str = "",
    session_id: str = "",
    history: list[dict[str, str]] | None = None,
) -> ChatResponse | None:
    """Run the typed Pydantic AI agent when live provider config is available."""
    agent = build_structured_chat_agent(user_query, session_id=session_id)
    if agent is None:
        return None
    context = policy_context.strip() or "No retrieved policy context was provided."
    prompt = f"Policy/workflow context:\n{context}\n\nUser question:\n{user_query}"
    deps = PydanticChatDeps(session_id=session_id, history=history or [])
    result = await asyncio.wait_for(
        agent.run(
            prompt,
            deps=deps,
            model_settings=controlled_parameters("chat"),
        ),
        timeout=policy_for("chat").timeout_seconds,
    )
    return result.output


async def handle_chat_message(
    message: str,
    history: list[dict[str, str]] | None = None,
    session_id: str = "",
) -> A2AEnvelope:
    """Execute the current chat flow and certify its structured response."""
    from agents.chat_agent import chat
    from core.safety import redact_pii
    from services.input_shield import sanitize_text

    raw_result = await chat(message, history or [], session_id)
    structured = normalize_chat_result(raw_result, query=message)
    redacted_message = redact_pii(sanitize_text(message))

    async def certify_existing_result(_payload: dict[str, Any]) -> ChatResponse:
        return structured

    route = _route_or_none(redacted_message)
    return await certified_handoff(
        source_agent="user_chat",
        target_agent="pydantic_chat_agent",
        func=certify_existing_result,
        payload={
            "message": redacted_message,
            "session_id": session_id,
        },
        objectives=chat_response_objectives(min_confidence=0.7),
        model_id=route.selected_model if route else None,
        metadata={
            "chat_mode": raw_result.get("mode", "unknown"),
            "tool_count": len(raw_result.get("tool_calls") or []),
            "source_policy_count": len(structured.source_policy_ids),
            "cost_route_available": route is not None,
            "provider_call": raw_result.get("mode") == "full",
            "prefilter_skip": raw_result.get("mode") != "full",
        },
        cost_query=redacted_message,
    )


async def governed_chat(
    message: str,
    history: list[dict[str, str]] | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Return the existing chat response shape plus certification evidence."""
    from agents.chat_agent import chat

    raw_result = await chat(message, history or [], session_id)
    structured = normalize_chat_result(raw_result, query=message)

    async def certify_existing_result(_payload: dict[str, Any]) -> ChatResponse:
        return structured

    route = _route_or_none(message)
    envelope = await certified_handoff(
        source_agent="user_chat",
        target_agent="pydantic_chat_agent",
        func=certify_existing_result,
        payload={"message": message, "session_id": session_id},
        objectives=chat_response_objectives(min_confidence=0.7),
        model_id=route.selected_model if route else None,
        metadata={
            "chat_mode": raw_result.get("mode", "unknown"),
            "tool_count": len(raw_result.get("tool_calls") or []),
            "source_policy_count": len(structured.source_policy_ids),
            "cost_route_available": route is not None,
            "provider_call": raw_result.get("mode") == "full",
            "prefilter_skip": raw_result.get("mode") != "full",
        },
        cost_query=message,
    )
    if envelope.certification.is_valid:
        certified = ChatResponse.model_validate(envelope.payload)
        raw_result["reply"] = certified.answer
        raw_result["structured"] = certified.model_dump()
    else:
        raw_result["reply"] = "I could not safely certify that answer. Please ask HR to review it."
        raw_result["structured"] = None
        raw_result["mode"] = "blocked"
    raw_result["trace_id"] = envelope.trace_id
    raw_result["certification"] = {
        "is_valid": envelope.certification.is_valid,
        "confidence": envelope.certification.confidence,
        "violations": envelope.certification.violations,
        "redaction_count": envelope.certification.redaction_count,
    }
    raw_result["cost_route"] = {
        "tier": envelope.metadata.get("cost_tier", route.tier if route else "unavailable"),
        "selected_model": envelope.model_id or (route.selected_model if route else None),
        "reason": envelope.metadata.get(
            "cost_route_reason", route.reason if route else "allowlist_unavailable"
        ),
    }
    return raw_result


def _route_or_none(user_query: str) -> CostRoute | None:
    try:
        return route_chat_message(user_query)
    except RuntimeError:
        return None


def _role_for_route(route: CostRoute) -> str:
    if route.tier == "economy":
        return "fast"
    return "chat"
