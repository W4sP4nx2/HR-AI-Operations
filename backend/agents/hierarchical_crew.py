"""Governed hierarchical CrewAI systems for HR decision support.

Two complete systems are exposed:

* ``resume_review`` — an evidence analyst and fairness guard coordinated by a
  talent-review manager.
* ``policy_case_resolution`` — a triage analyst and policy guard coordinated by
  an HR-operations manager.

The live path constructs a real CrewAI ``Process.hierarchical`` crew with a
custom manager agent. The deterministic path executes the same two worker
contracts locally so the product remains demoable without packages, provider
credentials, or network access. Run metadata always states which path ran.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from core.a2a_envelope import A2AEnvelope, certified_handoff
from core.guardrails import blind_demographics, detect_prompt_injection
from core.safety import redact_obj
from services.input_shield import sanitize_text

ExecutionMode = Literal["auto", "deterministic", "live"]
ResolvedExecutionMode = Literal["deterministic_fallback", "crewai_live"]


class CrewCapabilityUnavailable(RuntimeError):
    """Raised when an explicitly requested live CrewAI run cannot start."""


class WorkerAgentSpec(BaseModel):
    """One lower-level agent in a hierarchical crew."""

    agent_id: str
    role: str
    goal: str
    backstory: str
    allow_delegation: bool = False


class HierarchicalSystemSpec(BaseModel):
    """Static, secret-free topology and use-case contract."""

    system_id: str
    label: str
    use_case: str
    process: Literal["hierarchical"] = "hierarchical"
    manager_agent: WorkerAgentSpec
    worker_agents: list[WorkerAgentSpec]
    required_inputs: list[str]
    expected_output: str
    human_decision_boundary: str


class WorkerExecution(BaseModel):
    """Reviewable output from one delegated worker step."""

    agent_id: str
    role: str
    status: Literal["completed", "delegated"]
    summary: str
    evidence: list[str] = Field(default_factory=list)
    human_review_required: bool = False


class CrewHandoff(BaseModel):
    """One visible relationship in the governed manager-led run."""

    source: str
    target: str
    contract: str
    status: Literal["completed", "delegated", "awaiting_human_review"]


class HierarchicalCrewOutput(BaseModel):
    """Certified result returned by either execution path."""

    orchestration_id: str
    system_id: str
    use_case: str
    process: Literal["hierarchical"] = "hierarchical"
    manager_agent: str
    worker_agents: list[str]
    execution_mode: ResolvedExecutionMode
    status: Literal["completed", "review_required"]
    summary: str
    steps: list[WorkerExecution]
    handoffs: list[CrewHandoff]
    human_review_required: bool
    guardrails: list[str]


@dataclass(frozen=True)
class _PreparedInput:
    values: dict[str, str]
    controls: dict[str, bool]


HIERARCHICAL_SYSTEMS: dict[str, HierarchicalSystemSpec] = {
    "resume_review": HierarchicalSystemSpec(
        system_id="resume_review",
        label="Hierarchical Resume Review",
        use_case="Produce evidence-based candidate-role review notes without making a hiring decision.",
        manager_agent=WorkerAgentSpec(
            agent_id="talent_review_manager",
            role="Talent Review Manager",
            goal="Delegate evidence and fairness checks, reconcile conflicts, and require human review.",
            backstory="A senior talent-operations reviewer accountable for fair, auditable decision support.",
            allow_delegation=True,
        ),
        worker_agents=[
            WorkerAgentSpec(
                agent_id="resume_evidence_analyst",
                role="Resume Evidence Analyst",
                goal="Compare demonstrated skills with job requirements and report only reviewable evidence.",
                backstory="A structured evidence analyst who separates matches, gaps, and unsupported claims.",
            ),
            WorkerAgentSpec(
                agent_id="fairness_policy_guard",
                role="Fairness and Policy Guard",
                goal="Detect protected-data, injection, and evidence-quality risks before human review.",
                backstory="An HR governance specialist who cannot approve or reject candidates.",
            ),
        ],
        required_inputs=["job_description", "resume"],
        expected_output="Advisory skill evidence, fairness controls, conflicts, and a human-review requirement.",
        human_decision_boundary="A qualified human recruiter owns every hiring decision.",
    ),
    "policy_case_resolution": HierarchicalSystemSpec(
        system_id="policy_case_resolution",
        label="Hierarchical HR Case Resolution",
        use_case="Triage an HR case and validate its policy grounding before a human acts.",
        manager_agent=WorkerAgentSpec(
            agent_id="hr_operations_manager",
            role="HR Operations Manager",
            goal="Delegate classification and policy checks, resolve disagreement, and route risky cases to people.",
            backstory="An HR operations lead responsible for safe routing, service quality, and escalation.",
            allow_delegation=True,
        ),
        worker_agents=[
            WorkerAgentSpec(
                agent_id="case_triage_analyst",
                role="Case Triage Analyst",
                goal="Classify the case, explain lexical evidence, and identify urgent escalation signals.",
                backstory="A queue-routing specialist who never resolves sensitive cases autonomously.",
            ),
            WorkerAgentSpec(
                agent_id="policy_grounding_guard",
                role="Policy Grounding Guard",
                goal="Check whether the proposed route has current policy context and flag unsupported advice.",
                backstory="A policy-control specialist who requires citations and human review when evidence is weak.",
            ),
        ],
        required_inputs=["ticket"],
        expected_output="A category, escalation posture, grounding status, and reviewable next action.",
        human_decision_boundary="Urgent, sensitive, or ungrounded cases must be decided by a human HR reviewer.",
    ),
}


def hierarchical_system_manifest() -> dict[str, Any]:
    """Return the two implemented topologies and their live-runtime boundary."""
    from agents.crewai_adapter import crewai_available
    from agents.langsmith_cost_tracker import langsmith_configured

    return {
        "architecture": "hierarchical",
        "product_boundary": "single_orchestrator_with_bounded_crewai_subtask",
        "context_source": "validated_endpoint_parameters",
        "external_repository_fetch": False,
        "system_count": len(HIERARCHICAL_SYSTEMS),
        "systems": [spec.model_dump(mode="json") for spec in HIERARCHICAL_SYSTEMS.values()],
        "runtime": {
            "crewai_importable": crewai_available(),
            "langsmith_configured": langsmith_configured(),
            "default_mode": "auto",
            "fallback": "deterministic_fallback",
            "live_requirement": "CrewAI package plus a configured, allowlisted LLM provider",
        },
    }


def _system(system_id: str) -> HierarchicalSystemSpec:
    try:
        return HIERARCHICAL_SYSTEMS[system_id]
    except KeyError as exc:
        raise KeyError(f"unknown hierarchical crew system: {system_id}") from exc


def _prepare_inputs(spec: HierarchicalSystemSpec, values: dict[str, Any]) -> _PreparedInput:
    missing = [name for name in spec.required_inputs if not str(values.get(name, "")).strip()]
    if missing:
        raise ValueError(f"missing required input(s): {', '.join(missing)}")

    cleaned = {
        key: sanitize_text(str(value))
        for key, value in values.items()
        if key in {*spec.required_inputs, "policy_context", "policy_version"} and value is not None
    }
    injection = any(detect_prompt_injection(value) for value in cleaned.values())
    redacted = {key: str(value) for key, value in redact_obj(cleaned).items()}
    pii_redacted = redacted != cleaned
    demographic_blinded = False
    if spec.system_id == "resume_review":
        resume = redacted["resume"]
        blinded = blind_demographics(resume)
        demographic_blinded = blinded != resume
        redacted["resume"] = blinded
    return _PreparedInput(
        values=redacted,
        controls={
            "prompt_injection_detected": injection,
            "pii_redaction_applied": pii_redacted,
            "demographic_blinding_applied": demographic_blinded,
        },
    )


def _resume_evidence_worker(prepared: _PreparedInput) -> WorkerExecution:
    from agents.resume_screener_agent import _extract_skill_terms
    from services.skill_normalizer import SkillOntologyMapper

    mapper = SkillOntologyMapper()
    required = mapper.normalize_names(_extract_skill_terms(prepared.values["job_description"]))
    demonstrated = set(mapper.normalize_names(_extract_skill_terms(prepared.values["resume"])))
    matched = [skill for skill in required if skill in demonstrated]
    missing = [skill for skill in required if skill not in demonstrated]
    coverage = round((len(matched) / len(required)) * 100) if required else 0
    return WorkerExecution(
        agent_id="resume_evidence_analyst",
        role="Resume Evidence Analyst",
        status="completed",
        summary=f"Found {len(matched)} matched and {len(missing)} missing normalized skills ({coverage}% coverage).",
        evidence=[
            f"matched_skills={','.join(matched[:12]) or 'none'}",
            f"missing_skills={','.join(missing[:12]) or 'none'}",
            f"coverage_percent={coverage}",
        ],
        human_review_required=True,
    )


def _resume_fairness_worker(prepared: _PreparedInput) -> WorkerExecution:
    controls = prepared.controls
    risks = [name for name, active in controls.items() if active]
    short_input = len(prepared.values["resume"].split()) < 8
    if short_input:
        risks.append("insufficient_resume_context")
    return WorkerExecution(
        agent_id="fairness_policy_guard",
        role="Fairness and Policy Guard",
        status="completed",
        summary=(
            "Input controls require recruiter review."
            if risks
            else "No deterministic input-control violation detected; human review still applies."
        ),
        evidence=[f"control={risk}" for risk in risks] or ["control=passed_deterministic_checks"],
        human_review_required=True,
    )


def _case_triage_worker(prepared: _PreparedInput) -> WorkerExecution:
    from models.naive_baselines import triage_keyword_baseline

    result = triage_keyword_baseline.predict(prepared.values["ticket"])
    urgent = result.category == "URGENT"
    return WorkerExecution(
        agent_id="case_triage_analyst",
        role="Case Triage Analyst",
        status="completed",
        summary=f"Classified the case as {result.category} using deterministic lexical evidence.",
        evidence=[
            f"category={result.category}",
            f"matched_terms={','.join(result.matched_terms) or 'none'}",
            f"defaulted={str(result.defaulted).lower()}",
        ],
        human_review_required=urgent or result.defaulted,
    )


def _policy_guard_worker(prepared: _PreparedInput) -> WorkerExecution:
    context = prepared.values.get("policy_context", "").strip()
    version = prepared.values.get("policy_version", "").strip()
    grounded = bool(context)
    injection = prepared.controls["prompt_injection_detected"]
    return WorkerExecution(
        agent_id="policy_grounding_guard",
        role="Policy Grounding Guard",
        status="completed",
        summary=(
            "Policy context is present for human verification."
            if grounded and not injection
            else "Policy grounding is incomplete or unsafe; do not auto-resolve."
        ),
        evidence=[
            f"policy_context_present={str(grounded).lower()}",
            f"policy_version={version or 'unspecified'}",
            f"prompt_injection_detected={str(injection).lower()}",
        ],
        human_review_required=not grounded or injection,
    )


def _deterministic_steps(spec: HierarchicalSystemSpec, prepared: _PreparedInput) -> list[WorkerExecution]:
    if spec.system_id == "resume_review":
        return [_resume_evidence_worker(prepared), _resume_fairness_worker(prepared)]
    return [_case_triage_worker(prepared), _policy_guard_worker(prepared)]


def _manager_summary(spec: HierarchicalSystemSpec, steps: list[WorkerExecution]) -> str:
    if spec.system_id == "resume_review":
        return (
            "The manager reconciled skill evidence with fairness controls. "
            "This output is decision support only and is queued for recruiter review."
        )
    category = next(
        (item.split("=", 1)[1] for step in steps for item in step.evidence if item.startswith("category=")),
        "POLICY",
    )
    return (
        f"The manager reconciled the {category} route with the policy-grounding check. "
        "Sensitive or unsupported actions remain with an HR reviewer."
    )


def _guardrail_labels(prepared: _PreparedInput) -> list[str]:
    labels = ["pii_redaction", "prompt_injection_detection", "certified_a2a_output"]
    if "resume" in prepared.values:
        labels.append("demographic_blinding")
    labels.append("human_decision_boundary")
    return labels


def _handoffs(spec: HierarchicalSystemSpec, *, live: bool) -> list[CrewHandoff]:
    worker_status: Literal["completed", "delegated"] = "delegated" if live else "completed"
    handoffs = [
        CrewHandoff(
            source=spec.manager_agent.agent_id,
            target=worker.agent_id,
            contract="sanitized endpoint parameters -> reviewable specialist evidence",
            status=worker_status,
        )
        for worker in spec.worker_agents
    ]
    handoffs.append(
        CrewHandoff(
            source=spec.manager_agent.agent_id,
            target="human_reviewer",
            contract="certified advisory output -> durable approval task",
            status="awaiting_human_review",
        )
    )
    return handoffs


def build_hierarchical_crewai(system_id: str, *, llm: Any | None = None) -> Any:
    """Build a live CrewAI hierarchy with one manager and two worker agents."""
    spec = _system(system_id)
    try:
        from crewai import Agent, Crew, Process, Task
    except ImportError as exc:
        raise CrewCapabilityUnavailable("CrewAI is not installed") from exc

    if llm is None:
        from core.llm_factory import crewai_llm_for

        live_llm = crewai_llm_for(role=f"{system_id}_synthesis")
    else:
        live_llm = llm
    manager = Agent(
        role=spec.manager_agent.role,
        goal=spec.manager_agent.goal,
        backstory=spec.manager_agent.backstory,
        allow_delegation=True,
        llm=live_llm,
        verbose=False,
        max_iter=4,
    )
    workers = [
        Agent(
            role=worker.role,
            goal=worker.goal,
            backstory=worker.backstory,
            allow_delegation=False,
            llm=live_llm,
            verbose=False,
            max_iter=3,
        )
        for worker in spec.worker_agents
    ]
    task = Task(
        description=(
            f"{spec.use_case}\n"
            "The manager must delegate evidence analysis to both specialists, reconcile conflicts, "
            "and preserve the human decision boundary. Work item: {work_item}"
        ),
        expected_output=spec.expected_output,
    )
    return Crew(
        agents=workers,
        tasks=[task],
        manager_agent=manager,
        process=Process.hierarchical,
        planning=False,
        verbose=False,
    )


async def _live_output(
    spec: HierarchicalSystemSpec,
    prepared: _PreparedInput,
    orchestration_id: str,
    tracer: Any,
) -> HierarchicalCrewOutput:
    crew = build_hierarchical_crewai(spec.system_id)
    inputs = {"work_item": json.dumps(prepared.values, sort_keys=True)}
    if hasattr(crew, "akickoff"):
        raw = await crew.akickoff(inputs=inputs)
    else:  # CrewAI before native async support
        raw = await asyncio.to_thread(crew.kickoff, inputs=inputs)
    summary = str(getattr(raw, "raw", raw))[:1800]
    steps = [
        WorkerExecution(
            agent_id=worker.agent_id,
            role=worker.role,
            status="delegated",
            summary="CrewAI manager delegated this specialist role and completed the hierarchy.",
            evidence=["runtime=crewai_live", "raw_hr_payload_exported_to_langsmith=false"],
            human_review_required=True,
        )
        for worker in spec.worker_agents
    ]
    for step in steps:
        tracer.record_step(step.agent_id, step.model_dump(mode="json"))
    return HierarchicalCrewOutput(
        orchestration_id=orchestration_id,
        system_id=spec.system_id,
        use_case=spec.use_case,
        manager_agent=spec.manager_agent.agent_id,
        worker_agents=[worker.agent_id for worker in spec.worker_agents],
        execution_mode="crewai_live",
        status="review_required",
        summary=summary,
        steps=steps,
        handoffs=_handoffs(spec, live=True),
        human_review_required=True,
        guardrails=_guardrail_labels(prepared),
    )


async def run_hierarchical_system(
    system_id: str,
    inputs: dict[str, Any],
    *,
    mode: ExecutionMode = "auto",
) -> A2AEnvelope:
    """Run one hierarchy and return a certified manager-to-human envelope."""
    spec = _system(system_id)
    prepared = _prepare_inputs(spec, inputs)
    # Use a letter-only UUID representation. Digit-heavy UUID fragments can be
    # mistaken for phone numbers by strict PII certifiers, creating a flaky
    # false positive even though the identifier is random and non-personal.
    digit_letters = str.maketrans("0123456789", "ghijklmnop")
    orchestration_id = f"orch_{uuid4().hex.translate(digit_letters)}"

    from agents.crewai_adapter import crewai_available
    from agents.langsmith_cost_tracker import HierarchicalTrace
    from core.runtime_key import llm_active

    live_ready = crewai_available() and llm_active()
    if mode == "live" and not live_ready:
        raise CrewCapabilityUnavailable(
            "live mode requires the CrewAI package and a configured allowlisted LLM provider"
        )
    resolved_live = mode == "live" or (mode == "auto" and live_ready)
    tracer = HierarchicalTrace(
        name=f"crewai_{system_id}",
        orchestration_id=orchestration_id,
        inputs=prepared.values,
        metadata={"system_id": system_id, "process": "hierarchical"},
    )

    async def _execute(_: dict[str, Any]) -> dict[str, Any]:
        if resolved_live:
            output = await _live_output(spec, prepared, orchestration_id, tracer)
        else:
            steps = _deterministic_steps(spec, prepared)
            for step in steps:
                tracer.record_step(step.agent_id, step.model_dump(mode="json"))
            review = any(step.human_review_required for step in steps)
            output = HierarchicalCrewOutput(
                orchestration_id=orchestration_id,
                system_id=spec.system_id,
                use_case=spec.use_case,
                manager_agent=spec.manager_agent.agent_id,
                worker_agents=[worker.agent_id for worker in spec.worker_agents],
                execution_mode="deterministic_fallback",
                status="review_required" if review else "completed",
                summary=_manager_summary(spec, steps),
                steps=steps,
                handoffs=_handoffs(spec, live=False),
                human_review_required=review,
                guardrails=_guardrail_labels(prepared),
            )
        tracer.finish(output.model_dump(mode="json"))
        return output.model_dump(mode="json")

    envelope = await certified_handoff(
        source_agent=spec.manager_agent.agent_id,
        target_agent="human_reviewer",
        func=_execute,
        payload={"system_id": system_id, "orchestration_id": orchestration_id},
        objectives={
            "schema": HierarchicalCrewOutput.model_json_schema(),
            "require_pii_free": True,
        },
        metadata={
            "integration": "crewai",
            "process": "hierarchical",
            "product_boundary": "single_orchestrator_with_bounded_crewai_subtask",
            "context_source": "validated_endpoint_parameters",
            "external_repository_fetch": False,
            "orchestration_id": orchestration_id,
            "execution_mode": "crewai_live" if resolved_live else "deterministic_fallback",
            "worker_count": len(spec.worker_agents),
            "provider_call": resolved_live,
            "prefilter_skip": not resolved_live,
            "human_review_required": True,
        },
        cost_query=spec.use_case,
    )
    if resolved_live and not envelope.certification.is_valid:
        raise RuntimeError(
            "live CrewAI output failed certification: "
            + ", ".join(envelope.certification.violations)
        )
    if envelope.certification.is_valid and envelope.payload.get("human_review_required"):
        from core.memory import memory
        from services.audit_service import record_action

        task = await memory.create_agent_task(
            spec.manager_agent.agent_id,
            step="review_certified_crew_output",
            context=(
                f"{spec.label} produced certified advisory evidence. "
                "A qualified HR reviewer must approve, reject, or request changes."
            ),
            state={
                "orchestration_id": orchestration_id,
                "system_id": system_id,
                "trace_id": envelope.trace_id,
                "certified_output": envelope.payload,
            },
        )
        envelope.metadata.update(
            {
                "human_review_task_id": task["id"],
                "hitl_status": "awaiting_approval",
            }
        )
        await record_action(
            agent=spec.manager_agent.agent_id,
            action="human_review_queued",
            input_data={
                "orchestration_id": orchestration_id,
                "system_id": system_id,
            },
            output_data={
                "task_id": task["id"],
                "step": task["step"],
            },
            status="paused",
        )
    return envelope
