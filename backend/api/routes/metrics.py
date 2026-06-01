"""Operational metrics — derived purely by querying the audit log + cases.

The audit log is the single source of truth. No agent calculates or stores a
metric; this endpoint *queries* the immutable record and rolls it up (Stripe's
model: every action → immutable log → metrics derived from queries). The
Analytics dashboard renders exactly what this returns.

GET /metrics  → KPIs, agent activity, case status/category distributions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from api.responses import ok
from core.memory import memory
from core.security import require_role

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _rate(part: int, whole: int) -> float:
    """Safe ratio in [0, 1], rounded to 3 dp (0 when there's nothing to divide)."""
    return round(part / whole, 3) if whole else 0.0


@router.get("")
async def get_metrics(_: dict[str, Any] = Depends(require_role("analyst"))) -> dict[str, Any]:
    """Return live operational metrics computed from the audit log and cases.

    Everything here is a query result, never a precomputed counter:
      * agent_actions_total / actions_by_agent — from the audit table.
      * active_cases / resolved / escalations — from case status counts.
      * auto_resolution_rate — resolved ÷ (all triaged cases).
      * resume_screens — audit rows with action_type ``resume_screen``.
      * cases_by_category — the triage distribution.
    """
    actions_total = await memory.count_audit()
    by_agent = await memory.audit_counts_by_agent()
    by_action = await memory.audit_counts_by_action()
    status_counts = await memory.case_counts_by_status()
    by_category = await memory.case_counts_by_category()

    cases_total = sum(status_counts.values())
    active_cases = status_counts.get("open", 0) + status_counts.get("escalated", 0)
    resolved = status_counts.get("resolved", 0)
    escalations = status_counts.get("escalated", 0)

    # Today (UTC) — used for the "resolved today" KPI.
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    resolved_today = await memory.count_cases_resolved_since(midnight.isoformat())

    return ok(
        {
            "agent_actions_total": actions_total,
            "actions_by_agent": by_agent,
            "cases_total": cases_total,
            "active_cases": active_cases,
            "resolved_cases": resolved,
            "resolved_today": resolved_today,
            "escalations": escalations,
            "resume_screens": by_action.get("resume_screen", 0),
            "policy_queries": by_action.get("policy_query", 0),
            "injection_blocks": by_action.get("prompt_injection_blocked", 0),
            # Triage override telemetry: of all triaged cases, how often a human
            # rejected the AI's routing and re-routed it (a pure audit query).
            "triage_overrides": by_action.get("triage_override", 0),
            "triage_override_rate": _rate(
                by_action.get("triage_override", 0), by_action.get("triage", 0)
            ),
            # Auto-resolution rate: of all triaged cases, how many the system
            # resolved without a human (the headline efficiency number).
            "auto_resolution_rate": _rate(resolved, cases_total),
            "escalation_rate": _rate(escalations, cases_total),
            "cases_by_status": [{"status": k, "count": v} for k, v in status_counts.items()],
            "cases_by_category": by_category,
        }
    )
