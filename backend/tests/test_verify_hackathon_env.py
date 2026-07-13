"""No-network tests for hackathon environment profile verification."""

from __future__ import annotations

import json


def _clear_env(monkeypatch) -> None:
    for name in (
        "LLM_PROVIDER",
        "FIREWORKS_API_KEY",
        "FIREWORKS_BASE_URL",
        "AMD_VLLM_API_KEY",
        "AMD_VLLM_BASE_URL",
        "AMD_VLLM_MODEL",
        "AMD_VLLM_SERVED_MODEL",
        "HF_TOKEN",
        "ALLOWED_MODELS",
        "FIREWORKS_ALLOWED_MODELS",
        "AMD_VLLM_ALLOWED_MODELS",
        "AUTH_ENFORCE",
        "AUTH_OPEN_REGISTRATION",
        "JWT_SECRET",
        "ADMIN_EMAIL",
        "ADMIN_PASSWORD",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_fireworks_auth_profile_passes_with_official_quickstart_shape(
    monkeypatch,
) -> None:
    import scripts.verify_hackathon_env as verifier

    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key-test-key")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "accounts/fireworks/models/kimi-k2p6")

    checks = verifier.fireworks_auth_checks()

    assert all(check.ok for check in checks)
    assert {check.name for check in checks} == {
        "LLM_PROVIDER=fireworks",
        "FIREWORKS_API_KEY present",
        "FIREWORKS_BASE_URL official OpenAI-compatible endpoint",
        "ALLOWED_MODELS injected",
        "ALLOWED_MODELS use Fireworks account model paths",
    }


def test_fireworks_auth_profile_rejects_non_official_base_url(monkeypatch) -> None:
    import scripts.verify_hackathon_env as verifier

    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key-test-key")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "accounts/fireworks/models/kimi-k2p6")

    checks = {check.name: check for check in verifier.fireworks_auth_checks()}

    assert not checks["FIREWORKS_BASE_URL official OpenAI-compatible endpoint"].ok
    assert (
        "https://api.fireworks.ai/inference/v1"
        in checks["FIREWORKS_BASE_URL official OpenAI-compatible endpoint"].detail
    )


def test_amd_gemma_profile_requires_served_model_in_allowlist(monkeypatch) -> None:
    import scripts.verify_hackathon_env as verifier

    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "amd_vllm")
    monkeypatch.setenv("AMD_VLLM_API_KEY", "test-key-test-key")
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://amd-vllm:8000/v1")
    monkeypatch.setenv("AMD_VLLM_MODEL", "google/gemma-3-27b-it")
    monkeypatch.setenv("AMD_VLLM_SERVED_MODEL", "amd-gemma-3-27b-it")
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/qwen-32b")

    checks = {check.name: check for check in verifier.amd_gemma_checks()}

    assert checks["AMD_VLLM_MODEL points to Gemma"].ok
    assert checks["AMD_VLLM_SERVED_MODEL points to Gemma"].ok
    assert not checks["ALLOWED_MODELS contains served Gemma name"].ok


def test_amd_gemma_profile_rejects_gamma_typo_in_model_ids(monkeypatch) -> None:
    import scripts.verify_hackathon_env as verifier

    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "amd_vllm")
    monkeypatch.setenv("AMD_VLLM_API_KEY", "test-key-test-key")
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://amd-vllm:8000/v1")
    monkeypatch.setenv("AMD_VLLM_MODEL", "google/gamma-3-27b-it")
    monkeypatch.setenv("AMD_VLLM_SERVED_MODEL", "amd-gamma-3-27b-it")
    monkeypatch.setenv("ALLOWED_MODELS", "amd-gamma-3-27b-it")

    checks = {check.name: check for check in verifier.amd_gemma_checks()}

    assert not checks["AMD_VLLM_MODEL points to Gemma"].ok
    assert not checks["AMD_VLLM_SERVED_MODEL points to Gemma"].ok


def test_amd_deployment_auth_checks_require_closed_production_posture(monkeypatch) -> None:
    import scripts.verify_hackathon_env as verifier

    _clear_env(monkeypatch)
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    monkeypatch.setenv("AUTH_OPEN_REGISTRATION", "false")
    monkeypatch.setenv("JWT_SECRET", "fixture-random-jwt-secret-1234567890")
    monkeypatch.setenv("ADMIN_EMAIL", "judge-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "fixture-admin-password-1234567890")
    monkeypatch.setenv("DATABASE_URL", "postgresql://hr:secret@db:5432/hrdb")

    assert all(check.ok for check in verifier.amd_deployment_auth_checks())


def test_both_mode_validates_both_profiles_without_impossible_provider_pair(
    monkeypatch,
) -> None:
    import scripts.verify_hackathon_env as verifier

    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "amd_vllm")
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key-test-key")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
    monkeypatch.setenv("AMD_VLLM_API_KEY", "test-key-test-key")
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://amd-vllm:8000/v1")
    monkeypatch.setenv("AMD_VLLM_MODEL", "google/gemma-3-27b-it")
    monkeypatch.setenv("AMD_VLLM_SERVED_MODEL", "amd-gemma-3-27b-it")
    monkeypatch.setenv("FIREWORKS_ALLOWED_MODELS", "accounts/fireworks/models/kimi-k2p6")
    monkeypatch.setenv("AMD_VLLM_ALLOWED_MODELS", "amd-gemma-3-27b-it")
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    monkeypatch.setenv("AUTH_OPEN_REGISTRATION", "false")
    monkeypatch.setenv("JWT_SECRET", "fixture-random-jwt-secret-1234567890")
    monkeypatch.setenv("ADMIN_EMAIL", "judge-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "fixture-admin-password-1234567890")
    monkeypatch.setenv("DATABASE_URL", "postgresql://hr:secret@db:5432/hrdb")

    checks = verifier.checks_for_mode("both")

    assert all(check.ok for check in checks)
    assert not any(check.name == "LLM_PROVIDER=fireworks" for check in checks)
    assert not any(check.name == "LLM_PROVIDER=amd_vllm" for check in checks)


def test_main_json_reports_failed_profile_without_secrets(monkeypatch, capsys) -> None:
    import scripts.verify_hackathon_env as verifier

    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "short")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "accounts/fireworks/models/qwen")

    result = verifier.main(["--mode", "fireworks-auth", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert payload["ok"] is False
    assert "short" not in str(payload)


def test_fireworks_auth_rejects_non_fireworks_model_path(monkeypatch) -> None:
    import scripts.verify_hackathon_env as verifier

    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key-test-key")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "google/gemma-3-27b-it")

    checks = {check.name: check for check in verifier.fireworks_auth_checks()}

    assert not checks["ALLOWED_MODELS use Fireworks account model paths"].ok
