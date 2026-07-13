"""Offline preparation and provider handoff for high-volume resume batches.

Preparation is intentionally network-free and idempotent.  The caller can
review the manifest and upload it through :class:`FireworksBatchClient` only
after consent, retention, and budget checks pass.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pipelines.intake import CapabilityUnavailable
from services.resume_extractor import EXTRACTED_RESUME_SCHEMA
from services.resume_pipeline import ParsedResume, ResumeParseError, ResumeParserPipeline


@dataclass(frozen=True)
class ResumeBatchRecord:
    custom_id: str
    source_ref: str
    parsed: ParsedResume
    prompt: str


@dataclass(frozen=True)
class ResumeBatchManifest:
    records: tuple[ResumeBatchRecord, ...]
    skipped: tuple[dict[str, str], ...] = ()

    @property
    def total(self) -> int:
        return len(self.records) + len(self.skipped)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "prepared": len(self.records),
            "skipped": list(self.skipped),
            "custom_ids": [record.custom_id for record in self.records],
        }


@dataclass(frozen=True)
class BatchSubmission:
    """Secret-free record of one provider batch submission."""

    job_id: str
    input_dataset_id: str
    output_dataset_id: str
    records: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "input_dataset_id": self.input_dataset_id,
            "output_dataset_id": self.output_dataset_id,
            "records": self.records,
        }


class ResumeBatchProcessor:
    """Prepare bounded JSONL requests for Fireworks Batch inference."""

    def __init__(
        self,
        *,
        parser: ResumeParserPipeline | None = None,
        batch_size: int = 100,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.parser = parser or ResumeParserPipeline()
        self.batch_size = batch_size

    def prepare(
        self,
        files: Iterable[Path],
        *,
        job_description: str,
        model_id: str,
    ) -> ResumeBatchManifest:
        """Parse files and produce deterministic records, skipping bad inputs."""
        if not job_description.strip():
            raise ValueError("job_description is required for resume screening")
        if not model_id.strip():
            raise ValueError("model_id must be injected from the deployment allow-list")
        records: list[ResumeBatchRecord] = []
        skipped: list[dict[str, str]] = []
        for index, path in enumerate(sorted(files, key=lambda item: item.name.lower()), start=1):
            try:
                parsed = self.parser.parse(path.read_bytes(), path.name)
                if not parsed.text.strip():
                    raise ResumeParseError("no text; use the bounded vision fallback before batching")
                records.append(
                    ResumeBatchRecord(
                        custom_id=_custom_id(index, path),
                        source_ref=path.name,
                        parsed=parsed,
                        prompt=_screening_prompt(job_description, parsed),
                    )
                )
            except (CapabilityUnavailable, OSError, ResumeParseError, ValueError) as exc:
                skipped.append({"source_ref": path.name, "reason": str(exc)})
        return ResumeBatchManifest(tuple(records), tuple(skipped))

    def to_jsonl(self, manifest: ResumeBatchManifest, *, model_id: str) -> str:
        """Serialize records as strict-schema JSONL accepted by the Batch API."""
        if not model_id.strip():
            raise ValueError("model_id must not be empty")
        lines: list[str] = []
        seen: set[str] = set()
        for record in manifest.records:
            if record.custom_id in seen:
                raise ValueError(f"duplicate custom_id: {record.custom_id}")
            seen.add(record.custom_id)
            lines.append(
                json.dumps(
                    {
                        "custom_id": record.custom_id,
                        "body": {
                            "model": model_id,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": (
                                        "Return advisory resume evidence only. Do not make an "
                                        "autonomous hiring decision."
                                    ),
                                },
                                {"role": "user", "content": record.prompt},
                            ],
                            "max_tokens": 1200,
                            "temperature": 0.0,
                            "response_format": {
                                "type": "json_schema",
                                "json_schema": {
                                    "name": "ExtractedResume",
                                    "strict": True,
                                    "schema": EXTRACTED_RESUME_SCHEMA,
                                },
                            },
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return "\n".join(lines) + ("\n" if lines else "")

    def iter_batches(self, manifest: ResumeBatchManifest) -> Iterator[ResumeBatchManifest]:
        """Yield bounded, independently reviewable batches in source order."""
        for start in range(0, len(manifest.records), self.batch_size):
            yield ResumeBatchManifest(
                records=manifest.records[start : start + self.batch_size],
                skipped=(),
            )

    async def submit_batches(
        self,
        manifest: ResumeBatchManifest,
        *,
        model_id: str,
        job_prefix: str = "resume",
    ) -> list[BatchSubmission]:
        """Upload and submit each bounded batch through the Fireworks client.

        This is the first network boundary in the pipeline. Preparation remains
        offline and reviewable; this method requires the injected Fireworks
        control-plane credentials and returns only identifiers/counts.
        """
        from services.fireworks_batch import BatchConfig, FireworksBatchClient

        prefix = _safe_id(job_prefix)
        config = BatchConfig.from_env()
        submissions: list[BatchSubmission] = []
        async with FireworksBatchClient(config) as client:
            for index, batch in enumerate(self.iter_batches(manifest), start=1):
                job_id = _safe_id(f"{prefix}-{index:04d}")
                input_id = _safe_id(f"{job_id}-input")
                output_id = _safe_id(f"{job_id}-output")
                payload = self.to_jsonl(batch, model_id=model_id).encode("utf-8")
                await client.create_dataset(input_id)
                await client.create_dataset(output_id)
                await client.upload_jsonl(input_id, payload, filename=f"{job_id}.jsonl")
                await client.create_job(
                    job_id=job_id,
                    model_id=model_id,
                    input_dataset_id=input_id,
                    output_dataset_id=output_id,
                )
                submissions.append(BatchSubmission(job_id, input_id, output_id, len(batch.records)))
        return submissions

    async def poll_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float = 30.0,
        max_polls: int = 120,
    ) -> dict[str, Any]:
        """Poll one job with a hard bound and normalized provider state."""
        from services.fireworks_batch import BatchConfig, FireworksBatchClient, batch_status_view

        if max_polls < 1:
            raise ValueError("max_polls must be positive")
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must not be negative")
        config = BatchConfig.from_env()
        async with FireworksBatchClient(config) as client:
            for attempt in range(max_polls):
                view = batch_status_view(await client.get_job(job_id))
                if view["terminal"] or attempt == max_polls - 1:
                    return {"job_id": job_id, "polls": attempt + 1, **view}
                await asyncio.sleep(poll_interval_seconds)
        raise RuntimeError("batch polling ended without a provider response")

    def write_jsonl(self, manifest: ResumeBatchManifest, path: Path, *, model_id: str) -> None:
        """Write a prepared batch without creating parent directories implicitly."""
        path.write_text(self.to_jsonl(manifest, model_id=model_id), encoding="utf-8")


def _custom_id(index: int, path: Path) -> str:
    digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:12]
    return f"resume-{index:05d}-{digest}"


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-")
    if not normalized:
        raise ValueError("batch identifier must contain letters or numbers")
    return normalized[:100]


def _screening_prompt(job_description: str, parsed: ParsedResume) -> str:
    return (
        "Extract structured facts from this resume and compare them to the job description. "
        "Missing facts must be null or empty lists; do not infer protected traits.\n\n"
        f"Job description:\n{job_description.strip()}\n\n"
        f"Resume ({parsed.source_ref}):\n{parsed.text}"
    )
