"""Compliance audit log endpoints."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.responses import ok
from core.memory import memory
from core.security import require_role

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit(
    agent: str | None = None,
    limit: int = 200,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return audit-log rows, optionally filtered by agent.

    Args:
        agent: Optional agent-name filter.
        limit: Maximum rows to return.

    Returns:
        Standard envelope wrapping the audit rows.
    """
    rows = await memory.list_audit(agent=agent, limit=limit)
    return ok(rows)


@router.get("/export")
async def export_audit(
    agent: str | None = None,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> StreamingResponse:
    """Stream the audit log as a downloadable CSV file.

    Args:
        agent: Optional agent-name filter.

    Returns:
        A CSV ``StreamingResponse``.
    """
    rows = await memory.list_audit(agent=agent, limit=10000)
    buffer = io.StringIO()
    fieldnames = ["timestamp", "agent_name", "action_type", "input", "output", "status"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )
