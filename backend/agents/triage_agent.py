"""Triage agent — type-safe classification via Pydantic AI, with keyword fallback.

Classifies incoming HR tickets into one of:
    [BENEFITS, POLICY, ONBOARDING, PERFORMANCE, COMPLIANCE, URGENT]

Behaviour:
    * URGENT tickets are routed to a human immediately (case left open,
      assigned to a human, WebSocket alert emitted).
    * POLICY tickets are auto-resolved using the RAG pipeline.
    * All tickets create/update a case via the cases store.

Classification uses a **Pydantic AI** agent with a ``Literal``-typed result
(``TriageDecision``), so the model is schema-constrained — it cannot return an
arbitrary string, and the validated ``category`` / ``confidence`` / ``rationale``
flow straight into the decision dossier. When no live key is available (the
zero-secret default) a transparent keyword classifier is used, so triage always
functions deterministically.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from agents.policy_resolver import policy_resolver
from agents.prompts import TRIAGE
from core.genai_lifecycle import (
    controlled_parameters,
    policy_for,
    transform_fuzzy_input,
)
from core.memory import memory
from models.naive_baselines import TRIAGE_KEYWORDS, triage_keyword_baseline

AGENT_NAME = "triage_agent"

CATEGORIES = ["BENEFITS", "POLICY", "ONBOARDING", "PERFORMANCE", "COMPLIANCE", "URGENT"]


class TriageDecision(BaseModel):
    """Schema-constrained classifier output (the model can't return arbitrary text)."""

    category: Literal["BENEFITS", "POLICY", "ONBOARDING", "PERFORMANCE", "COMPLIANCE", "URGENT"]
    priority: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


Broadcaster = Callable[[dict[str, Any]], Awaitable[None]]

# What a human should do with each category — the "recommended action" line of
# the escalation dossier (so a case isn't just raw angry text handed to a human).
_RECOMMENDED_ACTION: dict[str, str] = {
    "URGENT": "Escalate to a human immediately; do not auto-resolve. Acknowledge within SLA.",
    "POLICY": "Auto-answered from policy documents — verify the cited source before closing.",
    "BENEFITS": "Route to the Benefits queue; confirm eligibility and enrollment window.",
    "ONBOARDING": "Route to the Onboarding workflow; check accounts and training assignment.",
    "PERFORMANCE": "Route to the People Partner; handle with documented, fair process.",
    "COMPLIANCE": "Flag for Compliance review; preserve records and restrict access.",
}

_POLICY_RESOLUTION_HANDOFF_OBJECTIVES: dict[str, Any] = {
    "schema": {
        "type": "object",
        "properties": {
            "resolution": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "source_documents": {"type": "array", "items": {"type": "object"}},
                    "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "needs_review": {"type": "boolean"},
                },
                "required": ["answer", "source_documents", "confidence_score", "needs_review"],
                "additionalProperties": True,
            },
            "trace": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["resolution", "trace"],
        "additionalProperties": True,
    },
    "require_pii_free": True,
}

_KEYWORDS = TRIAGE_KEYWORDS
_PRIORITY = {
    "URGENT": "critical",
    "COMPLIANCE": "high",
    "PERFORMANCE": "high",
    "ONBOARDING": "medium",
    "BENEFITS": "medium",
    "POLICY": "low",
}


class TriageAgent:
    """Classifies and routes incoming HR tickets."""

    def __init__(self, broadcaster: Broadcaster | None = None) -> None:
        """Initialise the triage agent.

        Args:
            broadcaster: Optional async WebSocket broadcaster.
        """
        self._broadcast = broadcaster

    def set_broadcaster(self, broadcaster: Broadcaster) -> None:
        """Attach a WebSocket broadcaster after construction."""
        self._broadcast = broadcaster

    async def _emit(self, event: dict[str, Any]) -> None:
        """Emit a WebSocket event if a broadcaster is attached."""
        if self._broadcast is not None:
            await self._broadcast(event)

    # -- classification ---------------------------------------------------
    def _keyword_classify(self, text: str) -> str:
        """Classify a ticket by keyword scoring.

        Args:
            text: The ticket text.

        Returns:
            One of :data:`CATEGORIES`.
        """
        return triage_keyword_baseline.predict(text).category

    def _keyword_reason(self, text: str, category: str) -> str:
        """Explain *why* a ticket got its category — the auditable rationale.

        Returns a plain-English sentence a compliance reviewer can verify,
        rather than leaving the decision opaque ("why was 'sDSD' POLICY?").
        """
        return triage_keyword_baseline.reason(text, category)

    async def _llm_classify(self, text: str) -> TriageDecision | None:
        """Classify with a type-safe Pydantic AI agent; ``None`` to fall back.

        The result is validated against :class:`TriageDecision`, so the model is
        physically blocked from returning a malformed/arbitrary category. The
        retry loop is capped (``retries=1``) and the input is length-bounded so a
        long document can't multiply token cost; a wall-clock timeout guards the
        call. Runs in-request (await), keeping the BYOK key on the request frame.
        """
        from core.llm_factory import get_request_scoped_model

        model = get_request_scoped_model(role="triage")
        if model is None:  # no live key / gated off → deterministic keyword path
            return None
        try:
            from pydantic_ai import Agent
        except Exception:  # noqa: BLE001
            return None

        agent: Agent[None, TriageDecision] = Agent(
            model,
            output_type=TriageDecision,
            system_prompt=TRIAGE.text,
            retries=policy_for("triage").retries,
        )
        try:
            prepared = transform_fuzzy_input(text, role="triage")
            result = await asyncio.wait_for(
                agent.run(
                    prepared.text,
                    model_settings=controlled_parameters("triage"),
                ),
                timeout=policy_for("triage").timeout_seconds,
            )
            return result.output
        except Exception:  # noqa: BLE001 — any failure → keyword fallback
            return None

    # -- public API -------------------------------------------------------
    async def run(self, ticket_text: str, summary: str | None = None) -> dict[str, Any]:
        """Triage a single HR ticket end to end.

        Args:
            ticket_text: The full ticket text.
            summary: Optional short summary; derived from text if omitted.

        Returns:
            Dict with the created ``case``, the chosen ``category`` and any
            ``resolution`` produced by auto-resolution.
        """
        await memory.upsert_agent(AGENT_NAME, status="running", last_action="triaging ticket")
        summary = summary or (ticket_text[:120] + ("…" if len(ticket_text) > 120 else ""))
        try:
            fast_route = triage_keyword_baseline.confident_predict(ticket_text)
            decision = None if fast_route is not None else await self._llm_classify(ticket_text)
            if fast_route is not None:
                category = fast_route.category
                method = "keyword_fast_path"
                llm_rationale = None
                llm_confidence = None
            elif decision is not None:
                category = decision.category
                method = "llm"
                llm_rationale: str | None = decision.rationale
                llm_confidence: float | None = decision.confidence
            else:
                category = self._keyword_classify(ticket_text)
                method = "keyword"
                llm_rationale = None
                llm_confidence = None
            baseline = triage_keyword_baseline.predict(ticket_text)
            priority = _PRIORITY[category]
            confidence = (
                float(llm_confidence)
                if llm_confidence is not None
                else (
                    0.3
                    if baseline.defaulted
                    else min(0.95, 0.55 + 0.1 * len(baseline.matched_terms))
                )
            )

            resolution: dict[str, Any] | None = None
            policy_trace: list[dict[str, Any]] = []
            status = "open"
            assigned = AGENT_NAME

            if category == "URGENT":
                # Route to a human immediately.
                assigned = "human"
                status = "escalated"
            elif category == "POLICY":
                # Auto-resolve through the bounded agentic loop (retrieve → grade
                # → reformulate-and-retry on low confidence → accept). Routing is
                # unchanged: POLICY still auto-resolves.
                from core.a2a_envelope import certified_handoff

                envelope = await certified_handoff(
                    source_agent=AGENT_NAME,
                    target_agent="policy_qa_agent",
                    func=lambda payload: policy_resolver.resolve(str(payload["ticket_text"])),
                    payload={"ticket_text": ticket_text},
                    objectives=_POLICY_RESOLUTION_HANDOFF_OBJECTIVES,
                    metadata={
                        "source_category": category,
                        "source_priority": priority,
                        "expected_target_category": "POLICY",
                    },
                )
                resolved = (
                    envelope.payload
                    if envelope.certification.is_valid
                    else {
                        "resolution": {
                            "answer": (
                                "Policy resolution did not pass certification; "
                                "route this ticket for manual review."
                            ),
                            "source_documents": [],
                            "confidence_score": 0.0,
                            "needs_review": True,
                            "mode": "certification_failed",
                        },
                        "trace": [
                            {
                                "step": "certification",
                                "violations": envelope.certification.violations,
                            }
                        ],
                    }
                )
                resolution = resolved["resolution"]
                policy_trace = resolved["trace"]
                status = "resolved"
                assigned = "policy_qa_agent"

            # Decision dossier: the *why* behind the routing so an escalation
            # carries context (not just the raw ticket) and the audit log reads
            # like a compliance record, not developer JSON.
            rationale = (
                (llm_rationale or "Classified by the LLM classifier.")
                if method == "llm"
                else self._keyword_reason(ticket_text, category)
            )
            dossier: dict[str, Any] = {
                "rationale": rationale,
                "method": method,
                "priority": priority,
                "confidence": round(confidence, 2),
                "recommended_action": _RECOMMENDED_ACTION.get(
                    category, "Route to the assigned queue."
                ),
            }
            if method == "llm" and llm_confidence is not None:
                dossier["classifier_confidence"] = round(llm_confidence, 2)
            if category == "POLICY" and resolution:
                dossier["confidence"] = resolution.get("confidence_score")
                dossier["sources"] = resolution.get("source_documents", [])[:3]
                dossier["mode"] = resolution.get("mode")
                # The agentic loop's steps — surfaced to the UI execution trace.
                dossier["trace"] = policy_trace
                dossier["attempts"] = sum(1 for s in policy_trace if s.get("step") == "retrieve")

            # Persist the synchronously-computed recommendation as first-class
            # case fields so the Cases panel renders it without a re-query (and
            # without a background task / race / BYOK leak). ``ai_mode`` keeps the
            # UI honest about whether an LLM or a deterministic excerpt answered.
            ai_recommendation = ai_confidence = ai_mode = None
            if category == "POLICY" and resolution:
                ai_recommendation = resolution.get("answer")
                ai_confidence = resolution.get("confidence_score")
                ai_mode = resolution.get("mode")

            case = await memory.create_case(
                category=category,
                summary=summary,
                detail=ticket_text,
                assigned_agent=assigned,
                status=status,
                ai_recommendation=ai_recommendation,
                ai_confidence=ai_confidence,
                ai_mode=ai_mode,
            )

            await memory.log_audit(
                AGENT_NAME,
                "triage",
                {"ticket": summary},
                {
                    "category": category,
                    "priority": priority,
                    "confidence": round(confidence, 2),
                    "status": status,
                    "case_id": case["id"],
                    "rationale": rationale,
                    "recommended_action": dossier["recommended_action"],
                    # Boundary-level decision context (not per-node flooding): how
                    # many retrieval attempts the agentic loop took to resolve.
                    **(
                        {"retrieval_attempts": dossier["attempts"]} if "attempts" in dossier else {}
                    ),
                    # The type-safe classifier's self-reported confidence (LLM path
                    # only) — surfaced as a gauge in the case drawer's trace.
                    **(
                        {"classifier_confidence": dossier["classifier_confidence"]}
                        if "classifier_confidence" in dossier
                        else {}
                    ),
                },
                "success",
            )
            await memory.upsert_agent(
                AGENT_NAME,
                status="idle",
                last_action=f"triaged → {category}",
                increment_runs=True,
            )

            # Emit live feed events for the frontend.
            await self._emit({"type": "new_case", "case": case})
            if category == "URGENT":
                await self._emit({"type": "escalation", "case": case, "agent": AGENT_NAME})

            return {
                "case": case,
                "category": category,
                "priority": priority,
                "confidence": round(confidence, 2),
                "resolution": resolution,
                "dossier": dossier,
            }
        except Exception as exc:  # noqa: BLE001
            await memory.log_audit(
                AGENT_NAME, "triage", {"ticket": summary}, {"error": str(exc)}, "error"
            )
            await memory.upsert_agent(AGENT_NAME, status="error", last_action=str(exc))
            raise


triage_agent = TriageAgent()
