"""Tests for the no-network Dynamic Capability evidence package."""

from __future__ import annotations

import json


def test_capability_evidence_package_is_no_secret_and_gated(monkeypatch) -> None:
    from scripts.generate_capability_evidence import build_package

    monkeypatch.setenv("FIREWORKS_API_KEY", "fw-secret-value-1234567890")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "accounts/fireworks/models/gemma-3-27b-it")
    monkeypatch.delenv("AMD_RUNTIME_EVIDENCE_FILE", raising=False)

    package = build_package()
    serialized = json.dumps(package)

    assert package["schema"] == "hrcc.capability_evidence.v1"
    assert package["cost_controls"]["ok"] is True
    assert package["claim_boundary"]["no_provider_calls"] is True
    assert package["claim_boundary"]["no_secret_values"] is True
    assert package["claim_boundary"]["live_amd_gemma_claim"] == "live_gated"
    assert "fw-secret-value" not in serialized
    assert package["environment"]["env_presence"]["FIREWORKS_API_KEY"] == "set"
    assert len(package["package_sha256"]) == 64


def test_capability_evidence_cli_writes_json(tmp_path, capsys, monkeypatch) -> None:
    from scripts.generate_capability_evidence import main

    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    output = tmp_path / "capability-evidence.json"

    assert main(["--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    stdout = capsys.readouterr().out

    assert payload["schema"] == "hrcc.capability_evidence.v1"
    assert payload["cost_controls"]["passed_count"] == payload["cost_controls"]["gate_count"]
    assert "Wrote capability evidence" in stdout
    assert "cost_controls_ok=True" in stdout
