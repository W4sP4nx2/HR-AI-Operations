"""Visible single-orchestrator routing for governed HR workflows.

The orchestrator does not model inter-agent communication. It chooses one
serving path and allowlisted model, exposes cost/cache/certification metadata,
and writes a privacy-safe audit event. Provider execution remains behind
``core.llm_factory`` in the workflow that consumes the plan.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from agents.a2a_cards import (
    GEMMA_MULTIMODAL_CARD,
    ORCHESTRATOR_CARDS,
    A2ACard,
    cards_to_tools,
    get_card,
)
from core.a2a_envelope import certified_handoff
from core.config import settings
from core.cost_router import CostRoute, CostRouter
from core.fireworks import configured_models
from core.fireworks_certifier import CertifiedResult
from core.runtime_key import llm_active
from services.audit_service import record_action
from services.semantic_cache import HRSemanticCache, context_hash

Workflow = Literal[
    "attrition",
    "onboarding",
    "policy_qa",
    "resume_screening",
    "triage",
]
ServingPath = Literal["batch", "deploy_on_demand", "fast", "standard"]
ExecutionMode = Literal["deterministic_fallback", "planned_live"]

ORCHESTRATOR_VERSION = "single-orchestrator-v2-a2a"
TOOLS = cards_to_tools(ORCHESTRATOR_CARDS)
_PLAN_CACHE = HRSemanticCache(maxsize=128, ttl_seconds=settings.semantic_cache_ttl)
_METRICS = {
    "plans_total": 0,
    "cache_hits": 0,
    "certifications_passed": 0,
    "certifications_failed": 0,
    "audit_events_recorded": 0,
}
_LAST_ROUTE: dict[str, Any] = {}


class OrchestrationPlan(BaseModel):
    """Privacy-safe route decision suitable for UI and lifecycle surfaces."""

    request_type: str
    workflow: Workflow
    selected_tool: str
    target_agent: str
    collaboration_targets: list[str]
    human_review_triggers: list[str]
    serving_path: ServingPath
    selected_model: str
    model_selection_source: Literal["ALLOWED_MODELS"] = "ALLOWED_MODELS"
    cost_tier: Literal["economy", "standard", "premium"]
    cost_reason: str
    matched_keyword: str | None = None
    cache_eligible: bool = True
    certification_required: bool = True
    audit_action: str = "orchestrator_route"
    human_review_required: bool
    fallback_available: bool = True
    reason: str


class CertificationSummary(BaseModel):
    is_valid: bool
    confidence: float
    violations: list[str]
    redaction_count: int


class CacheSummary(BaseModel):
    eligible: bool
    hit: bool
    context_hash: str


class AuditSummary(BaseModel):
    recorded: bool
    event_id: int | str | None = None
    action: str


class A2ASummary(BaseModel):
    """Privacy-safe view of the certified route envelope."""

    trace_id: str
    source_agent: str
    target_agent: str
    selected_tool: str
    model_id: str
    certified: bool
    metadata: dict[str, Any]


class OrchestrationResult(BaseModel):
    """Visible result returned by the no-provider-call planning endpoint."""

    request_id: str
    execution_mode: ExecutionMode
    provider_call: Literal[False] = False
    plan: OrchestrationPlan
    a2a: A2ASummary
    certification: CertificationSummary
    cache: CacheSummary
    audit: AuditSummary


def build_orchestration_plan(
    request_type: str,
    payload: Mapping[str, Any],
    *,
    models: Sequence[str] | None = None,
) -> OrchestrationPlan:
    """Choose one visible route without making a provider call."""
    allowed = list(models) if models is not None else configured_models()
    if not allowed:
        raise RuntimeError("ALLOWED_MODELS is empty or unset")

    workflow = _infer_workflow(request_type, payload)
    query = _payload_prompt(payload)
    has_images = workflow == "resume_screening" and _has_images(payload)
    card = _card_for_workflow(workflow, has_images)
    if has_images:
        selected_model = _gemma_model(allowed)
        cost_route = CostRoute(
            tier="premium",
            selected_model=selected_model,
            reason="multimodal_resume_requires_gemma",
        )
        serving_path: ServingPath = "deploy_on_demand"
    else:
        eligible = _non_multimodal_models(allowed)
        cost_route = CostRouter.classify(query, allowed_models=eligible)
        serving_path = _serving_path(workflow, payload)
        selected_model = _batch_model(allowed) if serving_path == "batch" else None
        selected_model = selected_model or cost_route.selected_model

    review_required = _human_review_required(workflow, query)
    return OrchestrationPlan(
        request_type=request_type,
        workflow=workflow,
        selected_tool=card.tool_name(),
        target_agent=card.agent_name,
        collaboration_targets=list(card.collaboration_targets),
        human_review_triggers=list(card.human_review_triggers),
        serving_path=serving_path,
        selected_model=selected_model,
        cost_tier=cost_route.tier,
        cost_reason=cost_route.reason,
        matched_keyword=cost_route.matched_keyword,
        human_review_required=review_required,
        reason=(
            f"Route {workflow} through {card.tool_name()} at {serving_path} and "
            f"{cost_route.tier} tier; "
            f"human_review_required={str(review_required).lower()}."
        ),
    )


async def orchestrate(
    request_type: str,
    payload: Mapping[str, Any],
    *,
    models: Sequence[str] | None = None,
) -> OrchestrationResult:
    """Return a certified, cached, and audited orchestration decision."""
    query = _payload_prompt(payload)
    cache_context = context_hash(ORCHESTRATOR_VERSION, request_type)
    cached = _PLAN_CACHE.get(query, cache_context)
    if cached:
        plan = OrchestrationPlan.model_validate(cached)
        cache_hit = True
        _METRICS["cache_hits"] += 1
    else:
        plan = build_orchestration_plan(request_type, payload, models=models)
        _PLAN_CACHE.set(query, cache_context, plan.model_dump(mode="json"))
        cache_hit = False
    _METRICS["plans_total"] += 1
    _LAST_ROUTE.update(
        {
            "workflow": plan.workflow,
            "selected_tool": plan.selected_tool,
            "serving_path": plan.serving_path,
            "selected_model": plan.selected_model,
            "cost_tier": plan.cost_tier,
            "human_review_required": plan.human_review_required,
            "execution_mode": "planned_live" if llm_active() else "deterministic_fallback",
        }
    )

    envelope = await certified_handoff(
        source_agent="orchestrator_agent",
        target_agent=plan.target_agent,
        func=lambda _: plan.model_dump(mode="json"),
        payload={
            "request_type": request_type,
            "input_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        },
        objectives={
            "schema": OrchestrationPlan.model_json_schema(),
            "require_pii_free": True,
        },
        model_id=plan.selected_model,
        metadata={
            "selected_tool": plan.selected_tool,
            "workflow": plan.workflow,
            "serving_path": plan.serving_path,
            "cost_tier": plan.cost_tier,
            "human_review_required": plan.human_review_required,
            "provider_call": False,
        },
        persist=False,
    )
    certified = envelope.certification
    certification = _certification_summary(certified)
    if not certification.is_valid:
        _METRICS["certifications_failed"] += 1
        raise RuntimeError(
            "orchestrator output failed certification: "
            + ", ".join(certification.violations)
        )
    _METRICS["certifications_passed"] += 1

    audit_row = await record_action(
        agent="orchestrator",
        action=plan.audit_action,
        input_data={
            "request_type": request_type,
            "input_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        },
        output_data={
            "workflow": plan.workflow,
            "serving_path": plan.serving_path,
            "selected_model": plan.selected_model,
            "selected_tool": plan.selected_tool,
            "a2a_trace_id": envelope.trace_id,
            "target_agent": plan.target_agent,
            "cost_tier": plan.cost_tier,
            "cache_hit": cache_hit,
            "certified": certification.is_valid,
            "human_review_required": plan.human_review_required,
        },
        status="success",
    )
    _METRICS["audit_events_recorded"] += 1
    return OrchestrationResult(
        request_id=str(uuid4()),
        execution_mode="planned_live" if llm_active() else "deterministic_fallback",
        plan=plan,
        a2a=A2ASummary(
            trace_id=envelope.trace_id,
            source_agent=envelope.source_agent,
            target_agent=envelope.target_agent,
            selected_tool=plan.selected_tool,
            model_id=envelope.model_id or plan.selected_model,
            certified=envelope.certification.is_valid,
            metadata=dict(envelope.metadata),
        ),
        certification=certification,
        cache=CacheSummary(
            eligible=plan.cache_eligible,
            hit=cache_hit,
            context_hash=cache_context,
        ),
        audit=AuditSummary(
            recorded=True,
            event_id=audit_row.get("id"),
            action=plan.audit_action,
        ),
    )


def orchestrator_manifest() -> dict[str, Any]:
    """Return the judge-visible single-orchestrator product contract."""
    plans_total = _METRICS["plans_total"]
    return {
        "pattern": "single_orchestrator",
        "stages": [
            "route",
            "cost_select",
            "cache_check",
            "certify",
            "audit",
            "respond",
        ],
        "serving_paths": ["fast", "standard", "batch", "deploy_on_demand"],
        "model_selection": "ALLOWED_MODELS only",
        "tools": TOOLS,
        "a2a_handoff": "certified_handoff with redacted route payload",
        "controls": {
            "cost_router": "core.cost_router.CostRouter",
            "semantic_cache": "services.semantic_cache.HRSemanticCache",
            "certifier": "core.fireworks_certifier.FireworksOutputCertifier",
            "audit": "services.audit_service.record_action",
            "deterministic_fallback": True,
        },
        "visible_metrics": [
            "selected_model",
            "serving_path",
            "cost_tier",
            "cache_hit",
            "certification_status",
            "audit_event_id",
            "human_review_required",
        ],
        "runtime": {
            **_METRICS,
            "cache_hit_rate": (
                _METRICS["cache_hits"] / plans_total if plans_total else 0.0
            ),
        },
        "last_route": dict(_LAST_ROUTE),
    }


def _infer_workflow(request_type: str, payload: Mapping[str, Any]) -> Workflow:
    normalized = request_type.strip().lower()
    aliases: dict[str, Workflow] = {
        "attrition": "attrition",
        "attrition_explanation": "attrition",
        "case_triage": "triage",
        "classification": "triage",
        "complex_reasoning": "attrition",
        "onboarding": "onboarding",
        "policy": "policy_qa",
        "policy_qa": "policy_qa",
        "rag": "policy_qa",
        "resume": "resume_screening",
        "resume_analysis": "resume_screening",
        "resume_screening": "resume_screening",
        "streaming_chat": "policy_qa",
        "structured_classification": "triage",
        "triage": "triage",
    }
    if normalized in aliases:
        return aliases[normalized]

    text = _payload_prompt(payload).lower()
    if any(term in text for term in ("resume", "candidate", "job description", "skills")):
        return "resume_screening"
    if any(term in text for term in ("attrition", "retention", "promotion", "risk")):
        return "attrition"
    if any(term in text for term in ("onboard", "new hire", "training", "account")):
        return "onboarding"
    if any(term in text for term in ("policy", "benefit", "pto", "leave", "compliance")):
        return "policy_qa"
    return "triage"


def _card_for_workflow(workflow: Workflow, has_images: bool) -> A2ACard:
    if has_images:
        return GEMMA_MULTIMODAL_CARD
    aliases = {
        "attrition": "attrition_agent",
        "onboarding": "onboarding_agent",
        "policy_qa": "policy_qa_agent",
        "resume_screening": "resume_screener_agent",
        "triage": "triage_agent",
    }
    return get_card(aliases[workflow])


def _serving_path(workflow: Workflow, payload: Mapping[str, Any]) -> ServingPath:
    records = payload.get("records")
    has_batch = (
        isinstance(records, Sequence)
        and not isinstance(records, (str, bytes))
        and bool(records)
    )
    if has_batch and workflow in {"attrition", "resume_screening"}:
        return "batch"
    if workflow == "triage":
        return "fast"
    return "standard"


def _gemma_model(allowed: Sequence[str]) -> str:
    configured = os.environ.get(
        "FIREWORKS_GEMMA_MODEL", settings.fireworks_gemma_model
    ).strip()
    if configured and configured in allowed:
        return configured
    candidates = [
        model_id
        for model_id in allowed
        if all(token in model_id.lower() for token in ("gemma", "4", "26b", "a4b"))
    ]
    if not candidates:
        raise RuntimeError(
            "ALLOWED_MODELS contains no Gemma 4 26B A4B IT model for multimodal routing"
        )
    return candidates[0]


def _non_multimodal_models(allowed: Sequence[str]) -> list[str]:
    configured_gemma = os.environ.get(
        "FIREWORKS_GEMMA_MODEL", settings.fireworks_gemma_model
    ).strip()
    candidates = [model_id for model_id in allowed if model_id != configured_gemma]
    return candidates or list(allowed)


def _batch_model(allowed: Sequence[str]) -> str | None:
    configured = os.environ.get(
        "FIREWORKS_BATCH_MODEL", settings.fireworks_batch_model
    ).strip()
    return configured if configured in allowed else None


def _human_review_required(workflow: Workflow, query: str) -> bool:
    if workflow in {"attrition", "onboarding", "resume_screening"}:
        return True
    return workflow == "triage" and any(
        term in query.lower() for term in ("urgent", "harassment", "termination", "legal")
    )


def _has_images(payload: Mapping[str, Any]) -> bool:
    image_urls = payload.get("image_urls")
    return (
        isinstance(image_urls, Sequence)
        and not isinstance(image_urls, (str, bytes))
        and bool(image_urls)
    )


def _payload_prompt(payload: Mapping[str, Any]) -> str:
    for key in ("prompt", "query", "message", "input", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(dict(payload), sort_keys=True, default=str)


def _certification_summary(
    result: CertifiedResult | ValidationError,
) -> CertificationSummary:
    if isinstance(result, ValidationError):
        return CertificationSummary(
            is_valid=False,
            confidence=0.0,
            violations=["schema_validation_failed"],
            redaction_count=0,
        )
    return CertificationSummary(
        is_valid=result.is_valid,
        confidence=result.confidence,
        violations=list(result.violations),
        redaction_count=result.redaction_count,
    )
