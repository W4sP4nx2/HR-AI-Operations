"""HR case management endpoints, including human-in-the-loop approvals."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agents.onboarding_agent import onboarding_agent
from api.responses import fail, ok
from api.websocket_manager import manager
from core.memory import memory
from core.security import require_role

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseCreate(BaseModel):
    """Payload to create a case directly (bypassing triage)."""

    category: str = "POLICY"
    summary: str
    detail: str = ""
    assigned_agent: str = "triage_agent"
    status: str = "open"


class ApprovalDecision(BaseModel):
    """Payload for approving/rejecting a paused agent task.

    Attributes:
        task_id: The agent task awaiting approval.
        reason: Optional reason (used for rejections).
    """

    task_id: str
    reason: str = ""


class StatusUpdate(BaseModel):
    """Payload to manually change a case's status (resolve / reopen)."""

    status: str  # resolved | open | escalated
    note: str = ""


# The human queues a misrouted case can be handed off to. Closed enum → an
# unknown queue is rejected with 422 before the data layer.
TriageQueue = Literal[
    "payroll",
    "legal",
    "employee_relations",
    "benefits",
    "it_helpdesk",
    "people_partner",
]


class TriageReroute(BaseModel):
    """Payload to reject the AI's triage routing and hand off to a human queue."""

    queue: TriageQueue
    reason: str = ""


@router.get("")
async def list_cases(
    category: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List HR cases with bounded cursor pagination."""
    return ok(
        await memory.list_cases_page(category=category, status=status, limit=limit, cursor=cursor)
    )


@router.post("")
async def create_case(body: CaseCreate) -> dict[str, Any]:
    """Create a new HR case and broadcast it to the live feed."""
    case = await memory.create_case(**body.model_dump())
    await manager.broadcast({"type": "new_case", "case": case})
    return ok(case)


_VALID_STATUSES = {"open", "resolved", "escalated"}


@router.patch("/{case_id}/status")
async def update_case_status(
    case_id: str,
    body: StatusUpdate,
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Manually resolve / reopen a case (manager+). Audited and broadcast.

    Closes the loop the agents can't: an ``open`` or ``escalated`` case can be
    marked ``resolved`` by a human, or a resolved case reopened.
    """
    if body.status not in _VALID_STATUSES:
        return fail(f"status must be one of {sorted(_VALID_STATUSES)}")
    case = await memory.update_case(case_id, status=body.status)
    if not case:
        return fail(f"case '{case_id}' not found")

    await memory.log_audit(
        case.get("assigned_agent", "case"),
        f"case_{body.status}",
        {
            "case_id": case_id,
            "note": body.note,
            "by": user.get("email"),
            "by_id": user.get("id", "unknown"),
            "role": user.get("role"),
        },
        {"status": body.status},
        "success",
    )
    await manager.broadcast({"type": "case_updated", "case": case})
    return ok(case)


@router.patch("/{case_id}/reroute")
async def reroute_case(
    case_id: str,
    body: TriageReroute,
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Reject the AI's triage routing and hand the case to a human queue.

    This is the honest alternative to forcing a misclassified case through
    "Mark resolved" (which would log a broken triage path as a success). The
    case is handed off (re-opened, re-assigned), and an immutable
    ``triage_override`` row is written — so the **Triage Override Rate** is a
    pure audit query, never a number an agent stored.
    """
    existing = await memory.get_case(case_id)
    if not existing:
        return fail(f"case '{case_id}' not found")

    case = await memory.update_case(case_id, assigned_agent=body.queue, status="open")
    await memory.log_audit(
        "triage_agent",
        "triage_override",
        {
            "case_id": case_id,
            "from_category": existing.get("category"),
            "from_assignee": existing.get("assigned_agent"),
            "to_queue": body.queue,
            "reason": body.reason,
            "by_id": user.get("id", "unknown"),
            "role": user.get("role"),
        },
        {"rerouted_to": body.queue, "status": "open"},
        "success",
    )
    await manager.broadcast({"type": "case_updated", "case": case})
    return ok(case)


@router.get("/pending")
async def pending_approvals(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """List agent tasks awaiting human approval (the Approval Queue, manager+)."""
    tasks = await memory.list_pending_tasks()
    return ok(tasks)


@router.get("/approvals/history")
async def approval_history(
    limit: int = 50,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Past approve/reject decisions, queried from the immutable audit log."""
    return ok(await memory.list_approval_history(limit=limit))


@router.get("/{case_id}")
async def get_case(case_id: str) -> dict[str, Any]:
    """Fetch a single case by id."""
    case = await memory.get_case(case_id)
    return ok(case) if case else fail("case not found")


@router.get("/{case_id}/detail")
async def get_case_detail(case_id: str) -> dict[str, Any]:
    """Fetch a case plus its activity trail for the detail drawer.

    Returns the case record and the chronological audit entries that reference
    it (agent reasoning, retrieved sources and outcomes are embedded in the
    audit ``output`` JSON).
    """
    case = await memory.get_case(case_id)
    if not case:
        return fail("case not found")
    activity = await memory.list_audit_for_case(case_id)
    return ok({"case": case, "activity": activity})


async def _resolve_decision(
    body: ApprovalDecision, decision: str, user: dict[str, Any]
) -> dict[str, Any]:
    """Shared approve/reject handler: resume the workflow and capture the decision.

    Both decisions are written to the audit log with the deciding user, the
    reason, and the resulting workflow state — so a rejected action is captured
    just as durably as an approved one.
    """
    approved = decision == "approved"
    # Atomic compare-and-set: the first decision wins and returns the row; a
    # racing/duplicate decision gets None and must NOT resume the workflow. This
    # single gate replaces the old (TOCTOU-racy) "check pending, then update".
    resolved = await memory.resolve_agent_task(body.task_id, decision, body.reason)
    if resolved is None:
        return fail("task not found or already resolved")

    state = json.loads(resolved.get("state") or "{}")
    final_state = None
    if resolved["agent_name"] == "onboarding_agent":
        onboarding_agent.set_broadcaster(manager.broadcast)
        final_state = await onboarding_agent.resume_after_approval(
            state, approved=approved, reason="" if approved else body.reason
        )

    # Capture the decision in the immutable audit trail (approve AND reject).
    await memory.log_audit(
        resolved["agent_name"],
        f"human_{decision}",
        {
            "task_id": body.task_id,
            "step": resolved.get("step"),
            "reason": body.reason,
            # decided_by (email) is PII-redacted in storage; decided_by_id is a
            # stable, non-PII actor id that survives redaction for accountability.
            "decided_by": user.get("email"),
            "decided_by_id": user.get("id", "unknown"),
            "role": user.get("role"),
        },
        {"decision": decision, "final_state": final_state},
        "success" if approved else "rejected",
    )

    await manager.broadcast(
        {
            "type": "approval_resolved",
            "decision": decision,
            "reason": body.reason,
            "task": resolved,
        }
    )
    return ok({"task": resolved, "state": final_state, "decided_by": user.get("email")})


@router.patch("/{case_id}/approve")
async def approve(
    case_id: str,
    body: ApprovalDecision,
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Approve a paused agent task and resume its workflow (manager+)."""
    return await _resolve_decision(body, "approved", user)


@router.patch("/{case_id}/reject")
async def reject(
    case_id: str,
    body: ApprovalDecision,
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Reject a paused agent task, capture the reason, and unwind it (manager+)."""
    return await _resolve_decision(body, "rejected", user)
