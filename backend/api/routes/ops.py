"""Tenant-scoped operational snapshot for the command center.

The command center must render one coherent state, not infer health by racing a
handful of unrelated endpoints.  This endpoint is deliberately read-only: the
database remains authoritative for agents, cases, approvals, and audit-derived
metrics, while provider capability data is attached with explicit provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from api.responses import ok
from core.capability_registry import capability_snapshot
from core.config import settings
from core.memory import memory
from core.runtime_key import llm_active, llm_provider
from core.security import require_role

router = APIRouter(prefix="/ops", tags=["operations"])


@router.get("/overview")
async def overview(
    user: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return one consistent, provenance-labelled command-center snapshot.

    ``tenant_id`` is included now so the frontend contract is tenant-aware.  In
    the current compatibility mode it is the authenticated subject (or the
    explicit anonymous demo tenant); the Supabase/RLS migration will replace
    that compatibility value with the membership-derived tenant id.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    agents = await memory.list_agents()
    pending = await memory.list_pending_tasks()
    status_counts = await memory.case_counts_by_status()
    by_action = await memory.audit_counts_by_action()
    capabilities = capability_snapshot()

    subject = str(user.get("id") or "anon")
    tenant_id = str(user.get("tenant_id") or ("demo" if subject == "anon" else f"tenant:{subject}"))
    active_cases = status_counts.get("open", 0) + status_counts.get("escalated", 0)
    resume_jobs = await memory.list_resume_jobs(
        tenant_id,
        states=("queued", "running", "needs_review"),
    )
    resume_counts = {
        state: sum(1 for job in resume_jobs if job["state"] == state)
        for state in ("queued", "running", "needs_review")
    }

    return ok(
        {
            "schema_version": "ops.v1",
            "tenant_id": tenant_id,
            "generated_at": generated_at,
            "fresh_for_seconds": 10,
            "provenance": "demo_runtime" if settings.demo_mode else "live_runtime",
            "agents": agents,
            "queues": {
                "human_review": {
                    "pending": len(pending),
                    "state": "blocked" if pending else "clear",
                },
                "cases": {
                    "active": active_cases,
                    "open": status_counts.get("open", 0),
                    "escalated": status_counts.get("escalated", 0),
                },
                "resume": {
                    "state": "active" if resume_jobs else "clear",
                    "pending": len(resume_jobs),
                    "queued": resume_counts["queued"],
                    "running": resume_counts["running"],
                    "needs_review": resume_counts["needs_review"],
                    "detail": "durable admission queue; extraction workers update progress",
                },
            },
            "workflow_edges": [
                {
                    "source": "triage_agent",
                    "target": "policy_qa_agent",
                    "contract": "route_to_grounded_evidence",
                },
                {
                    "source": "resume_screener_agent",
                    "target": "skill_validator",
                    "contract": "certified_skill_audit",
                },
                {
                    "source": "resume_screener_agent",
                    "target": "human_review",
                    "contract": "advisory_screening",
                },
                {
                    "source": "onboarding_agent",
                    "target": "human_review",
                    "contract": "approval_checkpoint",
                },
                {
                    "source": "attrition_agent",
                    "target": "human_review",
                    "contract": "advisory_retention_review",
                },
            ],
            "gates": {
                "auth_enforced": settings.auth_enforce,
                "llm_provider": llm_provider(),
                "llm_active": llm_active(),
                "human_review_pending": len(pending) > 0,
                "injection_blocks": by_action.get("prompt_injection_blocked", 0),
            },
            "providers": capabilities.get("providers", []),
            "hardware": capabilities.get("hardware", []),
            "slo": {
                "status": "not_measured",
                "note": "SLO values become measured only after the production load/eval harness runs.",
            },
        }
    )
