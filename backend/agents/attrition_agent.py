"""Attrition Predictor agent wrapper.

Thin agent layer over :mod:`models.attrition_model`. Provides the standard
agent ``run`` interface (status tracking + audit logging) used by the API and
agent registry, delegating the actual ML work to the trained model.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.retention_resolver import retention_resolver
from core.memory import memory
from models.attrition_model import FEATURES, attrition_model

AGENT_NAME = "attrition_agent"


class AttritionAgent:
    """Agent that predicts employee attrition risk."""

    def __init__(self) -> None:
        """Initialise the agent against the shared trained model."""
        self._model = attrition_model

    async def run(self, features: dict[str, float]) -> dict[str, Any]:
        """Predict attrition risk and log the action.

        Args:
            features: Mapping containing the six required feature values
                (see :data:`models.attrition_model.FEATURES`). Missing values
                default to neutral midpoints.

        Returns:
            Dict with ``attrition_risk_score``, ``top_risk_factors`` and
            ``explanation``.
        """
        await memory.upsert_agent(AGENT_NAME, status="running", last_action="predicting attrition")
        # Fill any missing features with sensible neutral defaults.
        defaults = {
            "tenure_months": 24,
            "performance_score": 3.0,
            "absence_days": 5,
            "last_promotion_months": 12,
            "salary_band": 3,
            "manager_rating": 3.0,
        }
        complete = {f: float(features.get(f, defaults[f])) for f in FEATURES}
        try:
            result = await asyncio.to_thread(self._model.predict, complete)
            score = result["attrition_risk_score"]
            high = result.get("needs_review", False)

            # Agent composition: on high risk, ask the Policy Q&A engine for the
            # policies that bear on the top drivers → grounded, cited retention
            # suggestions a manager can act on. Advisory; never blocks/alters the
            # prediction. Skipped when risk is low (bounded work).
            result["retention_context"] = (
                await retention_resolver.suggest(score, result.get("top_risk_factors", []))
                if high
                else []
            )

            # Land the prediction in the Cases ledger as a RETENTION case (every
            # agent action → Cases + Audit). High-risk → "open" (a stay interview
            # to schedule); otherwise "resolved". Advisory only — never punitive.
            case = await memory.create_case(
                category="RETENTION",
                summary=f"Attrition risk {score:.0%}",
                detail=result.get("explanation", "")[:500],
                assigned_agent="hrbp",
                status="open" if high else "resolved",
            )
            result["case_id"] = case["id"]

            await memory.log_audit(
                AGENT_NAME,
                "attrition_predict",
                complete,
                {
                    "risk": score,
                    "case_id": case["id"],
                    "retention_suggestions": len(result["retention_context"]),
                },
                "success",
            )
            await memory.upsert_agent(
                AGENT_NAME,
                status="idle",
                last_action=f"risk={score:.2f}",
                increment_runs=True,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            await memory.log_audit(
                AGENT_NAME, "attrition_predict", complete, {"error": str(exc)}, "error"
            )
            await memory.upsert_agent(AGENT_NAME, status="error", last_action=str(exc))
            raise


attrition_agent = AttritionAgent()
