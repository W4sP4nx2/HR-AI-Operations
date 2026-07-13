"""No-network Fireworks Batch control-plane tests."""

from __future__ import annotations

import json

import httpx
import pytest

from scripts.fireworks_batch_job import monitor_batch_job
from services.fireworks_batch import (
    BatchConfig,
    FireworksBatchClient,
    batch_config_status,
    batch_status_view,
    normalize_batch_state,
)


@pytest.fixture
def batch_config() -> BatchConfig:
    return BatchConfig(
        api_key="fixture-fireworks-key-not-real",
        control_base_url="https://control.example.invalid/v1",
        account_id="tenant-123",
    )


@pytest.mark.asyncio
async def test_batch_dataset_upload_job_create_and_status(monkeypatch, batch_config):
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/batchInferenceJobs/job-1"):
            return httpx.Response(200, json={"state": "RUNNING"})
        return httpx.Response(200, json={"name": "created"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FireworksBatchClient(batch_config, http_client=http)
        await client.create_dataset("resume-input")
        await client.upload_jsonl("resume-input", b'{"custom_id":"1","body":{}}\n')
        await client.create_job(
            job_id="job-1",
            model_id="tenant/fast-8b",
            input_dataset_id="resume-input",
            output_dataset_id="resume-output",
            top_k=20,
        )
        status = await client.get_job("job-1")

    assert status == {"state": "RUNNING"}
    assert [request.method for request in requests] == ["POST", "POST", "POST", "GET"]
    assert requests[0].url.path.endswith("/accounts/tenant-123/datasets")
    assert requests[1].url.path.endswith("/datasets/resume-input:upload")
    create_body = json.loads(requests[2].content)
    assert create_body["model"] == "tenant/fast-8b"
    assert create_body["inputDatasetId"] == "accounts/tenant-123/datasets/resume-input"
    assert create_body["inferenceParameters"]["topK"] == 20
    assert requests[2].url.params["batchInferenceJobId"] == "job-1"
    assert all(
        request.headers["authorization"] == "Bearer fixture-fireworks-key-not-real"
        for request in requests
    )


@pytest.mark.asyncio
async def test_batch_rejects_unapproved_model_before_network(monkeypatch, batch_config):
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/approved-8b")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FireworksBatchClient(batch_config, http_client=http)
        with pytest.raises(ValueError, match="ALLOWED_MODELS"):
            await client.create_job(
                job_id="job-1",
                model_id="tenant/unapproved-70b",
                input_dataset_id="input",
                output_dataset_id="output",
            )
    assert calls == 0


def test_batch_configuration_status_is_secret_free(monkeypatch):
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    monkeypatch.delenv("FIREWORKS_CONTROL_BASE_URL", raising=False)
    monkeypatch.delenv("FIREWORKS_ACCOUNT_ID", raising=False)
    status = batch_config_status()
    assert status["ready"] is False
    assert status["issues"] == [
        "FIREWORKS_API_KEY",
        "FIREWORKS_CONTROL_BASE_URL",
        "FIREWORKS_ACCOUNT_ID",
    ]


def test_batch_configuration_status_handles_invalid_account(monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    monkeypatch.setenv("FIREWORKS_CONTROL_BASE_URL", "https://control.example.invalid/v1")
    monkeypatch.setenv("FIREWORKS_ACCOUNT_ID", "invalid/account")

    status = batch_config_status()

    assert status["ready"] is False
    assert status["issues"] == ["resource id may contain only letters, numbers, '-' and '_'"]


def test_batch_status_view_normalizes_pending_and_bounds_progress():
    status = batch_status_view(
        {
            "name": "accounts/private-account/batchInferenceJobs/job-1",
            "state": "JOB_STATE_PENDING",
            "status": {"message": "waiting for capacity"},
            "jobProgress": {
                "percent": 140,
                "totalInputRequests": 200,
                "totalProcessedRequests": 12,
                "failedRequests": 1,
            },
        }
    )
    assert normalize_batch_state("RUNNING") == "running"
    assert normalize_batch_state("JOB_STATE_VALIDATING") == "validating"
    assert status == {
        "status": "pending",
        "label": "Pending",
        "provider_state": "JOB_STATE_PENDING",
        "explanation": (
            "The job is queued for provider capacity. Interactive screening remains available."
        ),
        "provider_message": "waiting for capacity",
        "progress_percent": 100.0,
        "processed_requests": 12,
        "total_requests": 200,
        "failed_requests": 1,
        "terminal": False,
        "poll_after_seconds": 10,
    }
    assert "private-account" not in json.dumps(status)
    assert batch_status_view({"state": "JOB_STATE_COMPLETED"})["terminal"] is True
    assert batch_status_view({"state": "future_state"})["status"] == "unknown"


@pytest.mark.asyncio
async def test_monitor_reconciles_normalized_job_metadata(tmp_path, batch_config):
    from core.memory import Memory

    responses = iter(
        [
            {
                "state": "JOB_STATE_RUNNING",
                "outputDatasetId": "accounts/tenant/datasets/output-1",
                "jobProgress": {
                    "totalInputRequests": 10,
                    "totalProcessedRequests": 4,
                    "failedRequests": 0,
                },
            },
            {
                "state": "JOB_STATE_COMPLETED",
                "outputDatasetId": "accounts/tenant/datasets/output-1",
                "jobProgress": {
                    "totalInputRequests": 10,
                    "totalProcessedRequests": 10,
                    "failedRequests": 1,
                },
            },
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    store = Memory(f"sqlite:///{tmp_path / 'batch.db'}")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FireworksBatchClient(batch_config, http_client=http)
        result = await monitor_batch_job(
            client,
            job_id="job-1",
            interval=0,
            max_polls=2,
            store=store,
        )

    persisted = await store.get_batch_job("job-1")
    assert result["status"] == "completed"
    assert persisted["status"] == "completed"
    assert persisted["processed_requests"] == 10
    assert persisted["failed_requests"] == 1
    assert persisted["output_dataset_id"] == "output-1"


@pytest.mark.asyncio
async def test_batch_status_route_returns_the_normalized_contract(monkeypatch, batch_config):
    from api.routes import lifecycle

    class FakeBatchClient:
        def __init__(self, _config):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_job(self, job_id):
            assert job_id == "resume-demo-001"
            return {"state": "JOB_STATE_PENDING", "jobProgress": {"percent": 10}}

    monkeypatch.setattr(lifecycle.BatchConfig, "from_env", lambda: batch_config)
    monkeypatch.setattr(lifecycle, "FireworksBatchClient", FakeBatchClient)

    response = await lifecycle.fireworks_batch_status("resume-demo-001", {})

    assert response["success"] is True
    assert response["data"]["job_id"] == "resume-demo-001"
    assert response["data"]["status"] == "pending"
    assert response["data"]["progress_percent"] == 10.0
