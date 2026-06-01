"""Formal agent contracts — typed I/O schemas + a single-source-of-truth registry.

The agents were prototyped with loose ``dict`` returns. This module engineers them
**systematically**: every agent has an explicit Pydantic **output schema**, a
declared **input model**, a required **RBAC role**, its **tools**, and **guardrails**.
A boundary validator (:func:`validate_output`) checks an agent's real output against
its schema so contract drift is caught in tests and (optionally) at runtime.

This makes the fleet auditable and self-documenting: ``AGENT_SPECS`` is the source
the API, the docs ([AGENT_PLAYBOOK.md]) and the tests all derive from.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


class TicketInput(BaseModel):
    """Free-text HR ticket for triage / policy Q&A."""

    text: str = Field(..., min_length=1, description="The ticket or question text.")


class ResumeInput(BaseModel):
    """A resume scored against a job description."""

    job_description: str = Field("", description="Target role description.")
    resume: str = Field(..., min_length=1, description="Candidate resume text.")


class NewHireInput(BaseModel):
    """A new-hire record for onboarding orchestration."""

    name: str
    email: str
    department: str = "general"
    manager: str = ""


class AttritionInput(BaseModel):
    """The six employee features the attrition model expects."""

    tenure_months: float
    performance_score: float = Field(..., ge=1, le=5)
    absence_days: float = Field(..., ge=0)
    last_promotion_months: float = Field(..., ge=0)
    salary_band: float = Field(..., ge=1, le=5)
    manager_rating: float = Field(..., ge=1, le=5)


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #

CATEGORIES = ["BENEFITS", "POLICY", "ONBOARDING", "PERFORMANCE", "COMPLIANCE", "URGENT"]


class CaseRef(BaseModel):
    """A minimal reference to a created/updated case."""

    id: str
    category: str
    status: str
    assigned_agent: str

    model_config = {"extra": "ignore"}


class TriageResult(BaseModel):
    """Triage agent output contract."""

    category: str
    case: CaseRef
    resolution: dict[str, Any] | None = None

    model_config = {"extra": "ignore"}


class PolicyAnswer(BaseModel):
    """Policy Q&A output contract."""

    answer: str
    source_documents: list[dict[str, Any]] = []
    confidence_score: float = Field(..., ge=0, le=1)
    needs_review: bool = False  # confidence below threshold → route to a human

    model_config = {"extra": "ignore"}


class ResumeScore(BaseModel):
    """Resume screener output contract."""

    score: int = Field(..., ge=0, le=100)
    recommendation: str
    reasoning: str
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    blinded: bool = True  # protected attributes removed before scoring
    needs_review: bool = False  # insufficient input → not a valid assessment
    # Advisory data-integrity flags from the timeline cross-validation pass
    # (reversed/future date ranges, fully-overlapping roles). Never affects the
    # score; sets needs_review for a human to verify.
    consistency_flags: list[str] = []

    model_config = {"extra": "ignore"}


class RiskFactor(BaseModel):
    factor: str
    contribution: float


class AttritionResult(BaseModel):
    """Attrition predictor output contract."""

    attrition_risk_score: float = Field(..., ge=0, le=1)
    top_risk_factors: list[RiskFactor]
    explanation: str
    needs_review: bool = False  # high risk → human bias review before action
    advisory_only: bool = True  # never an automated adverse decision
    # Grounded, policy-cited retention suggestions composed from Policy Q&A when
    # risk is high (advisory; empty otherwise).
    retention_context: list[dict[str, Any]] = []

    model_config = {"extra": "ignore"}


class OnboardingResult(BaseModel):
    """Onboarding orchestrator output contract (pauses for approval)."""

    status: str  # paused | error | completed
    task: dict[str, Any] | None = None
    state: dict[str, Any] | None = None

    model_config = {"extra": "ignore"}


# --------------------------------------------------------------------------- #
# Registry: the single source of truth for the fleet
# --------------------------------------------------------------------------- #


class AgentSpec(BaseModel):
    """A complete, declarative specification for one agent."""

    name: str
    label: str
    framework: str
    purpose: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    min_role: str  # viewer | analyst | manager | admin
    tools: list[str] = []
    guardrails: list[str] = []
    risk: str  # advisory | decision-support | gated-write | escalate

    model_config = {"arbitrary_types_allowed": True}


AGENT_SPECS: dict[str, AgentSpec] = {
    "triage_agent": AgentSpec(
        name="triage_agent",
        label="Triage",
        framework="CrewAI",
        purpose="Classify an HR ticket and route it: URGENT→human, POLICY→auto-resolve, else categorise.",
        input_model=TicketInput,
        output_model=TriageResult,
        min_role="analyst",
        tools=["keyword_classifier|llm_classifier", "rag_pipeline", "cases_store"],
        guardrails=[
            "URGENT always escalates to a human; never auto-resolved.",
            "Every classification is written to the audit log.",
        ],
        risk="escalate",
    ),
    "policy_qa_agent": AgentSpec(
        name="policy_qa_agent",
        label="Policy Q&A",
        framework="LangGraph",
        purpose="Answer policy questions from ingested documents with citations.",
        input_model=TicketInput,
        output_model=PolicyAnswer,
        min_role="viewer",
        tools=["qdrant_search", "get_policy_doc", "claude_synthesis"],
        guardrails=[
            "Answers are grounded in retrieved documents; cites doc_id.",
            "Returns 'no relevant policy' rather than hallucinating when empty.",
        ],
        risk="advisory",
    ),
    "resume_screener_agent": AgentSpec(
        name="resume_screener_agent",
        label="Resume Screener",
        framework="CrewAI",
        purpose="Score a resume against a JD and explain the fit.",
        input_model=ResumeInput,
        output_model=ResumeScore,
        min_role="analyst",
        tools=["embedding_similarity", "skill_matcher", "crewai_crew"],
        guardrails=[
            "Decision-support only — never auto-rejects a candidate.",
            "Every screen is audited with the score and recommendation.",
        ],
        risk="decision-support",
    ),
    "onboarding_agent": AgentSpec(
        name="onboarding_agent",
        label="Onboarding Orchestrator",
        framework="LangGraph",
        purpose="Run the new-hire checklist, pausing for human approval before sensitive steps.",
        input_model=NewHireInput,
        output_model=OnboardingResult,
        min_role="manager",
        tools=["validate", "create_accounts", "assign_training", "notify"],
        guardrails=[
            "State-changing steps require explicit human approval.",
            "Approval AND rejection are captured in the audit log with a reason.",
        ],
        risk="gated-write",
    ),
    "attrition_agent": AgentSpec(
        name="attrition_agent",
        label="Attrition Predictor",
        framework="scikit-learn",
        purpose="Score attrition risk from six features and surface the top drivers.",
        input_model=AttritionInput,
        output_model=AttritionResult,
        min_role="manager",
        tools=["random_forest", "feature_attribution", "claude_explanation"],
        guardrails=[
            "Advisory only — framed to start a retention conversation, never punitive.",
            "Access-controlled (manager+); sensitive-data handling reviewed.",
        ],
        risk="advisory",
    ),
}


def validate_output(agent_name: str, result: Any) -> BaseModel:
    """Validate an agent's raw output against its declared schema.

    Args:
        agent_name: Registry name of the agent.
        result: The agent's raw output (usually a dict).

    Returns:
        The parsed, validated Pydantic model instance.

    Raises:
        KeyError: if the agent is unknown.
        pydantic.ValidationError: if the output violates the contract.
    """
    spec = AGENT_SPECS[agent_name]
    return spec.output_model.model_validate(result)
