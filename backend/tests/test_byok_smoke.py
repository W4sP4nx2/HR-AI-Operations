"""No-network tests for the backend BYOK smoke harness."""

from __future__ import annotations

import pytest


def test_byok_smoke_success_without_key_echo(monkeypatch) -> None:
    import scripts.byok_smoke as smoke

    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    monkeypatch.setattr(smoke, "llm_provider", lambda: "fireworks")
    monkeypatch.setattr(smoke, "server_api_key", lambda: "secret-fireworks-key-1234567890")

    def fake_get(url: str, key: str, timeout: float):
        assert url == "http://backend.test/byok/verify"
        assert key == "secret-fireworks-key-1234567890"
        assert timeout == 1
        return {
            "success": True,
            "data": {
                "valid": True,
                "status": "verified",
                "provider": "fireworks",
                "detail": "key accepted by provider",
            },
        }

    monkeypatch.setattr(smoke, "_get_verify", fake_get)

    result = smoke.run_smoke(provider="fireworks", timeout=1)

    assert result["provider"] == "fireworks"
    assert result["status"] == "verified"
    assert result["key_echoed"] is False


def test_byok_smoke_rejects_amd_service_auth(monkeypatch) -> None:
    import scripts.byok_smoke as smoke

    monkeypatch.setattr(smoke, "llm_provider", lambda: "amd_vllm")
    with pytest.raises(RuntimeError, match="only for provider 'fireworks'"):
        smoke.run_smoke(provider="amd_vllm", timeout=1)  # type: ignore[arg-type]


def test_byok_smoke_rejects_local_provider_mismatch(monkeypatch) -> None:
    import scripts.byok_smoke as smoke

    monkeypatch.setattr(smoke, "llm_provider", lambda: "amd_vllm")

    with pytest.raises(RuntimeError, match="local LLM_PROVIDER"):
        smoke.run_smoke(provider="fireworks", timeout=1)


def test_byok_smoke_fails_if_backend_echoes_key(monkeypatch, capsys) -> None:
    import scripts.byok_smoke as smoke

    monkeypatch.setattr(smoke, "_expected_provider", lambda _provider: "fireworks")
    monkeypatch.setattr(smoke, "llm_provider", lambda: "fireworks")
    monkeypatch.setattr(smoke, "server_api_key", lambda: "secret-key-echo-1234567890")
    monkeypatch.setattr(
        smoke,
        "_get_verify",
        lambda *_args: {
            "data": {
                "status": "verified",
                "provider": "fireworks",
                "debug": "secret-key-echo-1234567890",
            }
        },
    )

    result = smoke.main(["--provider", "fireworks", "--json"])

    captured = capsys.readouterr().out
    assert result == 1
    assert "echoed the secret key" in captured
