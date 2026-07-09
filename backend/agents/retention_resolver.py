"""Attrition × Policy composition — grounded retention suggestions.

When the Attrition Predictor flags a **high-risk** employee, this resolver
**composes** two existing agents: it maps the model's top risk *factors* to the
relevant HR policy area and queries the **Policy Q&A (RAG) engine** for grounded,
cited context a manager can actually act on. It turns "risk 78%, driver:
last_promotion_months" into "here's the career-development policy that applies."

Why this is a plain bounded composition, not a LangGraph state machine:

  * There's no stateful branching or self-correction here — it's a deterministic
    fan-out (top factors → policy lookups). A state graph would be ceremony; the
    right-sized tool is a bounded async loop.

Guarantees (same spirit as the other resolvers):

  * **Bounded** — only the top ``MAX_FACTORS`` drivers are looked up, each RAG
    call wrapped in a wall-clock timeout.
  * **Advisory & non-blocking** — any failure yields an empty list; a retention
    lookup must never block or alter the prediction. It is decision *support*,
    never an automated adverse action.
  * **Honest** — suggestions are deterministic (factor→action), and the policy
    text is grounded RAG: if no policy matches (``mode == "no_context"``) it says
    so rather than inventing one.
"""

from __future__ import annotations

import asyncio
from typing import Any

# Each driver → (the policy question to ask RAG, the manager-facing angle).
# Deterministic and auditable; no driver maps to a protected attribute.
_FACTOR_POLICY: dict[str, tuple[str, str]] = {
    "last_promotion_months": (
        "career development and promotion policy",
        "Long time since last promotion — review career-development and promotion paths.",
    ),
    "salary_band": (
        "compensation and benefits policy",
        "Compensation band is a driver — review pay/benefits and equity adjustments.",
    ),
    "absence_days": (
        "leave and wellbeing policy",
        "Elevated absence — check leave entitlements and wellbeing support.",
    ),
    "manager_rating": (
        "manager feedback and performance review policy",
        "Manager-relationship signal — review 1:1 cadence and management support.",
    ),
    "disengagement_index": (
        "career development manager support retention policy",
        "Slow-burn disengagement signal — pair career-path review with manager support.",
    ),
    "tenure_months": (
        "onboarding and employee engagement policy",
        "Short tenure — strengthen onboarding and early-engagement touchpoints.",
    ),
    "performance_score": (
        "performance review and development policy",
        "Performance signal — agree a concrete development plan and support.",
    ),
}

_POLICY_HANDOFF_OBJECTIVES: dict[str, Any] = {
    "schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "mode": {"type": "string"},
            "source_documents": {"type": "array", "items": {"type": "object"}},
            "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
            "needs_review": {"type": "boolean"},
            "prompt_version": {"type": "string"},
        },
        "required": ["answer", "source_documents", "confidence_score", "needs_review"],
        "additionalProperties": True,
    },
    "require_pii_free": True,
}


class RetentionResolver:
    """Maps attrition drivers to grounded, policy-cited retention suggestions."""

    MAX_FACTORS = 2  # only look up the top couple of drivers (bounded fan-out)
    TIMEOUT_S = 15.0  # wall-clock guard per policy lookup

    async def suggest(
        self, score: float, top_risk_factors: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return grounded retention suggestions for the top drivers.

        Args:
            score: The attrition risk score (for context only).
            top_risk_factors: The model's ranked factors (``{factor, contribution}``).

        Returns:
            A list of ``{factor, suggestion, policy_query, policy_answer,
            grounded, sources}`` dicts — possibly empty. Never raises.
        """
        from services import rag

        out: list[dict[str, Any]] = []
        for f in top_risk_factors[: self.MAX_FACTORS]:
            name = f.get("factor")
            mapping = _FACTOR_POLICY.get(name)
            if not mapping:
                continue
            policy_query, suggestion = mapping
            try:
                from core.a2a_envelope import certified_handoff

                envelope = await asyncio.wait_for(
                    certified_handoff(
                        source_agent="policy_qa_agent",
                        target_agent="retention_resolver",
                        func=lambda payload: rag.query(str(payload["query"])),
                        payload={"query": policy_query},
                        objectives=_POLICY_HANDOFF_OBJECTIVES,
                    ),
                    timeout=self.TIMEOUT_S,
                )
            except Exception:  # noqa: BLE001 — advisory: a lookup must never block prediction
                continue
            if not envelope.certification.is_valid:
                continue
            res = envelope.payload
            grounded = bool(res) and res.get("mode") != "no_context"
            out.append(
                {
                    "factor": name,
                    "suggestion": suggestion,
                    "policy_query": policy_query,
                    "policy_answer": (
                        res.get("answer")
                        if grounded
                        else "No specific policy located — handle via a manual retention review."
                    ),
                    "grounded": grounded,
                    "sources": [s.get("doc_id") for s in res.get("source_documents", [])[:3]],
                }
            )
        return out


retention_resolver = RetentionResolver()
