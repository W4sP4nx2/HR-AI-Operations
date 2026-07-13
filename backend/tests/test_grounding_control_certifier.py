"""No-network tests for the grounding-control certification command."""

from __future__ import annotations

import json


def test_grounding_control_certification_passes_all_gates() -> None:
    from scripts.certify_grounding_controls import run_certification

    result = run_certification()

    assert result["ok"] is True
    assert result["network_required"] is False
    assert result["provider_key_required"] is False
    assert result["passed_count"] == result["gate_count"]
    names = {gate["name"] for gate in result["gates"]}
    assert {
        "no_context_refusal",
        "grounded_excerpt_fallback",
        "citation_validation",
        "empty_retrieval_needs_review",
        "prompt_injection_detection",
    } <= names


def test_grounding_control_certification_cli_emits_json(capsys) -> None:
    from scripts.certify_grounding_controls import main

    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["certification"] == "grounding_controls"
    assert payload["ok"] is True
    assert payload["gate_count"] >= 5
