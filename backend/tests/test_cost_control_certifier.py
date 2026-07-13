"""No-network tests for the operator-facing cost-control certification command."""

from __future__ import annotations

import json


def test_cost_control_certification_passes_all_gates() -> None:
    from scripts.certify_cost_controls import run_certification

    result = run_certification()

    assert result["ok"] is True
    assert result["network_required"] is False
    assert result["provider_key_required"] is False
    assert result["passed_count"] == result["gate_count"]
    names = {gate["name"] for gate in result["gates"]}
    assert {
        "oversized_prompt_rejection",
        "prohibited_model_rejection",
        "pii_preflight_detection",
        "routing_accuracy",
        "cache_determinism",
        "cost_math_accuracy",
        "benchmark_isolation",
        "benchmark_reproducibility",
    } <= names


def test_cost_control_certification_cli_emits_json(capsys) -> None:
    from scripts.certify_cost_controls import main

    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["certification"] == "zero_spend_cost_controls"
    assert payload["ok"] is True
    assert payload["gate_count"] >= 8
