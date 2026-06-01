"""Contract tests: every agent's real output validates against its schema.

This is what makes the fleet "engineered, not loose" — each agent is held to a
declared Pydantic output contract, and the registry (AGENT_SPECS) is checked for
completeness so no agent can ship without a spec.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_registry_is_complete() -> None:
    """Every registered agent in the API matches a spec with required fields."""
    from agents.contracts import AGENT_SPECS
    from api.routes.agents import AGENT_REGISTRY

    api_names = {a["name"] for a in AGENT_REGISTRY}
    spec_names = set(AGENT_SPECS)
    assert api_names == spec_names, (api_names, spec_names)

    for spec in AGENT_SPECS.values():
        assert spec.purpose and spec.min_role in {"viewer", "analyst", "manager", "admin"}
        assert spec.tools, f"{spec.name} declares no tools"
        assert spec.guardrails, f"{spec.name} declares no guardrails"
        assert spec.risk in {"advisory", "decision-support", "gated-write", "escalate"}


def test_triage_output_matches_contract() -> None:
    from agents.contracts import validate_output
    from agents.triage_agent import triage_agent

    result = asyncio.run(triage_agent.run("System down, payroll fails today, urgent!"))
    validated = validate_output("triage_agent", result)
    assert validated.category in (
        "URGENT",
        "POLICY",
        "BENEFITS",
        "ONBOARDING",
        "PERFORMANCE",
        "COMPLIANCE",
    )
    assert validated.case.id.startswith("CASE-")


def test_policy_output_matches_contract() -> None:
    from agents.contracts import validate_output
    from agents.policy_qa_agent import policy_qa_agent

    result = asyncio.run(policy_qa_agent.run("How many vacation days do I get?"))
    validated = validate_output("policy_qa_agent", result)
    assert 0.0 <= validated.confidence_score <= 1.0
    assert isinstance(validated.answer, str)


def test_resume_output_matches_contract() -> None:
    from agents.contracts import validate_output
    from agents.resume_screener_agent import resume_screener_agent

    result = asyncio.run(
        resume_screener_agent.run(
            "Senior Python engineer, FastAPI, AWS",
            "5 years Python, FastAPI, AWS, ML pipelines",
        )
    )
    validated = validate_output("resume_screener_agent", result)
    assert 0 <= validated.score <= 100
    assert validated.recommendation in ("hire", "no-hire")


def test_attrition_output_matches_contract() -> None:
    from agents.attrition_agent import attrition_agent
    from agents.contracts import validate_output

    result = asyncio.run(
        attrition_agent.run(
            {
                "tenure_months": 8,
                "performance_score": 2.0,
                "absence_days": 20,
                "last_promotion_months": 40,
                "salary_band": 1,
                "manager_rating": 2.0,
            }
        )
    )
    validated = validate_output("attrition_agent", result)
    assert 0.0 <= validated.attrition_risk_score <= 1.0
    assert len(validated.top_risk_factors) == 3


def test_onboarding_output_matches_contract() -> None:
    from agents.contracts import validate_output
    from agents.onboarding_agent import onboarding_agent

    result = asyncio.run(
        onboarding_agent.start(
            {"name": "Ada", "email": "ada@acme.com", "department": "eng", "manager": "m@acme.com"}
        )
    )
    validated = validate_output("onboarding_agent", result)
    assert validated.status in ("paused", "completed", "error")


def test_input_validation_rejects_bad_data() -> None:
    """Input models reject malformed payloads (systematic, not loose)."""
    from pydantic import ValidationError

    from agents.contracts import AttritionInput, TicketInput

    with pytest.raises(ValidationError):
        TicketInput(text="")  # empty not allowed
    with pytest.raises(ValidationError):
        AttritionInput(
            tenure_months=1,
            performance_score=9,  # out of 1..5 range
            absence_days=0,
            last_promotion_months=0,
            salary_band=1,
            manager_rating=3,
        )
