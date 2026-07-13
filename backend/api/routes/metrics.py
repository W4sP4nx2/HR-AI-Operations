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
from core.bias_audit import DEFAULT_SYNTHETIC_ATS_PATH, audit_hiring_csv
from core.config import settings
from core.cost_attribution import cost_attribution_snapshot, provider_usage_snapshot
from core.memory import memory
from core.runtime_key import llm_active, llm_provider
from core.security import require_role
from services.fireworks_batch import batch_config_status

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _rate(part: int, whole: int) -> float:
    """Safe ratio in [0, 1], rounded to 3 dp (0 when there's nothing to divide)."""
    return round(part / whole, 3) if whole else 0.0


def _illustrative_savings_scenario() -> dict[str, Any]:
    """Return transparent math for a roughly 35% blended target, not a claim."""
    batch_share = 0.40
    batch_discount = 0.50
    online_share = 1.0 - batch_share
    input_cost_share = 0.70
    cache_hit_rate = 0.50
    cached_input_discount = 0.50
    retry_spend_share = 0.05
    reduction = (
        batch_share * batch_discount
        + online_share * input_cost_share * cache_hit_rate * cached_input_discount
        + online_share * retry_spend_share
    )
    return {
        "status": "illustrative_target_not_measured",
        "blended_reduction": round(reduction, 4),
        "plain_language": "About 35% under this workload mix; validate with billing exports.",
        "assumptions": {
            "batch_workload_share": batch_share,
            "batch_discount": batch_discount,
            "online_input_cost_share": input_cost_share,
            "online_cache_hit_rate": cache_hit_rate,
            "cached_input_discount": cached_input_discount,
            "avoidable_retry_spend_share": retry_spend_share,
        },
        "caveats": [
            "Batch and cache savings are modeled on separate workload portions.",
            "Prompt caching reduces eligible input cost, not output cost.",
            "Retry savings require measured baseline retries; zero retries are not assumed.",
        ],
    }


@router.get("")
async def get_metrics(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
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


@router.get("/bias-audit")
async def get_bias_audit(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return Four-Fifths rule evidence from the synthetic ATS stress dataset."""
    try:
        audit = audit_hiring_csv(DEFAULT_SYNTHETIC_ATS_PATH)
    except FileNotFoundError as exc:
        audit = {
            "dataset_path": str(DEFAULT_SYNTHETIC_ATS_PATH),
            "record_count": 0,
            "decision_column": "hired",
            "threshold": 0.80,
            "violations_count": 0,
            "violates_four_fifths_rule": False,
            "dimensions": [],
            "headline": str(exc),
            "available": False,
        }
    else:
        audit["available"] = True
    return ok(audit)


@router.get("/inference-usage")
async def get_inference_usage(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return local token/cost telemetry and Fireworks billing-export readiness.

    The local ledger is application-observed and process-local. It is not a
    provider bill. Fireworks account billing export remains credential-gated via
    ``FIREWORKS_ACCOUNT_ID`` + ``FIREWORKS_API_KEY`` and is represented here as
    readiness metadata so the dashboard can be honest in zero-secret previews.
    """
    snapshot = cost_attribution_snapshot()
    observed = provider_usage_snapshot()
    rows = snapshot["cost_attribution"]
    totals = {
        "queries": sum(int(row["queries"]) for row in rows.values()),
        "provider_calls": sum(int(row["provider_calls"]) for row in rows.values()),
        "input_tokens": sum(int(row["input_tokens"]) for row in rows.values()),
        "output_tokens": sum(int(row["output_tokens"]) for row in rows.values()),
        "estimated_usd": round(sum(float(row["total_usd"]) for row in rows.values()), 6),
    }
    billing_ready = bool(
        settings.fireworks_account_id.strip() and settings.fireworks_api_key.strip()
    )
    from scripts.benchmark_cost_controls import run_ab_benchmark

    benchmark = run_ab_benchmark()
    batch = batch_config_status()
    return ok(
        {
            "source": "mixed_provenance",
            "provider": llm_provider(),
            "provider_live_enabled": llm_active(),
            "totals": totals,
            "provider_observed": observed,
            "tiers": rows,
            "cache_hit_rate": snapshot["cache_hit_rate"],
            "prefilter_skip_rate": snapshot["prefilter_skip_rate"],
            "token_efficiency_ratio": snapshot["token_efficiency_ratio"],
            "budget_circuit_breaker": snapshot["budget_circuit_breaker"],
            "estimation": snapshot["estimation"],
            "cost_benchmark": benchmark,
            "blended_cost_scenario": _illustrative_savings_scenario(),
            "fireworks_serverless": {
                "configured": llm_provider() == "fireworks",
                "billing_export_ready": False,
                "billing_export_configured": billing_ready,
                "account_id_configured": bool(settings.fireworks_account_id.strip()),
                "api_key_configured": bool(settings.fireworks_api_key.strip()),
                "billing_export_method": "firectl billing export-metrics",
                "billing_export_max_range_days": 31,
                "billing_api_fetch_implemented": False,
                "request_annotations": {
                    "team": "hr",
                    "project": "hr-command-center",
                    "environment": settings.environment,
                },
                "dashboard_note": (
                    "Provider-response tokens are observed live. Dollar values remain local "
                    "estimates until a Fireworks billing CSV is imported."
                ),
            },
            "fireworks_batch": {
                "ready": batch["ready"],
                "issues": batch["issues"],
                "detail": (
                    "Batch control-plane configuration is ready for provider submission."
                    if batch["ready"]
                    else "Batch provider calls are disabled until the control-plane inputs are configured."
                ),
            },
        }
    )
