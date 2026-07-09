"""Fireworks Batch control-plane client with injected endpoints and credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

import httpx

from core.config import settings
from core.fireworks import validate_model

BatchStatus = Literal[
    "validating",
    "pending",
    "running",
    "completed",
    "failed",
    "expired",
    "cancelled",
    "unknown",
]

_STATE_MAP: dict[str, BatchStatus] = {
    "CREATING": "validating",
    "CREATING_INPUT_DATASET": "validating",
    "VALIDATING": "validating",
    "PENDING": "pending",
    "RE_QUEUEING": "pending",
    "IDLE": "pending",
    "PAUSED": "pending",
    "RUNNING": "running",
    "WRITING_RESULTS": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "EXPIRED": "expired",
    "CANCELLED": "cancelled",
    "CANCELLING": "cancelled",
    "DELETED": "cancelled",
    "DELETING": "cancelled",
    "DELETING_CLEANING_UP": "cancelled",
    "EARLY_STOPPED": "cancelled",
}

_STATUS_COPY: dict[BatchStatus, tuple[str, str]] = {
    "validating": (
        "Validating",
        "Fireworks is checking the JSONL dataset before it enters the compute queue.",
    ),
    "pending": (
        "Pending",
        "The job is queued for provider capacity. Interactive screening remains available.",
    ),
    "running": ("Running", "Fireworks is processing records asynchronously."),
    "completed": ("Completed", "Results and error rows are ready for separate review."),
    "failed": ("Failed", "The provider rejected or could not complete the job."),
    "expired": (
        "Expired",
        "The provider time limit elapsed; completed rows remain usable.",
    ),
    "cancelled": ("Cancelled", "The job stopped before completion."),
    "unknown": ("Unknown", "The provider returned an unrecognized batch state."),
}


@dataclass(frozen=True)
class BatchConfig:
    """Validated Fireworks Batch configuration."""

    api_key: str
    control_base_url: str
    account_id: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls, api_key: str | None = None) -> BatchConfig:
        """Load Batch configuration without returning secret values in errors."""
        key = (api_key or os.environ.get("FIREWORKS_API_KEY", settings.fireworks_api_key)).strip()
        base_url = os.environ.get(
            "FIREWORKS_CONTROL_BASE_URL",
            settings.fireworks_control_base_url,
        ).rstrip("/")
        account_id = os.environ.get(
            "FIREWORKS_ACCOUNT_ID",
            settings.fireworks_account_id,
        ).strip()
        issues = []
        if not key:
            issues.append("FIREWORKS_API_KEY")
        if not base_url:
            issues.append("FIREWORKS_CONTROL_BASE_URL")
        if not account_id:
            issues.append("FIREWORKS_ACCOUNT_ID")
        if issues:
            raise RuntimeError(f"missing Fireworks Batch configuration: {', '.join(issues)}")
        parsed_base = httpx.URL(base_url)
        if parsed_base.scheme != "https" or not parsed_base.host:
            raise RuntimeError("FIREWORKS_CONTROL_BASE_URL must be an HTTPS URL")
        return cls(
            api_key=key,
            control_base_url=base_url,
            account_id=_resource_id(account_id),
            timeout_seconds=max(1.0, settings.fireworks_batch_timeout_seconds),
        )

    @property
    def account_path(self) -> str:
        return f"{self.control_base_url}/accounts/{quote(self.account_id, safe='')}"

    def resource_name(self, kind: str, resource_id: str) -> str:
        if kind not in {"datasets", "batchInferenceJobs"}:
            raise ValueError("unsupported Fireworks resource kind")
        return f"accounts/{self.account_id}/{kind}/{resource_id}"


class FireworksBatchClient:
    """Minimal async client for dataset upload, job creation, and status."""

    def __init__(
        self,
        config: BatchConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=config.timeout_seconds,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    async def __aenter__(self) -> FireworksBatchClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def create_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Create a user-uploaded dataset entry."""
        resource_id = _resource_id(dataset_id)
        response = await self._client.post(
            f"{self.config.account_path}/datasets",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json={
                "datasetId": resource_id,
                "dataset": {"userUploaded": {}},
            },
        )
        response.raise_for_status()
        return _json_object(response)

    async def upload_jsonl(
        self,
        dataset_id: str,
        payload: bytes,
        *,
        filename: str = "batch-input.jsonl",
    ) -> dict[str, Any]:
        """Upload a prepared JSONL payload to an existing dataset."""
        resource_id = _resource_id(dataset_id)
        if not payload.strip():
            raise ValueError("batch JSONL payload is empty")
        response = await self._client.post(
            f"{self.config.account_path}/datasets/{quote(resource_id, safe='')}:upload",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            files={"file": (filename, payload, "application/jsonl")},
        )
        response.raise_for_status()
        return _json_object(response)

    async def create_job(
        self,
        *,
        job_id: str,
        model_id: str,
        input_dataset_id: str,
        output_dataset_id: str,
        max_tokens: int = 800,
        temperature: float = 0.0,
        top_k: int | None = None,
        top_p: float | None = None,
    ) -> dict[str, Any]:
        """Create a Batch inference job over an uploaded dataset."""
        validate_model(model_id)
        inference = _sampling_parameters(
            max_tokens=max_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
        )
        job = _resource_id(job_id)
        input_id = _resource_id(input_dataset_id)
        output_id = _resource_id(output_dataset_id)
        response = await self._client.post(
            f"{self.config.account_path}/batchInferenceJobs",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            params={"batchInferenceJobId": job},
            json={
                "model": model_id,
                "inputDatasetId": self.config.resource_name("datasets", input_id),
                "outputDatasetId": self.config.resource_name("datasets", output_id),
                "inferenceParameters": inference,
            },
        )
        response.raise_for_status()
        return _json_object(response)

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Return the provider's current state for one Batch job."""
        job = _resource_id(job_id)
        response = await self._client.get(
            f"{self.config.account_path}/batchInferenceJobs/{quote(job, safe='')}",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
        )
        response.raise_for_status()
        return _json_object(response)


def batch_config_status() -> dict[str, Any]:
    """Return Batch readiness without exposing credentials or account values."""
    try:
        BatchConfig.from_env()
    except RuntimeError as exc:
        return {
            "ready": False,
            "issues": str(exc).removeprefix("missing Fireworks Batch configuration: ").split(", "),
        }
    except ValueError as exc:
        return {"ready": False, "issues": [str(exc)]}
    return {"ready": True, "issues": []}


def normalize_batch_state(provider_state: str | None) -> BatchStatus:
    """Map Fireworks job states to a stable product vocabulary."""
    normalized = (provider_state or "").strip().upper()
    if normalized.startswith("JOB_STATE_"):
        normalized = normalized.removeprefix("JOB_STATE_")
    return _STATE_MAP.get(normalized, "unknown")


def batch_status_view(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a credential-free status payload for UI polling."""
    provider_state = str(payload.get("state", "JOB_STATE_UNSPECIFIED")).strip().upper()
    status = normalize_batch_state(provider_state)
    label, explanation = _STATUS_COPY[status]
    progress = payload.get("jobProgress")
    progress = progress if isinstance(progress, dict) else {}
    provider_status = payload.get("status")
    provider_status = provider_status if isinstance(provider_status, dict) else {}
    percent = progress.get("percent")
    progress_percent = None
    if isinstance(percent, int | float):
        progress_percent = max(0.0, min(100.0, float(percent)))
    terminal = status in {"completed", "failed", "expired", "cancelled"}
    return {
        "status": status,
        "label": label,
        "provider_state": provider_state,
        "explanation": explanation,
        "provider_message": str(provider_status.get("message", "")).strip(),
        "progress_percent": progress_percent,
        "processed_requests": _optional_int(progress.get("totalProcessedRequests")),
        "total_requests": _optional_int(progress.get("totalInputRequests")),
        "failed_requests": _optional_int(progress.get("failedRequests")),
        "terminal": terminal,
        "poll_after_seconds": None if terminal else 10,
    }


def _resource_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("resource id must contain 1-128 characters")
    if any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in normalized
    ):
        raise ValueError("resource id may contain only letters, numbers, '-' and '_'")
    return normalized


def _sampling_parameters(
    *,
    max_tokens: int,
    temperature: float,
    top_k: int | None,
    top_p: float | None,
) -> dict[str, int | float]:
    if not 1 <= max_tokens <= 4096:
        raise ValueError("max_tokens must be between 1 and 4096")
    if not 0.0 <= temperature <= 2.0:
        raise ValueError("temperature must be between 0 and 2")
    if top_k is not None and not 0 <= top_k <= 100:
        raise ValueError("top_k must be between 0 and 100")
    if top_p is not None and not 0.0 <= top_p <= 1.0:
        raise ValueError("top_p must be between 0 and 1")
    result: dict[str, int | float] = {
        "maxTokens": max_tokens,
        "temperature": temperature,
    }
    if top_k is not None:
        result["topK"] = top_k
    if top_p is not None:
        result["topP"] = top_p
    return result


def _json_object(response: httpx.Response) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Fireworks response must be a JSON object")
    return payload


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None
