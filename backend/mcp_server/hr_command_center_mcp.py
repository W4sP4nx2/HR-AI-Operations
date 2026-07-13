"""Read-only MCP surface for safe HR decision support.

The MCP adapter intentionally exposes a smaller surface than the FastAPI app:

* agent contracts and guardrails,
* deterministic ticket-triage previews, and
* policy guidance with explicit consent before configured external inference.

Resume screening, attrition records, case mutation, policy ingestion, and human
approval actions remain behind the product's authenticated UI/API boundaries.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from agents.contracts import AGENT_SPECS
from agents.policy_qa_agent import policy_qa_agent
from core.config import settings
from core.guardrails import REFUSAL_MESSAGE, detect_prompt_injection
from core.runtime_key import llm_active
from models.naive_baselines import triage_keyword_baseline
from services.input_shield import sanitize_text

CHARACTER_LIMIT = 25_000

mcp = FastMCP(
    "hr_command_center_mcp",
    instructions=(
        "Use these tools for read-only HR decision support. Never treat a triage preview "
        "or policy answer as authorization for an employment action. Sensitive workflows "
        "remain in the authenticated HR Command Center with human approval and audit."
    ),
)


class ResponseFormat(str, Enum):
    """Supported response representations."""

    MARKDOWN = "markdown"
    JSON = "json"


class CatalogRequest(BaseModel):
    """Input for agent-contract discovery."""

    model_config = ConfigDict(extra="forbid")

    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Use markdown for human reading or json for programmatic processing.",
    )


class TriagePreviewRequest(BaseModel):
    """Input for a non-persisting ticket classification preview."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    ticket: str = Field(
        ...,
        min_length=3,
        max_length=20_000,
        description="HR request to classify, for example 'Payroll failed today and this is urgent'.",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Use markdown for human reading or json for programmatic processing.",
    )


class PolicyGuidanceRequest(BaseModel):
    """Input for grounded policy guidance."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        min_length=3,
        max_length=20_000,
        description="Policy question to answer from the configured policy corpus.",
    )
    allow_external_inference: bool = Field(
        default=False,
        description=(
            "Explicit consent to send the question to the configured remote LLM or embedding "
            "provider. Leave false for local-only execution."
        ),
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Use markdown for human reading or json for programmatic processing.",
    )


def _external_inference_configured() -> bool:
    """Return whether a policy query may leave the local process."""
    embedding_provider = settings.embedding_provider.strip().lower()
    return llm_active() or embedding_provider not in {"", "local"}


def _bounded_json(payload: dict[str, Any]) -> str:
    """Serialize a response without flooding an MCP client's context."""
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if len(rendered) <= CHARACTER_LIMIT:
        return rendered
    return json.dumps(
        {
            "error": "Response exceeded the MCP character limit.",
            "truncated": True,
            "guidance": "Request a narrower result or use markdown output.",
        },
        indent=2,
    )


def _catalog_payload() -> dict[str, Any]:
    agents = []
    for spec in AGENT_SPECS.values():
        agents.append(
            {
                "name": spec.name,
                "label": spec.label,
                "framework": spec.framework,
                "purpose": spec.purpose,
                "minimum_role": spec.min_role,
                "risk": spec.risk,
                "tools": spec.tools,
                "guardrails": spec.guardrails,
            }
        )
    return {
        "agents": agents,
        "count": len(agents),
        "mcp_scope": "read-only decision support",
        "excluded_sensitive_surfaces": [
            "resume content",
            "attrition records",
            "case mutation",
            "policy ingestion",
            "human approvals",
        ],
    }


@mcp.tool(
    name="hrcc_get_agent_catalog",
    annotations={
        "title": "Get HR agent contracts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def hrcc_get_agent_catalog(request: CatalogRequest) -> str:
    """Return agent purposes, minimum roles, risk levels, tools, and guardrails.

    Use this before choosing an HR workflow or explaining why a sensitive
    capability is unavailable through MCP. The response never includes secrets,
    employee records, case contents, or runtime provider URLs.
    """
    payload = _catalog_payload()
    if request.response_format == ResponseFormat.JSON:
        return _bounded_json(payload)

    lines = [
        "# HR Command Center agent catalog",
        "",
        "MCP scope: read-only decision support. Sensitive records and writes stay in the app.",
        "",
    ]
    for agent in payload["agents"]:
        lines.extend(
            [
                f"## {agent['label']} (`{agent['name']}`)",
                f"- Framework: {agent['framework']}",
                f"- Minimum app role: {agent['minimum_role']}",
                f"- Risk posture: {agent['risk']}",
                f"- Purpose: {agent['purpose']}",
                f"- Guardrails: {'; '.join(agent['guardrails'])}",
                "",
            ]
        )
    return "\n".join(lines)


@mcp.tool(
    name="hrcc_preview_ticket_triage",
    annotations={
        "title": "Preview HR ticket triage",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def hrcc_preview_ticket_triage(request: TriagePreviewRequest) -> str:
    """Classify an HR request locally without creating or updating a case.

    The deterministic baseline returns a category, matched signals, rationale,
    and recommended next step. It never invokes a model, sends text to an
    external provider, or mutates the case store. URGENT previews always direct
    the caller to immediate human escalation.
    """
    ticket = sanitize_text(request.ticket)
    if detect_prompt_injection(ticket):
        payload = {
            "blocked": True,
            "category": None,
            "needs_human_review": True,
            "message": REFUSAL_MESSAGE,
        }
    else:
        result = triage_keyword_baseline.predict(ticket)
        payload = {
            "blocked": False,
            "category": result.category,
            "method": "deterministic_keyword_baseline",
            "matched_signals": list(result.matched_terms),
            "defaulted": result.defaulted,
            "rationale": triage_keyword_baseline.reason(ticket),
            "needs_human_review": result.category == "URGENT" or result.defaulted,
            "recommended_next_step": (
                "Escalate to a human immediately; do not auto-resolve."
                if result.category == "URGENT"
                else "Review the preview in the authenticated command center before acting."
            ),
        }

    if request.response_format == ResponseFormat.JSON:
        return _bounded_json(payload)
    if payload["blocked"]:
        return f"# Triage preview blocked\n\n{payload['message']}"
    signals = ", ".join(payload["matched_signals"]) or "none"
    return "\n".join(
        [
            "# Ticket triage preview",
            "",
            f"- Category: **{payload['category']}**",
            f"- Method: {payload['method']}",
            f"- Matched signals: {signals}",
            f"- Human review: {'required' if payload['needs_human_review'] else 'recommended'}",
            f"- Rationale: {payload['rationale']}",
            f"- Next step: {payload['recommended_next_step']}",
        ]
    )


@mcp.tool(
    name="hrcc_get_policy_guidance",
    annotations={
        "title": "Get grounded HR policy guidance",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def hrcc_get_policy_guidance(request: PolicyGuidanceRequest) -> str:
    """Answer an HR policy question from the configured policy corpus.

    This operation does not mutate business records, but it writes an audit row.
    When a remote LLM or embedding provider is active, the call is refused unless
    ``allow_external_inference`` is true. Answers remain advisory and include
    source documents, confidence, and a human-review flag.
    """
    question = sanitize_text(request.question)
    if _external_inference_configured() and not request.allow_external_inference:
        return _bounded_json(
            {
                "error": "External inference is configured but consent was not provided.",
                "action": (
                    "Set allow_external_inference=true only after confirming the policy "
                    "question may be sent to the configured provider."
                ),
            }
        )

    try:
        result = await policy_qa_agent.run(question)
    except Exception as exc:  # noqa: BLE001 - return an actionable MCP tool error
        return _bounded_json(
            {
                "error": "Policy guidance is temporarily unavailable.",
                "error_type": type(exc).__name__,
                "action": "Check the policy corpus and vector backend, then retry.",
            }
        )

    payload = {
        "answer": result.get("answer", ""),
        "confidence_score": result.get("confidence_score", 0.0),
        "needs_review": result.get("needs_review", False),
        "source_documents": result.get("source_documents", [])[:5],
        "mode": result.get("mode", "unknown"),
    }
    if request.response_format == ResponseFormat.JSON:
        return _bounded_json(payload)

    sources = payload["source_documents"]
    source_lines = [
        f"- `{source.get('doc_id', 'unknown')}`" for source in sources if isinstance(source, dict)
    ]
    return "\n".join(
        [
            "# Policy guidance",
            "",
            str(payload["answer"]),
            "",
            f"- Confidence: {float(payload['confidence_score']):.2f}",
            f"- Human review: {'required' if payload['needs_review'] else 'not flagged'}",
            f"- Mode: {payload['mode']}",
            "- Sources:",
            *(source_lines or ["- No source documents were retrieved."]),
        ]
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
