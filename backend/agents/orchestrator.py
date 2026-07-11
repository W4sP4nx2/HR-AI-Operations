"""Fireworks-aware A2A orchestrator.

This module plans and certifies dispatches without performing network I/O. Live
execution stays in the existing agent/provider paths; the orchestrator's job is
to make the routing topology explicit, testable, and visible in the product.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

from agents.a2a_cards import (
    AGENT_CARDS,
    REQUEST_ALIASES,
    A2ACard,
    cards_to_tools,
    get_card,
)
from core.a2a_envelope import A2AEnvelope, certified_handoff
from core.fireworks import (
    build_batch_jsonl,
    build_chat_body,
    build_resume_vision_body,
    configured_models,
)
from core.llm_factory import pick_model_for_role

ORCHESTRATOR_SYSTEM_PROMPT = """You are the HR AI Command Center orchestrator.
Choose exactly one A2A tool by reading each tool description. Prefer the card
whose serving path, Fireworks primitives, cost posture, and risk posture match
the request. Never invent a model id. The selected dispatcher must use only
models injected through ALLOWED_MODELS, and every cross-agent handoff must return
a certified A2A envelope before another agent consumes it."""

DispatchMode = Literal["batch", "reasoning", "standard", "stream", "vision"]


class OrchestrationPlan(BaseModel):
    """Concrete dispatch plan derived from one A2A card."""

    request_type: str
    selected_agent: str
    selected_tool: str
    owner_team: str
    serving_path: str
    dispatch_mode: DispatchMode
    fireworks_primitives: list[str]
    selected_model: str
    model_selection_source: str = "ALLOWED_MODELS"
    cost_posture: str
    risk_posture: str
    human_review_triggers: list[str]
    collaboration_targets: list[str]
    reason: str
    request_contract: dict[str, Any]


def select_model_for_card(card: A2ACard, models: Sequence[str] | None = None) -> str:
    """Select a concrete model for a card from the injected allow-list only."""
    allowed = list(models) if models is not None else configured_models()
    if not allowed:
        raise RuntimeError("ALLOWED_MODELS is empty or unset")

    lowered_preferences = [hint.lower() for hint in card.model_family_preferences]
    for hint in lowered_preferences:
        for model_id in allowed:
            if hint and hint in model_id.lower():
                return model_id

    role = f"{card.agent_name}:{','.join(card.fireworks_primitives)}:{card.cost_posture}"
    return pick_model_for_role(role, list(allowed))


def build_orchestration_plan(
    request_type: str,
    payload: Mapping[str, Any],
    *,
    models: Sequence[str] | None = None,
) -> OrchestrationPlan:
    """Build a no-key Fireworks/A2A dispatch plan for one workload."""
    card = _infer_card(request_type, payload)
    model_id = select_model_for_card(card, models)
    dispatch_mode = _dispatch_mode(card, payload)
    request_contract = _dispatch_contract(card, payload, model_id, dispatch_mode)
    return OrchestrationPlan(
        request_type=request_type,
        selected_agent=card.agent_name,
        selected_tool=card.tool_name(),
        owner_team=card.owner_team,
        serving_path=card.serving_path,
        dispatch_mode=dispatch_mode,
        fireworks_primitives=list(card.fireworks_primitives),
        selected_model=model_id,
        cost_posture=card.cost_posture,
        risk_posture=card.risk_posture,
        human_review_triggers=list(card.human_review_triggers),
        collaboration_targets=list(card.collaboration_targets),
        reason=_routing_reason(card, dispatch_mode),
        request_contract=request_contract,
    )


async def orchestrate(
    request_type: str,
    payload: Mapping[str, Any],
    *,
    models: Sequence[str] | None = None,
) -> A2AEnvelope:
    """Return a certified envelope containing the dispatch plan."""
    plan = build_orchestration_plan(request_type, payload, models=models)
    return await certified_handoff(
        source_agent="orchestrator_agent",
        target_agent=plan.selected_agent,
        func=lambda _: plan.model_dump(),
        payload=dict(payload),
        objectives={
            "schema": OrchestrationPlan.model_json_schema(),
            "require_pii_free": True,
        },
        model_id=plan.selected_model,
        metadata={
            "selected_tool": plan.selected_tool,
            "serving_path": plan.serving_path,
            "dispatch_mode": plan.dispatch_mode,
            "fireworks_primitives": plan.fireworks_primitives,
            "cost_tier": (plan.cost_posture if plan.cost_posture != "batch" else "standard"),
            "provider_call": False,
            "prefilter_skip": True,
        },
        persist=False,
    )


def orchestrator_manifest() -> dict[str, Any]:
    """Return no-secret orchestrator metadata for product/lifecycle views."""
    return {
        "system_prompt_contract": ORCHESTRATOR_SYSTEM_PROMPT,
        "model_selection": "preferences are hints; selected_model must be in ALLOWED_MODELS",
        "tools": cards_to_tools(),
        "routing_examples": {
            workload: {
                "agent": get_card(workload).agent_name,
                "serving_path": get_card(workload).serving_path,
                "fireworks_primitives": get_card(workload).fireworks_primitives,
            }
            for workload in [
                "structured_classification",
                "policy_qa",
                "resume_analysis",
                "attrition_explanation",
                "onboarding",
            ]
        },
    }


def _infer_card(request_type: str, payload: Mapping[str, Any]) -> A2ACard:
    normalized = request_type.strip().lower()
    if normalized in AGENT_CARDS or normalized in REQUEST_ALIASES:
        return get_card(normalized)

    text = " ".join(
        str(value).lower()
        for key, value in payload.items()
        if key in {"input", "message", "query", "text", "prompt"} and value is not None
    )
    if any(term in text for term in ("resume", "candidate", "job description", "skills")):
        return get_card("resume_analysis")
    if any(term in text for term in ("attrition", "retention", "promotion", "risk")):
        return get_card("attrition_explanation")
    if any(term in text for term in ("onboard", "new hire", "training", "account")):
        return get_card("onboarding")
    if any(term in text for term in ("policy", "benefit", "pto", "leave", "compliance")):
        return get_card("policy_qa")
    return get_card("triage")


def _dispatch_mode(card: A2ACard, payload: Mapping[str, Any]) -> DispatchMode:
    if "vision" in card.fireworks_primitives and payload.get("image_urls"):
        return "vision"
    if "reasoning" in card.fireworks_primitives:
        return "reasoning"
    if card.serving_path == "serverless_batch":
        return "batch"
    if card.serving_path == "serverless_streaming":
        return "stream"
    return "standard"


def _dispatch_contract(
    card: A2ACard,
    payload: Mapping[str, Any],
    model_id: str,
    dispatch_mode: DispatchMode,
) -> dict[str, Any]:
    prompt = _payload_prompt(payload)
    if dispatch_mode == "vision":
        image_urls = payload.get("image_urls")
        if not isinstance(image_urls, Sequence) or isinstance(image_urls, (str, bytes)):
            raise ValueError("vision dispatch requires image_urls")
        return {
            "kind": "chat.completions",
            "mode": "vision_json_schema",
            "body": build_resume_vision_body(
                model_id=model_id,
                image_urls=[str(url) for url in image_urls],
                session_id=_session_id(payload),
            ),
        }

    if dispatch_mode == "batch":
        records = payload.get("records")
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or not records:
            records = [{"custom_id": "a2a-request-1", "prompt": prompt}]
        jsonl = build_batch_jsonl(
            [dict(record) for record in records],
            model_id=model_id,
            system_prompt=_system_prompt(card),
            max_tokens=int(payload.get("max_tokens", 800) or 800),
        )
        return {
            "kind": "batch",
            "mode": "jsonl",
            "model": model_id,
            "jsonl_preview": jsonl.splitlines()[:3],
            "record_count": len(jsonl.splitlines()),
        }

    body = build_chat_body(
        model_id=model_id,
        messages=[
            {"role": "system", "content": _system_prompt(card)},
            {"role": "user", "content": prompt},
        ],
        max_tokens=int(payload.get("max_tokens", 600) or 600),
        temperature=float(payload.get("temperature", 0.0) or 0.0),
        schema_name=card.output_contract,
        json_schema=_output_schema(card),
        session_id=_session_id(payload),
        service_tier="standard",
    )
    if dispatch_mode == "stream":
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    if dispatch_mode == "reasoning":
        body["reasoning_effort"] = str(payload.get("reasoning_effort", "medium"))
    return {"kind": "chat.completions", "mode": dispatch_mode, "body": body}


def _output_schema(card: A2ACard) -> dict[str, Any]:
    from agents.contracts import AGENT_SPECS

    return dict(AGENT_SPECS[card.agent_name].output_model.model_json_schema())


def _payload_prompt(payload: Mapping[str, Any]) -> str:
    for key in ("prompt", "query", "message", "input", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(dict(payload), sort_keys=True, default=str)


def _session_id(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("session_id")
    return value if isinstance(value, str) and value else None


def _system_prompt(card: A2ACard) -> str:
    return (
        f"You are {card.label}. Return JSON matching {card.output_contract}. "
        "Keep HR output advisory, citation-backed when policy is involved, and "
        "safe for certified A2A handoff."
    )


def _routing_reason(card: A2ACard, dispatch_mode: DispatchMode) -> str:
    primitives = ", ".join(card.fireworks_primitives)
    return (
        f"Selected {card.agent_name} because {dispatch_mode} uses {primitives} "
        f"with {card.cost_posture} cost posture and {card.risk_posture} risk posture."
    )
