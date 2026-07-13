"""Contract tests for persisted AI controls and secret handling."""

from __future__ import annotations

import asyncio


def test_encrypted_key_persistence_and_masked_public_view(tmp_path, monkeypatch) -> None:
    """Provider keys round-trip through the DB without appearing in payloads."""
    import core.runtime_settings as runtime_module
    from core.memory import Memory
    from core.runtime_settings import RuntimeSettings

    database = Memory(f"sqlite:///{tmp_path / 'settings.db'}")
    monkeypatch.setattr(runtime_module, "memory", database)
    local = RuntimeSettings()

    async def scenario() -> None:
        await local.load()
        await local.save(
            {
                "provider": "fireworks",
                "selected_model": "tenant/fast-8b",
                "temperature": 0.55,
                "max_tokens": 768,
            },
            api_key="fw-secret-value-123456",
        )
        row = await database.get_runtime_settings()
        assert row is not None
        assert "fw-secret-value-123456" not in row["payload"]
        assert "fw-secret-value-123456" not in row["encrypted_api_keys"]

        restored = RuntimeSettings()
        await restored.load()
        public = restored.public()
        assert restored.api_key_for("fireworks") == "fw-secret-value-123456"
        assert public["api_keys"]["fireworks"]["configured"] is True
        assert public["api_keys"]["fireworks"]["masked"] == "••••3456"
        assert "fw-secret-value-123456" not in str(public)

    asyncio.run(scenario())


def test_runtime_controls_change_model_and_parameters(monkeypatch) -> None:
    """A saved snapshot changes routing parameters consumed by inference code."""
    import core.genai_lifecycle as lifecycle
    import core.llm_factory as factory
    import core.runtime_key as runtime_key
    import core.runtime_settings as runtime_module
    from core.runtime_settings import RuntimeSettings

    local = RuntimeSettings()
    local._values.update(
        {
            "provider": "fireworks",
            "selected_model": "tenant/fast-8b",
            "temperature": 0.65,
            "max_tokens": 512,
            "reasoning_effort": 0.9,
        }
    )
    local._active = True
    local._loaded = True
    monkeypatch.setattr(runtime_module, "runtime_settings", local)
    monkeypatch.setattr(runtime_key, "runtime_settings", local)
    monkeypatch.setattr(factory, "runtime_settings", local)

    parameters = lifecycle.controlled_parameters("chat", max_tokens=900, temperature=0.0)
    assert parameters["max_tokens"] == 512
    assert parameters["temperature"] == 0.3
    assert parameters["reasoning_effort"] == "high"
    assert (
        factory.pick_model_for_role("triage", ["tenant/fast-8b", "tenant/deep-70b"])
        == "tenant/fast-8b"
    )
    assert runtime_key.llm_provider() == "fireworks"


def test_stale_selected_model_is_cleared_when_allowlist_exists(monkeypatch) -> None:
    """Saved UI model choices cannot route to IDs removed from ALLOWED_MODELS."""
    from core.runtime_settings import RuntimeSettings

    monkeypatch.setenv("ALLOWED_MODELS", "accounts/fireworks/models/deepseek-v3p1")
    local = RuntimeSettings()
    local._values["selected_model"] = "accounts/fireworks/models/llama-v3p1-8b-instruct"

    local._discard_unconfigured_selected_model()

    assert local.selected_model() == ""


def test_settings_routes_return_envelopes_and_connection_latency(monkeypatch, tmp_path) -> None:
    """Settings endpoints persist controls and expose a measured local probe."""
    import core.runtime_settings as runtime_module
    from api.routes import settings as settings_route
    from api.routes.settings import RuntimeSettingsUpdate
    from core.memory import Memory
    from core.runtime_settings import RuntimeSettings

    database = Memory(f"sqlite:///{tmp_path / 'route-settings.db'}")
    local = RuntimeSettings()
    monkeypatch.setattr(runtime_module, "memory", database)
    monkeypatch.setattr(settings_route, "runtime_settings", local)

    async def scenario() -> None:
        response = await settings_route.update_settings(
            RuntimeSettingsUpdate(
                provider="deterministic",
                temperature=0.4,
                max_tokens=640,
                caching_enabled=False,
            ),
            {},
        )
        assert response["success"] is True
        assert response["data"]["temperature"] == 0.4
        assert response["data"]["max_tokens"] == 640
        assert response["data"]["api_keys"]["fireworks"]["configured"] is False

        probe = await settings_route.test_connection(
            settings_route.ConnectionTestRequest(provider="deterministic"),
            {},
        )
        assert probe["success"] is True
        assert probe["data"]["valid"] is True
        assert probe["data"]["latency_ms"] >= 0

    asyncio.run(scenario())
