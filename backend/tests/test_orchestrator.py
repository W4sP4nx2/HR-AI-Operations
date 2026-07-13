"""No-key tests for the visible single-orchestrator product contract."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agents.orchestrator import build_orchestration_plan, orchestrate, orchestrator_manifest
from api.main import app

FAST_MODEL = "tenant/models/fast-8b"
STANDARD_MODEL = "tenant/models/standard-32b"
GEMMA_MODEL = "tenant/models/gemma-4-26b-a4b-it"


@pytest.fixture(autouse=True)
def orchestrator_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ALLOWED_MODELS", f"{FAST_MODEL},{STANDARD_MODEL},{GEMMA_MODEL}"
    )
    monkeypatch.setenv("FIREWORKS_GEMMA_MODEL", GEMMA_MODEL)
    monkeypatch.setenv("FIREWORKS_BATCH_MODEL", STANDARD_MODEL)


def test_simple_policy_query_exposes_economy_cost_route() -> None:
    plan = build_orchestration_plan(
        "policy_qa",
        {"query": "What is the vacation leave policy?"},
    )

    assert plan.workflow == "policy_qa"
    assert plan.serving_path == "standard"
    assert plan.cost_tier == "economy"
    assert plan.selected_model == FAST_MODEL
    assert plan.model_selection_source == "ALLOWED_MODELS"


def test_urgent_triage_uses_fast_path_and_human_review() -> None:
    plan = build_orchestration_plan(
        "triage",
        {"input": "Payroll is down today, urgent."},
    )

    assert plan.workflow == "triage"
    assert plan.serving_path == "fast"
    assert plan.human_review_required is True
    assert plan.fallback_available is True


def test_bulk_attrition_uses_batch_route() -> None:
    plan = build_orchestration_plan(
        "attrition_explanation",
        {
            "prompt": "Produce advisory retention summaries.",
            "records": [{"custom_id": "employee-1", "prompt": "review"}],
        },
    )

    assert plan.workflow == "attrition"
    assert plan.serving_path == "batch"
    assert plan.selected_model == STANDARD_MODEL
    assert plan.human_review_required is True


@pytest.mark.asyncio
async def test_orchestrator_result_is_certified_cached_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_events: list[dict[str, object]] = []

    async def fake_record_action(**kwargs):
        audit_events.append(kwargs)
        return {"id": "audit-1"}

    monkeypatch.setattr("agents.orchestrator.record_action", fake_record_action)
    query = f"Explain PTO for test {uuid4()}"
    first = await orchestrate("policy_qa", {"query": query})
    second = await orchestrate("policy_qa", {"query": query})

    assert first.provider_call is False
    assert first.certification.is_valid is True
    assert first.cache.hit is False
    assert first.audit.recorded is True
    assert first.audit.event_id == "audit-1"
    assert second.cache.hit is True
    assert len(audit_events) == 2
    assert "input_hash" in audit_events[0]["input_data"]
    assert query not in str(audit_events[0])


def test_manifest_exposes_observability_not_agent_handoffs() -> None:
    manifest = orchestrator_manifest()

    assert manifest["pattern"] == "single_orchestrator"
    assert "cost_tier" in manifest["visible_metrics"]
    assert "cache_hit" in manifest["visible_metrics"]
    assert "certification_status" in manifest["visible_metrics"]
    assert "cache_hit_rate" in manifest["runtime"]
    assert isinstance(manifest["last_route"], dict)
    assert "gemma_multimodal" in {
        tool["function"]["name"] for tool in manifest["tools"]
    }
    assert manifest["a2a_handoff"] == "certified_handoff with redacted route payload"


def test_lifecycle_manifest_surfaces_visible_orchestration() -> None:
    client = TestClient(app)
    response = client.get("/lifecycle/fireworks")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["orchestration"]["pattern"] == "single_orchestrator"
    assert "gemma_multimodal" in {
        tool["function"]["name"]
        for tool in data["orchestration"]["tools"]
    }


def test_orchestrator_plan_endpoint_returns_plain_product_result() -> None:
    client = TestClient(app)
    response = client.post(
        "/agents/orchestrator/plan",
        json={
            "request_type": "policy_qa",
            "payload": {"query": f"What is the leave policy? {uuid4()}"},
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["provider_call"] is False
    assert result["certification"]["is_valid"] is True
    assert result["audit"]["recorded"] is True
    assert result["plan"]["workflow"] == "policy_qa"
    assert result["a2a"]["certified"] is True
    assert result["a2a"]["source_agent"] == "orchestrator_agent"
    assert "payload" not in result["a2a"]
