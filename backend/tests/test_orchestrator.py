"""No-key tests for the Fireworks-aware A2A orchestrator."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.a2a_cards import AGENT_CARDS, cards_to_tools, get_card
from agents.orchestrator import (
    build_orchestration_plan,
    orchestrate,
    select_model_for_card,
)
from api.main import app


@pytest.fixture
def fireworks_allowlist(monkeypatch):
    models = [
        "accounts/fireworks/models/deepseek-v4-flash",
        "accounts/fireworks/models/kimi-k2p6",
        "accounts/fireworks/models/gemma-3-vision",
        "accounts/fireworks/models/deepseek-r1-distill-qwen-32b",
    ]
    monkeypatch.setenv("ALLOWED_MODELS", ",".join(models))
    return models


def test_cards_become_fireworks_tool_descriptions():
    tools = cards_to_tools()
    names = {tool["function"]["name"] for tool in tools}
    triage_tool = next(
        tool for tool in tools if tool["function"]["name"] == "dispatch_triage_agent"
    )

    assert len(tools) == len(AGENT_CARDS)
    assert "dispatch_policy_qa_agent" in names
    assert "Serving path: serverless_streaming" in triage_tool["function"]["description"]
    assert "Fireworks primitives: streaming, json_schema, tool_calling" in (
        triage_tool["function"]["description"]
    )


def test_model_selection_uses_only_allowed_models_and_family_hints(fireworks_allowlist):
    resume_card = get_card("resume_analysis")
    selected = select_model_for_card(resume_card)

    assert selected == "accounts/fireworks/models/gemma-3-vision"
    assert selected in fireworks_allowlist


def test_model_selection_requires_allowlist(monkeypatch):
    monkeypatch.delenv("ALLOWED_MODELS", raising=False)

    with pytest.raises(RuntimeError, match="ALLOWED_MODELS"):
        select_model_for_card(get_card("triage"))


def test_orchestration_plan_builds_streaming_contract(fireworks_allowlist):
    plan = build_orchestration_plan(
        "structured_classification",
        {"input": "Employee asks about dental benefits", "session_id": "demo-session"},
    )

    assert plan.selected_agent == "triage_agent"
    assert plan.selected_model in fireworks_allowlist
    assert plan.dispatch_mode == "stream"
    assert plan.request_contract["body"]["stream"] is True
    assert plan.request_contract["body"]["stream_options"] == {"include_usage": True}
    assert plan.request_contract["body"]["response_format"]["type"] == "json_schema"


def test_orchestration_plan_builds_reasoning_contract(fireworks_allowlist):
    plan = build_orchestration_plan(
        "attrition_explanation",
        {
            "prompt": "Explain a high attrition risk advisory.",
            "reasoning_effort": "low",
        },
    )

    assert plan.selected_agent == "attrition_agent"
    assert plan.selected_model in fireworks_allowlist
    assert plan.dispatch_mode == "reasoning"
    assert plan.request_contract["body"]["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_orchestrate_returns_certified_envelope(fireworks_allowlist):
    envelope = await orchestrate(
        "policy_qa",
        {"query": "What is our PTO rollover policy?"},
    )

    assert envelope.source_agent == "orchestrator_agent"
    assert envelope.target_agent == "policy_qa_agent"
    assert envelope.certification.is_valid
    assert envelope.payload["selected_model"] in fireworks_allowlist
    assert envelope.metadata["provider_call"] is False
    assert envelope.metadata["prefilter_skip"] is True


def test_lifecycle_manifest_surfaces_a2a_topology(fireworks_allowlist):
    client = TestClient(app)
    response = client.get("/lifecycle/fireworks")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["a2a_orchestration"]["cards"]["card_count"] == len(AGENT_CARDS)
    policy_card = data["a2a_orchestration"]["cards"]["cards"]["policy_qa_agent"]
    assert policy_card["serving_path"] == "serverless_online"
    assert policy_card["model_selection"] == "runtime ALLOWED_MODELS only"


def test_orchestrator_plan_endpoint_is_key_free(fireworks_allowlist):
    client = TestClient(app)
    response = client.post(
        "/agents/orchestrator/plan",
        json={
            "request_type": "resume_analysis",
            "payload": {
                "image_urls": ["data:image/png;base64,AAAA"],
                "prompt": "Extract this scanned resume.",
            },
        },
    )

    assert response.status_code == 200
    envelope = response.json()["data"]
    assert envelope["target_agent"] == "resume_screener_agent"
    assert envelope["payload"]["dispatch_mode"] == "vision"
    assert envelope["payload"]["selected_model"] in fireworks_allowlist
