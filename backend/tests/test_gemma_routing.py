"""Gemma multimodal tests for the simplified single orchestrator."""

from __future__ import annotations

from uuid import uuid4

import pytest

from agents.orchestrator import build_orchestration_plan, orchestrate

GEMMA_MODEL = "tenant/models/gemma-4-26b-a4b-it"
TEXT_MODEL = "tenant/models/kimi-k2p6"


@pytest.fixture(autouse=True)
def gemma_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_MODELS", f"{TEXT_MODEL},{GEMMA_MODEL}")
    monkeypatch.setenv("FIREWORKS_GEMMA_MODEL", GEMMA_MODEL)


def test_image_resume_routes_directly_to_allowlisted_gemma() -> None:
    plan = build_orchestration_plan(
        "resume_analysis",
        {
            "image_urls": ["data:image/png;base64,AAAA"],
            "prompt": "Extract and assess this scanned resume.",
        },
    )

    assert plan.workflow == "resume_screening"
    assert plan.serving_path == "deploy_on_demand"
    assert plan.selected_model == GEMMA_MODEL
    assert plan.cost_tier == "premium"
    assert plan.cost_reason == "multimodal_resume_requires_gemma"
    assert plan.human_review_required is True
    assert plan.selected_tool == "gemma_multimodal"
    assert plan.target_agent == "resume_screener_agent"


def test_text_resume_does_not_use_multimodal_route() -> None:
    plan = build_orchestration_plan(
        "resume_analysis",
        {"prompt": "Assess this text-only resume."},
    )

    assert plan.workflow == "resume_screening"
    assert plan.serving_path == "standard"
    assert plan.selected_model == TEXT_MODEL


def test_image_route_fails_closed_without_allowlisted_gemma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_MODELS", TEXT_MODEL)

    with pytest.raises(RuntimeError, match="Gemma"):
        build_orchestration_plan(
            "resume_analysis",
            {
                "image_urls": ["data:image/png;base64,AAAA"],
                "prompt": "Assess this scanned resume.",
            },
        )


@pytest.mark.asyncio
async def test_gemma_plan_is_plain_certified_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_record_action(**kwargs):
        return {"id": "audit-gemma"}

    monkeypatch.setattr("agents.orchestrator.record_action", fake_record_action)
    result = await orchestrate(
        "resume_analysis",
        {
            "image_urls": ["data:image/png;base64,AAAA"],
            "prompt": f"Assess this scanned resume {uuid4()}.",
        },
    )

    assert result.certification.is_valid is True
    assert result.audit.event_id == "audit-gemma"
    assert result.plan.selected_model == GEMMA_MODEL
    assert result.plan.serving_path == "deploy_on_demand"
    assert result.provider_call is False
    assert result.a2a.certified is True
    assert result.a2a.selected_tool == "gemma_multimodal"
    assert result.a2a.target_agent == "resume_screener_agent"
