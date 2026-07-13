"""No-network tests for the AMD/vLLM Gemma smoke harness."""

from __future__ import annotations

import pytest


def test_amd_vllm_smoke_success(monkeypatch) -> None:
    import scripts.amd_vllm_smoke as smoke

    monkeypatch.setattr(smoke, "llm_provider", lambda: "amd_vllm")
    monkeypatch.setattr(smoke, "llm_config_issues", lambda: [])
    monkeypatch.setattr(smoke, "server_api_key", lambda: "internal-key-1234567890")
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://amd-vllm:8000/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "amd-gemma-3-27b-it")

    def fake_get(url, *, headers, timeout):
        assert headers["Authorization"].startswith("Bearer ")
        assert timeout == 1
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/v1/models"):
            return {"data": [{"id": "amd-gemma-3-27b-it"}]}
        raise AssertionError(url)

    def fake_post(url, *, headers, payload, timeout):
        assert headers["Authorization"].startswith("Bearer ")
        assert timeout == 1
        assert url.endswith("/v1/chat/completions")
        assert payload["model"] == "amd-gemma-3-27b-it"
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr(smoke, "_get_json", fake_get)
    monkeypatch.setattr(smoke, "_post_json", fake_post)

    result = smoke.run_smoke(timeout=1)

    assert result["provider"] == "amd_vllm"
    assert result["model"] == "amd-gemma-3-27b-it"
    assert result["base_url_path"] == "/v1"
    assert result["chat_smoke"] == "ok"


def test_amd_vllm_smoke_requires_gemma_allowed_model(monkeypatch, capsys) -> None:
    import scripts.amd_vllm_smoke as smoke

    monkeypatch.setattr(smoke, "llm_provider", lambda: "amd_vllm")
    monkeypatch.setattr(smoke, "llm_config_issues", lambda: [])
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://amd-vllm:8000/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/qwen-32b")

    result = smoke.main(["--json"])

    captured = capsys.readouterr().out
    assert result == 1
    assert "Gemma/Gamma-family" in captured


def test_amd_vllm_smoke_requires_served_model_to_match(monkeypatch) -> None:
    import scripts.amd_vllm_smoke as smoke

    monkeypatch.setattr(smoke, "llm_provider", lambda: "amd_vllm")
    monkeypatch.setattr(smoke, "llm_config_issues", lambda: [])
    monkeypatch.setattr(smoke, "server_api_key", lambda: "internal-key-1234567890")
    monkeypatch.setenv("AMD_VLLM_BASE_URL", "http://amd-vllm:8000/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "amd-gemma-3-27b-it")

    def fake_get(url, *, headers, timeout):
        assert headers["Authorization"].startswith("Bearer ")
        assert timeout == 1
        if url.endswith("/health"):
            return {"status": "ok"}
        return {"data": [{"id": "not-the-gemma-model"}]}

    monkeypatch.setattr(smoke, "_get_json", fake_get)

    with pytest.raises(RuntimeError, match="not returned"):
        smoke.run_smoke(timeout=1)
