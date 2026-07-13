"""Strict schemas for governed interactive chat."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatResponse(BaseModel):
    """Structured chat response enforced before the UI receives an answer."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(
        description="Direct answer to the user's HR question.",
        min_length=1,
        max_length=500,
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the grounded answer.",
    )
    needs_human_review: bool = Field(
        description="True for sensitive or ambiguous HR actions.",
    )
    source_policy_ids: list[str] = Field(
        default_factory=list,
        description="Policy or document identifiers cited by the response.",
        max_length=8,
    )
    tone: Literal["professional", "empathetic", "neutral"] = Field(
        default="professional",
        description="Response tone selected for the UI.",
    )


def chat_response_objectives(*, min_confidence: float = 0.7) -> dict[str, Any]:
    """Certification objectives shared by chat wrappers and tests."""
    return {
        "schema": ChatResponse.model_json_schema(),
        "require_pii_free": True,
        "min_confidence": min_confidence,
        "confidence_field": "confidence",
        "required_fields": [
            "answer",
            "confidence",
            "needs_human_review",
            "source_policy_ids",
            "tone",
        ],
    }


def normalize_chat_result(result: dict[str, Any], *, query: str = "") -> ChatResponse:
    """Convert the existing chat agent dict into the strict chat schema."""
    answer = _clip_answer(str(result.get("reply") or "I could not produce a safe answer."))
    mode = str(result.get("mode") or "degraded")
    tool_calls = result.get("tool_calls") if isinstance(result.get("tool_calls"), list) else []
    citations = result.get("citations") if isinstance(result.get("citations"), list) else []
    source_policy_ids = _source_policy_ids(citations, tool_calls)
    sensitive = _needs_human_review(query, answer, tool_calls)
    return ChatResponse(
        answer=answer,
        confidence=_confidence_for_mode(mode, source_policy_ids, sensitive),
        needs_human_review=sensitive,
        source_policy_ids=source_policy_ids,
        tone="empathetic" if sensitive else "professional",
    )


def _clip_answer(answer: str) -> str:
    compact = " ".join(answer.split()).strip()
    if len(compact) <= 500:
        return compact or "I could not produce a safe answer."
    clipped = compact[:497].rstrip()
    return f"{clipped}..."


def _source_policy_ids(citations: list[Any], tool_calls: list[Any]) -> list[str]:
    ids: list[str] = []
    for citation in citations:
        if isinstance(citation, dict) and citation.get("doc_id"):
            ids.append(str(citation["doc_id"]))
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        result = call.get("result")
        if not isinstance(result, dict):
            continue
        for excerpt in result.get("excerpts", []) or []:
            if isinstance(excerpt, dict) and excerpt.get("doc_id"):
                ids.append(str(excerpt["doc_id"]))
    return list(dict.fromkeys(ids))[:8]


def _needs_human_review(query: str, answer: str, tool_calls: list[Any]) -> bool:
    text = f"{query} {answer}".lower()
    sensitive_terms = (
        "harassment",
        "discrimination",
        "retaliation",
        "termination",
        "legal",
        "complaint",
        "urgent",
        "emergency",
        "attrition",
        "risk",
    )
    if any(term in text for term in sensitive_terms):
        return True
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        tool = str(call.get("tool") or "")
        if tool in {"triage_ticket", "check_attrition"}:
            return True
        result = call.get("result")
        if isinstance(result, dict) and result.get("category") in {"URGENT", "COMPLIANCE"}:
            return True
    return bool(re.search(r"\bcase-[a-f0-9]+\b", text, re.IGNORECASE))


def _confidence_for_mode(mode: str, source_policy_ids: list[str], sensitive: bool) -> float:
    if mode == "full" and source_policy_ids:
        return 0.86
    if mode == "full":
        return 0.78 if not sensitive else 0.72
    if mode == "degraded" and source_policy_ids:
        return 0.74
    if mode == "degraded":
        return 0.71 if not sensitive else 0.7
    return 0.0
