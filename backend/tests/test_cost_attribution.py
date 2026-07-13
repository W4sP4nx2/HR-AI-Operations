"""Cost attribution dashboard and benchmark evidence."""

from __future__ import annotations

import pytest

from core.cost_attribution import (
    cost_attribution_snapshot,
    record_cost_event,
    reset_cost_attribution,
)


def test_cost_attribution_snapshot_tracks_tiers_cache_and_skips() -> None:
    reset_cost_attribution()

    record_cost_event(tier="economy", input_tokens=100, output_tokens=50)
    record_cost_event(tier="standard", input_tokens=200, output_tokens=80, cache_hit=True)
    record_cost_event(tier="premium", input_tokens=300, output_tokens=40, prefilter_skip=True)

    snapshot = cost_attribution_snapshot()

    assert snapshot["cost_attribution"]["economy"]["queries"] == 1
    assert snapshot["cost_attribution"]["economy"]["total_usd"] > 0
    assert snapshot["cost_attribution"]["standard"]["total_usd"] == 0
    assert snapshot["cost_attribution"]["premium"]["total_usd"] == 0
    assert snapshot["cache_hit_rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert snapshot["prefilter_skip_rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert snapshot["estimation"]["billing_export_connected"] is False


@pytest.mark.asyncio
async def test_certified_handoff_records_cost_attribution(monkeypatch) -> None:
    from core.a2a_envelope import certified_handoff

    reset_cost_attribution()
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b,tenant/deep-70b")

    await certified_handoff(
        source_agent="chat",
        target_agent="policy",
        func=lambda _payload: {"answer": "Use PTO policy.", "confidence": 0.9},
        payload={"query": "What is my vacation policy?"},
        objectives={
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["answer", "confidence"],
                "additionalProperties": False,
            },
            "require_pii_free": True,
        },
        cost_query="What is my vacation policy?",
        persist=False,
    )

    snapshot = cost_attribution_snapshot()
    assert snapshot["cost_attribution"]["economy"]["queries"] == 1
    assert snapshot["cost_attribution"]["economy"]["provider_calls"] == 1


def test_cost_control_ab_benchmark_passes_target() -> None:
    from scripts.benchmark_cost_controls import run_ab_benchmark

    result = run_ab_benchmark()

    assert result["passed"] is True
    assert result["cost_reduction"] >= result["target"]["cost_reduction_min"]
    assert result["quality_delta"] <= result["target"]["quality_loss_max"]
    assert result["controlled"]["provider_calls"] < result["uncontrolled"]["provider_calls"]


@pytest.mark.asyncio
async def test_inference_usage_endpoint_exposes_local_estimates(monkeypatch) -> None:
    from api.routes.metrics import get_inference_usage

    reset_cost_attribution()
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    record_cost_event(tier="economy", input_tokens=500, output_tokens=100)

    response = await get_inference_usage({})
    data = response["data"]

    assert data["source"] == "mixed_provenance"
    assert data["provider_observed"]["requests"] == 0
    assert data["totals"]["provider_calls"] == 1
    assert data["totals"]["input_tokens"] == 500
    assert data["totals"]["estimated_usd"] > 0
    assert data["cost_benchmark"]["passed"] is True
    assert data["cost_benchmark"]["cost_reduction"] > 0.4
    assert data["fireworks_serverless"]["billing_export_method"] == (
        "firectl billing export-metrics"
    )
    assert data["fireworks_serverless"]["billing_api_fetch_implemented"] is False
    assert data["fireworks_serverless"]["request_annotations"]["project"] == "hr-command-center"
    assert data["blended_cost_scenario"]["status"] == "illustrative_target_not_measured"
    assert data["blended_cost_scenario"]["blended_reduction"] == pytest.approx(0.335)


def test_provider_usage_is_separate_from_estimated_cost() -> None:
    from core.cost_attribution import provider_usage_snapshot, record_provider_usage

    reset_cost_attribution()
    record_provider_usage(
        model_id="accounts/example/models/test",
        prompt_tokens=100,
        cached_prompt_tokens=40,
        completion_tokens=20,
    )
    observed = provider_usage_snapshot()
    assert observed["requests"] == 1
    assert observed["prompt_tokens"] == 100
    assert observed["cached_prompt_tokens"] == 40
    assert observed["completion_tokens"] == 20
    assert observed["rated_cost_usd"] is None
