"""A2A cards for Fireworks-aware agent routing.

The cards are product contracts, not provider credentials. They describe what
each agent can do, which Fireworks primitive fits the workload, and which model
families are preferred. The concrete model is still selected at runtime from
``ALLOWED_MODELS`` only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.contracts import AGENT_SPECS

FireworksPrimitive = Literal[
    "batch",
    "embeddings",
    "json_schema",
    "prompt_cache",
    "reasoning",
    "streaming",
    "tool_calling",
    "vision",
]

ServingPath = Literal[
    "deterministic",
    "serverless_batch",
    "serverless_online",
    "serverless_streaming",
]

CostPosture = Literal["economy", "standard", "premium", "batch"]


class A2ACard(BaseModel):
    """Routing metadata shared between the orchestrator and agent fleet."""

    agent_name: str
    label: str
    owner_team: str
    purpose: str
    accepted_workloads: list[str]
    output_contract: str
    serving_path: ServingPath
    fireworks_primitives: list[FireworksPrimitive]
    model_family_preferences: list[str] = Field(
        description=(
            "Lowercase family hints, matched against ALLOWED_MODELS. These are "
            "preferences only; they are never used as default model ids."
        )
    )
    cost_posture: CostPosture
    risk_posture: str
    tools: list[str]
    collaboration_targets: list[str]
    human_review_triggers: list[str]
    amd_use_case: str

    def tool_name(self) -> str:
        """Return the OpenAI-compatible tool name for this card."""
        return f"dispatch_{self.agent_name}"

    def tool_description(self) -> str:
        """Pack routing-critical metadata into a model-visible tool description."""
        primitives = ", ".join(self.fireworks_primitives)
        workloads = ", ".join(self.accepted_workloads)
        targets = ", ".join(self.collaboration_targets) or "none"
        return (
            f"{self.label} A2A card. Purpose: {self.purpose} "
            f"Serving path: {self.serving_path}. Fireworks primitives: {primitives}. "
            f"Cost posture: {self.cost_posture}. Risk posture: {self.risk_posture}. "
            f"Use for: {workloads}. Collaborates with: {targets}. "
            f"AMD angle: {self.amd_use_case}"
        )


def _spec(name: str):
    return AGENT_SPECS[name]


AGENT_CARDS: dict[str, A2ACard] = {
    "triage_agent": A2ACard(
        agent_name="triage_agent",
        label=_spec("triage_agent").label,
        owner_team="HR Ops Intake",
        purpose=_spec("triage_agent").purpose,
        accepted_workloads=[
            "ticket classification",
            "urgent escalation",
            "routing to policy Q&A",
        ],
        output_contract="TriageResult",
        serving_path="serverless_streaming",
        fireworks_primitives=["streaming", "json_schema", "tool_calling"],
        model_family_preferences=[
            "flash",
            "20b",
            "8b",
            "mini",
            "coder",
            "qwen",
            "kimi",
            "deepseek",
        ],
        cost_posture="economy",
        risk_posture=_spec("triage_agent").risk,
        tools=_spec("triage_agent").tools,
        collaboration_targets=["policy_qa_agent", "onboarding_agent"],
        human_review_triggers=[
            "URGENT category",
            "cross-agent category disagreement",
            "confidence below threshold",
        ],
        amd_use_case="high-volume low-latency classification on Fireworks serverless",
    ),
    "policy_qa_agent": A2ACard(
        agent_name="policy_qa_agent",
        label=_spec("policy_qa_agent").label,
        owner_team="People Policy",
        purpose=_spec("policy_qa_agent").purpose,
        accepted_workloads=[
            "policy question answering",
            "RAG synthesis",
            "citation-backed response",
        ],
        output_contract="PolicyAnswer",
        serving_path="serverless_online",
        fireworks_primitives=[
            "json_schema",
            "tool_calling",
            "prompt_cache",
            "streaming",
        ],
        model_family_preferences=[
            "qwen",
            "kimi",
            "deepseek",
            "glm",
            "plus",
            "pro",
            "120b",
        ],
        cost_posture="standard",
        risk_posture=_spec("policy_qa_agent").risk,
        tools=_spec("policy_qa_agent").tools,
        collaboration_targets=["triage_agent", "retention_resolver"],
        human_review_triggers=[
            "no source documents",
            "low confidence",
            "policy conflict",
        ],
        amd_use_case="structured, citation-bound RAG synthesis with prompt-cache locality",
    ),
    "resume_screener_agent": A2ACard(
        agent_name="resume_screener_agent",
        label=_spec("resume_screener_agent").label,
        owner_team="Recruiting",
        purpose=_spec("resume_screener_agent").purpose,
        accepted_workloads=[
            "resume screening",
            "scanned resume extraction",
            "bulk candidate comparison",
        ],
        output_contract="ResumeScore",
        serving_path="serverless_batch",
        fireworks_primitives=["batch", "vision", "json_schema"],
        model_family_preferences=[
            "vision",
            "vlm",
            "kimi",
            "qwen",
            "gemma",
            "gamma",
            "llama",
            "flash",
        ],
        cost_posture="batch",
        risk_posture=_spec("resume_screener_agent").risk,
        tools=_spec("resume_screener_agent").tools,
        collaboration_targets=["skill_validator", "triage_agent"],
        human_review_triggers=[
            "protected-attribute uncertainty",
            "low extraction confidence",
            "date consistency flags",
        ],
        amd_use_case="vision plus batch throughput for large candidate queues",
    ),
    "attrition_agent": A2ACard(
        agent_name="attrition_agent",
        label=_spec("attrition_agent").label,
        owner_team="People Analytics",
        purpose=_spec("attrition_agent").purpose,
        accepted_workloads=[
            "attrition explanation",
            "manager-facing advisory narrative",
            "retention risk synthesis",
        ],
        output_contract="AttritionResult",
        serving_path="serverless_batch",
        fireworks_primitives=["batch", "reasoning", "json_schema"],
        model_family_preferences=[
            "r1",
            "reason",
            "deepseek",
            "glm",
            "qwen",
            "pro",
            "120b",
        ],
        cost_posture="batch",
        risk_posture=_spec("attrition_agent").risk,
        tools=_spec("attrition_agent").tools,
        collaboration_targets=["policy_qa_agent", "retention_resolver"],
        human_review_triggers=[
            "risk above review threshold",
            "policy recommendation missing citations",
            "adverse-action language",
        ],
        amd_use_case="longer reasoning traces for auditable retention explanations",
    ),
    "onboarding_agent": A2ACard(
        agent_name="onboarding_agent",
        label=_spec("onboarding_agent").label,
        owner_team="HR Operations",
        purpose=_spec("onboarding_agent").purpose,
        accepted_workloads=[
            "new hire workflow",
            "account creation checklist",
            "training assignment",
        ],
        output_contract="OnboardingResult",
        serving_path="serverless_online",
        fireworks_primitives=["tool_calling", "json_schema", "streaming"],
        model_family_preferences=[
            "tool",
            "kimi",
            "deepseek",
            "glm",
            "coder",
            "qwen",
        ],
        cost_posture="standard",
        risk_posture=_spec("onboarding_agent").risk,
        tools=_spec("onboarding_agent").tools,
        collaboration_targets=["triage_agent"],
        human_review_triggers=[
            "state-changing step",
            "manager approval missing",
            "tool execution failure",
        ],
        amd_use_case="tool-calling workflow execution with a human checkpoint",
    ),
}


REQUEST_ALIASES: dict[str, str] = {
    "attrition": "attrition_agent",
    "attrition_explanation": "attrition_agent",
    "case_triage": "triage_agent",
    "classification": "triage_agent",
    "complex_reasoning": "attrition_agent",
    "onboarding": "onboarding_agent",
    "policy": "policy_qa_agent",
    "policy_qa": "policy_qa_agent",
    "rag": "policy_qa_agent",
    "resume": "resume_screener_agent",
    "resume_analysis": "resume_screener_agent",
    "resume_screening": "resume_screener_agent",
    "streaming_chat": "policy_qa_agent",
    "structured_classification": "triage_agent",
    "triage": "triage_agent",
}


def get_card(agent_or_workload: str) -> A2ACard:
    """Return a card by agent name or workload alias."""
    key = agent_or_workload.strip().lower()
    agent_name = REQUEST_ALIASES.get(key, key)
    try:
        return AGENT_CARDS[agent_name]
    except KeyError as exc:
        raise ValueError(f"unknown A2A agent or workload: {agent_or_workload}") from exc


def cards_to_tools(cards: dict[str, A2ACard] | None = None) -> list[dict[str, object]]:
    """Expose A2A cards as OpenAI-compatible function tools."""
    registry = cards or AGENT_CARDS
    tools: list[dict[str, object]] = []
    for card in registry.values():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": card.tool_name(),
                    "description": card.tool_description(),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "payload": {
                                "type": "object",
                                "description": "Input payload to hand to the target agent.",
                            },
                            "reason": {
                                "type": "string",
                                "description": (
                                    "Why this card, serving path, and risk posture fit the request."
                                ),
                            },
                        },
                        "required": ["payload", "reason"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    return sorted(tools, key=lambda tool: str(tool["function"]["name"]))


def a2a_card_manifest() -> dict[str, object]:
    """Return a no-secret card manifest for lifecycle and product views."""
    return {
        "card_count": len(AGENT_CARDS),
        "tool_count": len(cards_to_tools()),
        "cards": {
            name: {
                "label": card.label,
                "owner_team": card.owner_team,
                "serving_path": card.serving_path,
                "fireworks_primitives": card.fireworks_primitives,
                "cost_posture": card.cost_posture,
                "risk_posture": card.risk_posture,
                "collaboration_targets": card.collaboration_targets,
                "human_review_triggers": card.human_review_triggers,
                "model_selection": "runtime ALLOWED_MODELS only",
                "model_family_preferences": card.model_family_preferences,
                "amd_use_case": card.amd_use_case,
            }
            for name, card in AGENT_CARDS.items()
        },
    }
