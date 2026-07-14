"""Tests for the unified command-center operational snapshot."""

from fastapi.testclient import TestClient

from api.main import app


def test_ops_overview_is_provenance_labelled_and_coherent(monkeypatch) -> None:
    from core.runtime_settings import runtime_settings

    async def _skip_persisted_operator_settings():
        return runtime_settings.public()

    monkeypatch.setattr(runtime_settings, "load", _skip_persisted_operator_settings)
    client = TestClient(app)

    response = client.get("/ops/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["schema_version"] == "ops.v1"
    assert data["tenant_id"] == "demo"
    assert data["provenance"] in {"demo_runtime", "live_runtime"}
    assert isinstance(data["agents"], list)
    assert {"human_review", "cases", "resume"} <= set(data["queues"])
    assert data["queues"]["resume"]["state"] in {"clear", "active"}
    assert data["queues"]["resume"]["pending"] >= 0
    assert data["gates"]["auth_enforced"] is False
    assert data["slo"]["status"] == "not_measured"
