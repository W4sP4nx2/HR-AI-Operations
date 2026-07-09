"""Controlled inference and lifecycle metadata for the GenAI system."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from agents.prompts import (
    ATTRITION_EXPLANATION,
    CHAT,
    POLICY_RAG,
    PROMPTS,
    SKILL_VALIDATOR,
    TRIAGE,
)
from core.guardrails import detect_prompt_injection
from core.safety import prompt_hash


@dataclass(frozen=True)
class InferencePolicy:
    role: str
    prompt_id: str
    max_input_chars: int
    max_tokens: int
    temperature_min: float
    temperature_max: float
    timeout_seconds: float
    retries: int
    output_contract: str
    top_k: int | None
    top_p: float | None


POLICIES: dict[str, InferencePolicy] = {
    "chat": InferencePolicy(
        "chat", CHAT.prompt_id, 12_000, 800, 0.0, 0.3, 30.0, 1, "text", 50, None
    ),
    "triage": InferencePolicy(
        "triage",
        TRIAGE.prompt_id,
        4_000,
        250,
        0.0,
        0.0,
        20.0,
        1,
        "TriageDecision",
        1,
        None,
    ),
    "skill_validator": InferencePolicy(
        "skill_validator",
        SKILL_VALIDATOR.prompt_id,
        4_000,
        500,
        0.0,
        0.0,
        25.0,
        1,
        "SkillAudit",
        1,
        None,
    ),
    "policy_rag": InferencePolicy(
        "policy_rag",
        POLICY_RAG.prompt_id,
        16_000,
        600,
        0.0,
        0.0,
        30.0,
        1,
        "text",
        1,
        None,
    ),
    "attrition_explanation": InferencePolicy(
        "attrition_explanation",
        ATTRITION_EXPLANATION.prompt_id,
        2_000,
        250,
        0.0,
        0.1,
        20.0,
        0,
        "text",
        20,
        None,
    ),
}
DEFAULT_POLICY = InferencePolicy(
    "default", CHAT.prompt_id, 8_000, 600, 0.0, 0.2, 30.0, 0, "text", 40, None
)


@dataclass(frozen=True)
class InputTransformation:
    text: str
    original_chars: int
    output_chars: int
    unicode_normalized: bool
    controls_removed: bool
    whitespace_normalized: bool
    truncated: bool
    injection_signal: bool


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")
_EXCESS_NEWLINES = re.compile(r"\n{3,}")


def policy_for(role: str) -> InferencePolicy:
    """Return the reviewed inference envelope for a role."""
    return POLICIES.get(role, DEFAULT_POLICY)


def transform_fuzzy_input(text: str, *, role: str = "default") -> InputTransformation:
    """Normalize fuzzy text while preserving meaning and recording each change."""
    policy = policy_for(role)
    original = str(text)
    normalized = unicodedata.normalize("NFKC", original)
    without_controls = _CONTROL_CHARS.sub("", normalized)
    whitespace = _EXCESS_NEWLINES.sub(
        "\n\n",
        _HORIZONTAL_SPACE.sub(" ", without_controls).strip(),
    )
    transformed = whitespace[: policy.max_input_chars]
    result = InputTransformation(
        text=transformed,
        original_chars=len(original),
        output_chars=len(transformed),
        unicode_normalized=normalized != original,
        controls_removed=without_controls != normalized,
        whitespace_normalized=whitespace != without_controls,
        truncated=len(whitespace) > policy.max_input_chars,
        injection_signal=detect_prompt_injection(transformed),
    )
    from core.observability import record_inference_input

    record_inference_input(
        role,
        truncated=result.truncated,
        injection_signal=result.injection_signal,
    )
    return result


def controlled_parameters(
    role: str,
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, int | float]:
    """Clamp caller preferences to the reviewed role-specific envelope."""
    policy = policy_for(role)
    tokens = min(max(1, max_tokens or policy.max_tokens), policy.max_tokens)
    requested_temperature = policy.temperature_min if temperature is None else float(temperature)
    bounded_temperature = min(
        max(requested_temperature, policy.temperature_min),
        policy.temperature_max,
    )
    parameters: dict[str, int | float] = {
        "max_tokens": tokens,
        "temperature": bounded_temperature,
    }
    if policy.top_k is not None:
        parameters["top_k"] = min(max(policy.top_k, 0), 100)
    if policy.top_p is not None:
        parameters["top_p"] = min(max(policy.top_p, 0.0), 1.0)
    return parameters


def score_output(
    *,
    schema_valid: bool,
    grounded: bool,
    safety_passed: bool,
    confidence: float | None,
) -> dict[str, Any]:
    """Return a transparent quality score; never hide failed hard gates."""
    confidence_score = min(max(float(confidence or 0.0), 0.0), 1.0)
    hard_gate = schema_valid and safety_passed
    score = (
        0.35 * float(schema_valid)
        + 0.30 * float(grounded)
        + 0.25 * float(safety_passed)
        + 0.10 * confidence_score
    )
    return {
        "score": round(score, 4),
        "schema_valid": schema_valid,
        "grounded": grounded,
        "safety_passed": safety_passed,
        "confidence": confidence_score,
        "accepted": hard_gate and grounded,
        "needs_review": not (hard_gate and grounded),
    }


def lifecycle_manifest() -> dict[str, Any]:
    """Describe what is implemented at each GenAI lifecycle stage."""
    prompt_manifest = {
        prompt_id: {
            "version": spec.version,
            "hash": prompt_hash(spec.text),
        }
        for prompt_id, spec in PROMPTS.items()
    }
    return {
        "building_blocks": {
            "inputs": "typed contracts plus recorded fuzzy-input transformations",
            "inference": "provider factory, allow-listed models, bounded role policies",
            "retrieval": "policy chunks, embeddings, pgvector/local backends, citations",
            "outputs": "Pydantic schemas, hard safety gates, human-review flags",
            "labels": "triage overrides and append-only manager feedback",
        },
        "stages": [
            {
                "stage": "inference",
                "status": "implemented",
                "evidence": ["prompt registry", "controlled parameters", "audit log"],
            },
            {
                "stage": "pretraining",
                "status": "external",
                "evidence": ["base models are provider/harness supplied"],
            },
            {
                "stage": "post_training",
                "status": "not_executed",
                "evidence": ["labels are collected but never auto-fed into training"],
            },
            {
                "stage": "data_labeling",
                "status": "implemented",
                "evidence": ["triage_override audit rows", "agent_feedback ledger"],
            },
        ],
        "prompts": prompt_manifest,
        "policies": {role: asdict(policy) for role, policy in POLICIES.items()},
    }
