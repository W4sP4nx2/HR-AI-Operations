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
