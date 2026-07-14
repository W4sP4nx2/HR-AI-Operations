"""Durable large-resume job contract.

This route is the control plane only. Production uploads use a signed object
storage URL; a separate worker claims the queued row and performs page/chunk
processing. Keeping admission/status separate from extraction prevents a large
resume from monopolising an HTTP request.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from api.responses import ok
from core.config import settings
from core.memory import memory
from core.security import require_role

router = APIRouter(prefix="/resume-jobs", tags=["resume-jobs"])


class ResumeJobCreate(BaseModel):
    """Signed-storage manifest submitted before worker processing."""

    filename: str = Field(min_length=1, max_length=255)
    source_object_key: str = Field(min_length=1, max_length=2048)
    size_bytes: int = Field(ge=1, le=25 * 1024 * 1024)
    pages_total: int | None = Field(default=None, ge=1, le=50)


def _tenant_id(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or ("demo" if user.get("id") == "anon" else f"tenant:{user['id']}"))


def _public_job(job: dict[str, Any], *, deduplicated: bool = False) -> dict[str, Any]:
    """Remove idempotency/storage internals while exposing state needed by UI."""
    return {
        "job_id": job["id"],
        "tenant_id": job["tenant_id"],
        "state": job["state"],
        "filename": job["filename"],
        "size_bytes": job["size_bytes"],
        "pages_total": job["pages_total"],
        "pages_completed": job["pages_completed"],
        "coverage": job["coverage"],
        "trace_id": job["trace_id"],
        "attempt": job["attempt"],
        "version": job["version"],
        "error_code": job["error_code"],
        "error_detail": job["error_detail"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job["completed_at"],
        "deduplicated": deduplicated,
        "provenance": "demo_runtime" if settings.demo_mode else "live_runtime",
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_resume_job(
    body: ResumeJobCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict[str, Any] = Depends(require_role("manager")),
) -> JSONResponse:
    """Admit a resume manifest without running extraction in the request."""
    if not idempotency_key or len(idempotency_key.strip()) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be supplied and at least 8 characters",
        )
    allowed_prefixes = ("supabase://", "s3://")
    if settings.environment != "production":
        allowed_prefixes += ("local://",)
    if not body.source_object_key.startswith(allowed_prefixes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_object_key must reference private object storage",
        )
    tenant = _tenant_id(user)
    existing = await memory.get_resume_job_by_idempotency(tenant, idempotency_key.strip())
    if existing:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=ok(_public_job(existing, deduplicated=True)),
        )
    active_jobs = await memory.list_resume_jobs(tenant, states=("queued", "running"))
    if len(active_jobs) >= settings.resume_concurrency_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="tenant resume concurrency quota is currently full",
        )
    job, deduplicated = await memory.create_resume_job(
        tenant_id=tenant,
        created_by=str(user.get("id") or "anon"),
        idempotency_key=idempotency_key.strip(),
        filename=body.filename,
        source_object_key=body.source_object_key,
        size_bytes=body.size_bytes,
        pages_total=body.pages_total,
        trace_id=f"trace-{uuid.uuid4().hex[:16]}",
    )
    payload = _public_job(job, deduplicated=deduplicated)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=ok(payload))


@router.get("/{job_id}")
async def get_resume_job(
    job_id: str,
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    job = await memory.get_resume_job(job_id, _tenant_id(user))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resume job not found")
    return ok(_public_job(job))


@router.post("/{job_id}/cancel")
async def cancel_resume_job(
    job_id: str,
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    job = await memory.transition_resume_job(
        job_id,
        _tenant_id(user),
        from_states=("queued", "running", "needs_review"),
        state="cancelled",
    )
    if not job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="resume job is missing or no longer cancellable",
        )
    return ok(_public_job(job))


@router.post("/{job_id}/retry")
async def retry_resume_job(
    job_id: str,
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    job = await memory.get_resume_job(job_id, _tenant_id(user))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resume job not found")
    if job["state"] not in {"failed", "cancelled", "needs_review"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only failed, cancelled, or needs_review jobs can be retried",
        )
    retried = await memory.transition_resume_job(
        job_id,
        _tenant_id(user),
        from_states=(job["state"],),
        state="queued",
        attempt=int(job["attempt"] or 0) + 1,
        error_code=None,
        error_detail=None,
        completed_at=None,
    )
    if not retried:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="resume job changed before retry")
    return ok(_public_job(retried))
