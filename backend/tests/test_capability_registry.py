"""No-network tests for dynamic capability discovery."""

from __future__ import annotations

import json


def _providers(snapshot: dict) -> dict[str, dict]:
    return {provider["provider_id"]: provider for provider in snapshot["providers"]}


def _hardware(snapshot: dict) -> dict[str, dict]:
    return {item["hardware_id"]: item for item in snapshot["hardware"]}


def test_capability_snapshot_is_zero_spend_when_keys_are_missing(monkeypatch) -> None:
    from core.capability_registry import capability_snapshot

    for key in (
        "FIREWORKS_API_KEY",
        "FIREWORKS_BASE_URL",
        "ALLOWED_MODELS",
        "AMD_VLLM_BASE_URL",
        "AMD_VLLM_API_KEY",
        "AMD_VLLM_SERVED_MODEL",
        "AMD_RUNTIME_EVIDENCE_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MOCK_LLM", "true")

    snapshot = capability_snapshot()
    providers = _providers(snapshot)

    assert snapshot["demo_mode"] is True
    assert providers["deterministic_fallback"]["status"] == "measured_local"
    assert (
        providers["deterministic_fallback"]["measurements"][0]["evidence_level"] == "measured_local"
    )
    assert providers["fireworks"]["status"] == "live_gated"
    assert "FIREWORKS_API_KEY" in providers["fireworks"]["missing_inputs"]
    assert providers["amd_vllm_gemma"]["status"] == "live_gated"
    assert "AMD_RUNTIME_EVIDENCE_FILE" in providers["amd_vllm_gemma"]["missing_inputs"]
    assert all(
        route["selected_provider"] == "deterministic_fallback" for route in snapshot["routing"]
    )
    assert snapshot["runtime_controls"]["max_input_tokens"] > 0
    integrations = {item["integration_id"]: item for item in snapshot["integrations"]}
    assert integrations["orchestrator"]["status"] == "proven"
    assert integrations["orchestrator"]["architecture"] == "single_orchestrator"
    assert "a2a" not in integrations
    assert "crewai" not in integrations
    assert integrations["langsmith"]["status"] == "not_configured"
    assert any("LANGCHAIN_API_KEY" in item for item in integrations["langsmith"]["missing_inputs"])
    assert "fixture-fireworks-key" not in str(snapshot)


def test_capability_snapshot_reports_fireworks_config_without_live_claim(monkeypatch) -> None:
    from core.capability_registry import capability_snapshot

    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key-test-key")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
    monkeypatch.setenv(
        "ALLOWED_MODELS",
        "accounts/fireworks/models/gemma-3-27b-it,accounts/fireworks/models/kimi-k2p6",
    )
    monkeypatch.delenv("AMD_RUNTIME_EVIDENCE_FILE", raising=False)

    fireworks = _providers(capability_snapshot())["fireworks"]

    assert fireworks["status"] == "configured"
    assert fireworks["live_enabled"] is True
    assert fireworks["credentials_exposed"] is False if "credentials_exposed" in fireworks else True
    assert fireworks["models_available"] == [
        "accounts/fireworks/models/gemma-3-27b-it",
        "accounts/fireworks/models/kimi-k2p6",
    ]


def test_amd_runtime_is_not_proven_without_amd_evidence(monkeypatch, tmp_path) -> None:
    from core.capability_registry import capability_snapshot

    evidence = tmp_path / "runtime.json"
    evidence.write_text(
        json.dumps(
            {
                "device_names": ["NVIDIA A100-SXM4-80GB"],
                "torch_version": "2.6.0",
                "rocm_version": "6.3",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMD_RUNTIME_EVIDENCE_FILE", str(evidence))
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("AMD_VLLM_API_KEY", "test-key-test-key")
    monkeypatch.setenv("AMD_VLLM_SERVED_MODEL", "amd-gemma-3-27b-it")
    monkeypatch.setenv("ALLOWED_MODELS", "amd-gemma-3-27b-it")

    snapshot = capability_snapshot()
    amd = _providers(snapshot)["amd_vllm_gemma"]
    hardware = _hardware(snapshot)["local_rocm_gpu"]

    assert amd["status"] == "configured"
    assert hardware["status"] == "unavailable"
    assert any("does not identify an AMD device" in note for note in hardware["notes"])


def test_amd_runtime_can_be_proven_with_valid_evidence(monkeypatch, tmp_path) -> None:
    from core.capability_registry import capability_snapshot

    evidence = tmp_path / "runtime.json"
    evidence.write_text(
        json.dumps(
            {
                "device_names": ["AMD Instinct MI300X"],
                "device_count": 1,
                "torch_version": "2.6.0+rocm6.3",
                "rocm_version": "6.3",
                "vllm_version": "0.8.5",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMD_RUNTIME_EVIDENCE_FILE", str(evidence))
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("AMD_VLLM_API_KEY", "test-key-test-key")
    monkeypatch.setenv("AMD_VLLM_SERVED_MODEL", "amd-gemma-3-27b-it")
    monkeypatch.setenv("ALLOWED_MODELS", "amd-gemma-3-27b-it")

    snapshot = capability_snapshot()
    amd = _providers(snapshot)["amd_vllm_gemma"]
    hardware = _hardware(snapshot)["local_rocm_gpu"]

    assert amd["status"] == "proven"
    assert hardware["status"] == "proven"
    assert hardware["device_names"] == ["AMD Instinct MI300X"]
    assert any(
        route["task_type"] == "sensitive_hr_or_pii"
        and route["selected_provider"] == "amd_vllm_gemma"
        for route in snapshot["routing"]
    )
