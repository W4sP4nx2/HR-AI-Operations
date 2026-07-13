"""Govern.ai's small, testable A2A protocol surface.

The application keeps the durable business workflow in its own contracts, but
exposes a protocol-shaped boundary for agent-to-agent calls.  The boundary uses
the A2A concepts of Agent Cards, JSON-RPC ``message/send`` and task states while
keeping HR-specific governance in the payload: redaction, policy version,
allowed actions and a mandatory human checkpoint.

This module deliberately does not claim that the two roles are separate
processes.  They are independently addressable HTTP endpoints in the same
service today; a deployment can move either endpoint to its own service later
without changing the envelope contract.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field

from core.a2a_envelope import A2AEnvelope, certified_handoff
from core.guardrails import blind_demographics


class AgentCard(BaseModel):
    """Protocol-facing card for one independently addressable role."""

    protocolVersion: str = "0.3.0"
    name: str
    description: str
    url: str
    version: str = "0.1.0"
    capabilities: dict[str, bool] = Field(default_factory=dict)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    authentication: dict[str, Any] = Field(default_factory=dict)
    governance: dict[str, Any] = Field(default_factory=dict)


class JsonRpcRequest(BaseModel):
    """Minimal JSON-RPC request accepted by the agent endpoints."""

    jsonrpc: str = "2.0"
    id: str | int
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class A2ATask(BaseModel):
    """Task lifecycle response returned by ``message/send``."""

    id: str
    status: str
    contextId: str
    agent: str
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    handoff: dict[str, Any] = Field(default_factory=dict)
    governance: dict[str, Any] = Field(default_factory=dict)


AGENT_CARDS: dict[str, AgentCard] = {
    "resume_extractor": AgentCard(
        name="resume_extractor",
        description="Extract a redacted candidate profile from synthetic or redacted resume text.",
        url="/a2a/agents/resume_extractor/rpc",
        capabilities={"streaming": False, "pushNotifications": False},
        skills=[
            {
                "id": "extract-profile",
                "name": "Extract structured profile",
                "description": "Return skills and evidence without candidate identity fields.",
            }
        ],
        authentication={"schemes": ["local-demo-or-deployment-auth"]},
        governance={
            "sensitive_data": "raw resume stays at the intake boundary",
            "final_decision": False,
            "next_agent": "policy_guard",
        },
    ),
    "policy_guard": AgentCard(
        name="policy_guard",
        description="Blind protected attributes, apply screening policy, and prepare a human-review handoff.",
        url="/a2a/agents/policy_guard/rpc",
        capabilities={"streaming": False, "pushNotifications": False},
        skills=[
            {
                "id": "govern-screening",
                "name": "Govern resume review",
                "description": "Return policy-bound evidence and advisory ranking controls.",
            }
        ],
        authentication={"schemes": ["local-demo-or-deployment-auth"]},
        governance={
            "policy_version": "hr-screening-v1",
            "human_approval_required": True,
            "forbidden_actions": ["reject_candidate", "make_hiring_decision", "override_policy"],
        },
    ),
}


def card_for(agent_name: str) -> AgentCard:
    """Return a card or raise a stable ``KeyError`` for an unknown role."""
    return AGENT_CARDS[agent_name]


def _candidate_ref(text: str) -> str:
    return "cand_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _skills(text: str) -> list[str]:
    stop = {"the", "and", "with", "for", "years", "experience", "built", "using"}
    terms = re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}", text.lower())
    return list(dict.fromkeys(term.strip(".-") for term in terms if term not in stop))[:24]


def _extract_profile(text: str) -> dict[str, Any]:
    """Create a deliberately identity-free extraction artifact."""
    blinded = blind_demographics(text)
    # The protocol boundary is stricter than the resume scorer: email and phone
    # are removed before evidence is certified or handed to the next role.
    safe_lines = [
        re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email]", line)
        for line in blinded.splitlines()
    ]
    safe_lines = [re.sub(r"\b(?:\+?\d[\d ()-]{7,}\d)\b", "[phone]", line) for line in safe_lines]
    return {
        "candidate_ref": _candidate_ref(text),
        "skills": _skills("\n".join(safe_lines)),
        "evidence": [line.strip() for line in safe_lines if line.strip()][:8],
        "source_kind": "synthetic_or_redacted_resume",
    }


def _guard_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Apply the non-negotiable HR policy controls to a profile."""
    safe = dict(profile)
    safe.pop("name", None)
    safe.pop("email", None)
    safe.pop("phone", None)
    safe["policy_version"] = "hr-screening-v1"
    safe["allowed_actions"] = ["rank_for_review", "explain_evidence", "flag_conflict"]
    safe["forbidden_actions"] = ["reject_candidate", "make_hiring_decision", "override_policy"]
    safe["human_approval_required"] = True
    safe["needs_review"] = True
    return safe


async def execute_agent_message(agent_name: str, params: dict[str, Any]) -> tuple[A2ATask, A2AEnvelope]:
    """Execute one protocol message and certify its artifact."""
    if agent_name == "resume_extractor":
        message = params.get("message") or {}
        text = str(message.get("text") or params.get("text") or "").strip()
        if not text:
            raise ValueError("resume_extractor requires message.text")
        artifact = _extract_profile(text)
        objectives = {
            "schema": {
                "type": "object",
                "properties": {
                    "candidate_ref": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "source_kind": {"type": "string"},
                },
                "required": ["candidate_ref", "skills", "evidence", "source_kind"],
                "additionalProperties": False,
            },
            "require_pii_free": True,
        }
        envelope = await certified_handoff(
            source_agent="resume_extractor",
            target_agent="policy_guard",
            func=lambda _payload: artifact,
            payload={"source_kind": artifact["source_kind"]},
            objectives=objectives,
            metadata={"protocol": "a2a", "next_agent": "policy_guard"},
            persist=False,
        )
        status = "completed" if envelope.certification.is_valid else "failed"
        task = A2ATask(
            id=envelope.trace_id,
            status=status,
            contextId=envelope.trace_id,
            agent=agent_name,
            artifacts=[{"name": "candidate-profile", "data": envelope.payload}],
            handoff={"target_agent": "policy_guard", "trace_id": envelope.trace_id},
            governance={"raw_resume_forwarded": False},
        )
        return task, envelope

    if agent_name == "policy_guard":
        profile = params.get("profile")
        if not isinstance(profile, dict):
            raise ValueError("policy_guard requires params.profile")
        artifact = _guard_profile(profile)
        objectives = {
            "schema": {
                "type": "object",
                "properties": {
                    "candidate_ref": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "source_kind": {"type": "string"},
                    "policy_version": {"type": "string"},
                    "allowed_actions": {"type": "array", "items": {"type": "string"}},
                    "forbidden_actions": {"type": "array", "items": {"type": "string"}},
                    "human_approval_required": {"type": "boolean"},
                    "needs_review": {"type": "boolean"},
                },
                "required": [
                    "candidate_ref",
                    "skills",
                    "evidence",
                    "source_kind",
                    "policy_version",
                    "allowed_actions",
                    "forbidden_actions",
                    "human_approval_required",
                    "needs_review",
                ],
                "additionalProperties": False,
            },
            "require_pii_free": True,
        }
        envelope = await certified_handoff(
            source_agent="policy_guard",
            target_agent="human_reviewer",
            func=lambda _payload: artifact,
            payload={"candidate_ref": str(profile.get("candidate_ref", "unknown"))},
            objectives=objectives,
            metadata={"protocol": "a2a", "policy_version": "hr-screening-v1"},
            persist=False,
        )
        status = "input-required" if envelope.certification.is_valid else "failed"
        task = A2ATask(
            id=envelope.trace_id,
            status=status,
            contextId=envelope.trace_id,
            agent=agent_name,
            artifacts=[{"name": "governed-review", "data": envelope.payload}],
            handoff={"target_agent": "human_reviewer", "trace_id": envelope.trace_id},
            governance={
                "policy_version": "hr-screening-v1",
                "human_approval_required": True,
                "decision_authority": "human_reviewer",
            },
        )
        return task, envelope

    raise KeyError(agent_name)
