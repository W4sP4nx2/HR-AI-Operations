"""Durable large-resume admission and state-transition tests."""

import asyncio
import json
import uuid

from fastapi.testclient import TestClient

from api.main import app


def test_resume_job_is_idempotent_and_cancellable(monkeypatch) -> None:
    from core.runtime_settings import runtime_settings

    async def _skip_persisted_operator_settings():
        return runtime_settings.public()

    monkeypatch.setattr(runtime_settings, "load", _skip_persisted_operator_settings)
    client = TestClient(app)
    body = {
        "filename": "candidate.pdf",
        "source_object_key": "local://candidate.pdf",
        "size_bytes": 1_024,
        "pages_total": 4,
    }
    headers = {"Idempotency-Key": "candidate-001"}

    created = client.post("/resume-jobs", json=body, headers=headers)
    assert created.status_code == 202
    first = created.json()["data"]
    assert first["state"] == "queued"
    assert first["deduplicated"] is False

    duplicate = client.post("/resume-jobs", json=body, headers=headers)
    assert duplicate.status_code == 202
    second = duplicate.json()["data"]
    assert second["job_id"] == first["job_id"]
    assert second["deduplicated"] is True

    fetched = client.get(f"/resume-jobs/{first['job_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["tenant_id"] == "demo"

    cancelled = client.post(f"/resume-jobs/{first['job_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["state"] == "cancelled"

    retried = client.post(f"/resume-jobs/{first['job_id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["data"]["state"] == "queued"
    assert retried.json()["data"]["attempt"] == 1


def test_production_rejects_local_object_keys(monkeypatch) -> None:
    from core.config import settings
    from core.runtime_settings import runtime_settings

    async def _skip_persisted_operator_settings():
        return runtime_settings.public()

    monkeypatch.setattr(runtime_settings, "load", _skip_persisted_operator_settings)
    monkeypatch.setattr(settings, "environment", "production")
    client = TestClient(app)
    response = client.post(
        "/resume-jobs",
        json={
            "filename": "candidate.pdf",
            "source_object_key": "local://candidate.pdf",
            "size_bytes": 1024,
            "pages_total": 1,
        },
        headers={"Idempotency-Key": "production-local-1"},
    )
    assert response.status_code == 400


def test_worker_processes_large_text_without_silent_truncation() -> None:
    from core.memory import memory
    from services.resume_job_worker import ResumeJobWorker

    async def run() -> None:
        job, deduplicated = await memory.create_resume_job(
            tenant_id="worker-tenant",
            created_by="manager-1",
            idempotency_key=f"worker-{uuid.uuid4().hex}",
            filename="large-resume.txt",
            source_object_key="local://large-resume.txt",
            size_bytes=150_000,
            pages_total=1,
            trace_id="trace-worker-test",
        )
        assert deduplicated is False
        content = ("Python Kubernetes evidence. " * 5_500).encode("utf-8")
        result = await ResumeJobWorker(memory).process_bytes(
            job["id"], "worker-tenant", content, "large-resume.txt"
        )
        assert result is not None
        assert result["state"] == "certified"
        assert result["coverage"] == 1.0
        parsed = json.loads(result["result_json"])
        assert parsed["scoring"] == "not_run"
        assert parsed["source"]["chars"] > 20_000
        assert parsed["chunk_count"] > 1

    asyncio.run(run())
