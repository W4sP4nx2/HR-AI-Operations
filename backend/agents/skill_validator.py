"""Schema-constrained skill validation — closes the embedding negation blind spot.

Vector similarity + keyword matching are blind to grammatical negation: "abandoned
FastAPI" and "never built LangGraph" still surface those tokens, so a candidate
gets credit for skills they explicitly disclaim. This pass runs a **type-safe
Pydantic AI** gate over the *matched* skills and grades each one's evidence, so
the screener can drop the false matches before scoring.

It is **opt-in and bounded**, with the same rails as the triage classifier:
  * runs in-request via the request-scoped provider factory (BYOK-safe; no
    detached task — see ``tests/test_no_detached_tasks.py``),
  * input length-capped + ``retries=1`` + wall-clock timeout (token-cost guard),
  * returns ``None`` when no live key / pydantic-ai is unavailable, so the caller
    falls back to keyword behavior — and **marks that fallback explicitly** so the
    UI never presents an unvalidated score as validated.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel

from agents.prompts import SKILL_VALIDATOR
from core.genai_lifecycle import (
    controlled_parameters,
    policy_for,
    transform_fuzzy_input,
)


class SkillEvidence(BaseModel):
    """One skill's evidence status, judged from context (not token presence)."""

    skill: str
    status: Literal["demonstrated", "aspirational", "negated", "absent"]


class SkillAudit(BaseModel):
    """The schema-constrained result: a status per evaluated skill."""

    items: list[SkillEvidence]


class SkillValidator:
    """Grades each matched skill's evidence via a type-safe Pydantic AI pass."""

    async def validate(self, skills: list[str], resume: str) -> SkillAudit | None:
        """Return a :class:`SkillAudit` for ``skills``, or ``None`` to fall back.

        Never raises: timeout / unavailable key / any error → ``None`` so scoring
        is never blocked by the (advisory) validation pass.
        """
        if not skills:
            return SkillAudit(items=[])
        from core.llm_factory import get_request_scoped_model

        model = get_request_scoped_model(role="skill_validator")
        if model is None:  # no live key / gated off → keyword fallback
            return None
        try:
            from pydantic_ai import Agent
        except Exception:  # noqa: BLE001
            return None

        agent: Agent[None, SkillAudit] = Agent(
            model,
            output_type=SkillAudit,
            system_prompt=SKILL_VALIDATOR.text,
            retries=policy_for("skill_validator").retries,
        )
        prepared = transform_fuzzy_input(resume, role="skill_validator")
        prompt = f"Skills to verify: {', '.join(skills)}\n\nResume:\n{prepared.text}"
        try:
            result = await asyncio.wait_for(
                agent.run(
                    prompt,
                    model_settings=controlled_parameters("skill_validator"),
                ),
                timeout=policy_for("skill_validator").timeout_seconds,
            )
            return result.output
        except Exception:  # noqa: BLE001 — any failure → keyword fallback
            return None

    @staticmethod
    def discount(audit: SkillAudit) -> set[str]:
        """Skills to drop from the matched set: negated or merely aspirational."""
        return {e.skill.lower() for e in audit.items if e.status in ("negated", "aspirational")}


def apply_audit(result: dict[str, Any], audit: SkillAudit) -> dict[str, Any]:
    """Re-score ``result`` with negated/aspirational skills removed from the match.

    Recomputes the blended score on the *demonstrated* skills only and records the
    dropped ones in ``unverified_skills``. Sets ``skill_audit_mode='validated'``.
    Requires the private ``_semantic`` / ``_total`` carried by ``_embedding_score``.
    """
    drop = SkillValidator.discount(audit)
    original = list(result.get("matched_skills", []))
    demonstrated = [s for s in original if s.lower() not in drop]
    dropped = [s for s in original if s.lower() in drop]

    semantic = float(result.get("_semantic", 0.0))
    total = int(result.get("_total", 0))
    new_ratio = len(demonstrated) / total if total else 0.0
    new_score = int(100 * (0.6 * semantic + 0.4 * new_ratio) + 0.5)

    result["matched_skills"] = demonstrated
    result["unverified_skills"] = dropped
    result["score"] = new_score
    result["recommendation"] = "hire" if new_score >= 65 else "no-hire"
    result["skill_audit_mode"] = "validated"
    if dropped:
        result["needs_review"] = True
        result["reasoning"] += (
            f" Skill audit: {len(dropped)} keyword match(es) discounted as "
            f"unverified context ({', '.join(dropped)}) — score adjusted down."
        )
    return result


skill_validator = SkillValidator()
