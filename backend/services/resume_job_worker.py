"""Bounded worker stage for durable large-resume jobs.

The worker deliberately stops at parser certification.  It proves that every
page was accepted and chunked before any model scorer is allowed to run; it
does not pretend that parsing is a hiring recommendation.  A storage adapter
can call :meth:`ResumeJobWorker.process_bytes` after validating a signed,
tenant-scoped object-storage download.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.memory import Memory, memory
from services.resume_pipeline import (
    MAX_RESUME_BYTES,
    MAX_RESUME_PAGES,
    ResumeParseError,
    ResumeParserPipeline,
    chunk_resume_text,
)


class ResumeJobWorker:
    """Process one admitted job with compare-and-set state transitions."""

    def __init__(self, store: Memory | None = None) -> None:
        self.store = store or memory
        self.parser = ResumeParserPipeline(
            max_bytes=MAX_RESUME_BYTES,
            max_pages=MAX_RESUME_PAGES,
        )

    async def process_bytes(
        self,
        job_id: str,
        tenant_id: str,
        file_bytes: bytes,
        filename: str,
    ) -> dict[str, Any] | None:
        """Parse and chunk one job, returning its terminal durable record.

        The source bytes are caller-owned and never persisted by this helper.
        In production the caller must fetch them through a tenant-scoped signed
        storage adapter and delete its temporary copy after processing.
        """
        running = await self.store.transition_resume_job(
            job_id,
            tenant_id,
            from_states=("queued",),
            state="running",
            started_at=_utcnow(),
            error_code=None,
            error_detail=None,
        )
        if not running:
            return None
        await self.store.upsert_agent(
            "resume_parser_worker",
            status="running",
            last_action=f"parsing:{job_id}",
            increment_runs=True,
        )
        try:
            parsed = await _parse(self.parser, file_bytes, filename)
            page_count = parsed.pages or 1
            chunks = chunk_resume_text(parsed.text)
            if not chunks:
                terminal = await self.store.transition_resume_job(
                    job_id,
                    tenant_id,
                    from_states=("running",),
                    state="needs_review",
                    pages_total=page_count,
                    pages_completed=page_count,
                    coverage=1.0,
                    result_json=json.dumps(parsed.as_dict(), sort_keys=True),
                    error_code="no_extractable_text",
                    error_detail="Parser produced no text; a vision or human review gate is required.",
                    completed_at=_utcnow(),
                )
                return terminal

            chunk_digests: list[str] = []
            for index, chunk in enumerate(chunks):
                chunk_digests.append(hashlib.sha256(chunk.encode("utf-8")).hexdigest())
                completed = min(page_count, max(1, round(page_count * (index + 1) / len(chunks))))
                await self.store.transition_resume_job(
                    job_id,
                    tenant_id,
                    from_states=("running",),
                    state="running",
                    pages_total=page_count,
                    pages_completed=completed,
                    coverage=round((index + 1) / len(chunks), 4),
                )

            needs_review = parsed.needs_human_review
            terminal = await self.store.transition_resume_job(
                job_id,
                tenant_id,
                from_states=("running",),
                state="needs_review" if needs_review else "certified",
                pages_total=page_count,
                pages_completed=page_count,
                coverage=1.0,
                result_json=json.dumps(
                    {
                        "stage": "parser_certified",
                        "source": parsed.as_dict(),
                        "chunk_count": len(chunks),
                        "chunk_digests": chunk_digests,
                        "scoring": "not_run",
                    },
                    sort_keys=True,
                ),
                error_code="needs_review" if needs_review else None,
                error_detail=(
                    "Parser warnings require review before scoring." if needs_review else None
                ),
                completed_at=_utcnow(),
            )
            return terminal
        except ResumeParseError as exc:
            return await self.store.transition_resume_job(
                job_id,
                tenant_id,
                from_states=("running",),
                state="failed",
                error_code="parse_error",
                error_detail=str(exc)[:240],
                completed_at=_utcnow(),
            )
        except Exception as exc:  # noqa: BLE001 - worker must persist explicit failure
            return await self.store.transition_resume_job(
                job_id,
                tenant_id,
                from_states=("running",),
                state="failed",
                error_code="worker_error",
                error_detail=f"{type(exc).__name__}: {exc}"[:240],
                completed_at=_utcnow(),
            )
        finally:
            await self.store.upsert_agent(
                "resume_parser_worker",
                status="idle",
                last_action=f"completed:{job_id}",
            )


async def _parse(parser: ResumeParserPipeline, file_bytes: bytes, filename: str):
    """Run CPU-bound parsing off the event loop."""
    import asyncio

    return await asyncio.to_thread(parser.parse, file_bytes, filename)


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
