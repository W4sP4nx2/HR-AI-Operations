"""Coverage for non-secret live chat telemetry."""

from __future__ import annotations


def test_stream_usage_records_provider_and_governed_cost(monkeypatch) -> None:
    from api.routes.chat import _record_stream_usage
    from core.cost_router import CostRoute, CostRouter

    provider_calls: list[dict[str, int | str]] = []
    cost_calls: list[dict[str, int | str | bool]] = []
    monkeypatch.setattr(
        "core.cost_attribution.record_provider_usage",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    monkeypatch.setattr(
        "core.cost_attribution.record_cost_event",
        lambda **kwargs: cost_calls.append(kwargs),
    )
    monkeypatch.setattr(
        CostRouter,
        "classify",
        lambda _query: CostRoute("economy", "model", "test"),
    )

    class Usage:
        input_tokens = 17
        output_tokens = 9
        cache_read_tokens = 4

    class Stream:
        usage = Usage()

    class Model:
        model_name = "accounts/fireworks/models/kimi-k2p6"

    class Agent:
        model = Model()

    assert _record_stream_usage(Stream(), Agent(), "How much leave?") == Model.model_name
    assert provider_calls == [
        {
            "model_id": Model.model_name,
            "prompt_tokens": 17,
            "completion_tokens": 9,
            "cached_prompt_tokens": 4,
        }
    ]
    assert cost_calls == [
        {
            "tier": "economy",
            "input_tokens": 17,
            "output_tokens": 9,
            "provider_call": True,
        }
    ]
