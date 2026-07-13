"""GenAI lifecycle, evaluation, and human-label collection analysis."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.responses import fail, ok, unavailable
from core.capability_registry import capability_snapshot
from core.fireworks import fireworks_manifest
from core.genai_lifecycle import lifecycle_manifest
from core.hallucination import hallucination_metrics_snapshot
from core.memory import memory
from core.security import require_role
from models.baseline_evaluation import evaluate_all
from services.fireworks_batch import (
    BatchConfig,
    FireworksBatchClient,
    batch_status_view,
)

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


async def build_lifecycle_analysis() -> dict[str, Any]:
    """Assemble model controls, baseline comparisons, and collected-label health."""
    actions = await memory.audit_counts_by_action()
    feedback = await memory.feedback_stats()
    feedback_total = sum(row["total"] for row in feedback)
    triage_total = actions.get("triage", 0)
    overrides = actions.get("triage_override", 0)
    return {
        "manifest": lifecycle_manifest(),
        "comparisons": evaluate_all(),
        "data_collection": {
            "triage_predictions": triage_total,
            "triage_overrides": overrides,
            "retention_feedback_labels": feedback_total,
            "retention_feedback_by_driver": feedback,
            "sources": [
                "append-only triage_override audit events",
                "append-only accepted/rejected/edited manager feedback",
            ],
            "limitations": [
                "no override does not mean a prediction was human-confirmed",
                "interaction telemetry is selection-biased",
                "manager feedback is not an attrition outcome label",
            ],
        },
        "training_readiness": {
            "ready": False,
            "reason": (
                "Collected interaction labels are analysis signals only. Post-training "
                "requires a governed, versioned dataset, consent/retention policy, "
                "representative sampling, temporal holdout, and bias review."
            ),
        },
    }


@router.get("")
async def lifecycle(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return reviewable GenAI lifecycle controls and collection analysis."""
    return ok(await build_lifecycle_analysis())


@router.get("/fireworks")
async def fireworks(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return no-secret Fireworks capability, routing, and promotion controls."""
    return ok(fireworks_manifest())


@router.get("/capabilities")
async def capabilities(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return evidence-based provider and hardware capability discovery."""
    return ok(capability_snapshot())


@router.get("/hallucination_metrics")
async def hallucination_metrics(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return anti-hallucination metrics from certification and audit evidence."""
    return ok(
        hallucination_metrics_snapshot(
            audit_counts=await memory.audit_counts_by_action(),
            window=100,
        )
    )


@router.get("/cost-controls")
async def cost_controls(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return zero-spend cost-governance certification evidence."""
    from scripts.certify_cost_controls import run_certification

    result = run_certification()
    return ok(result)


@router.get("/fireworks/batch/{job_id}")
async def fireworks_batch_status(
    job_id: str,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return a normalized Batch state without persisting provider payloads."""
    try:
        config = BatchConfig.from_env()
        async with FireworksBatchClient(config) as client:
            result = await client.get_job(job_id)
    except RuntimeError as exc:
        return unavailable(str(exc), {"capability": "fireworks_batch"})
    except ValueError as exc:
        return fail(str(exc))
    except Exception:  # noqa: BLE001 - provider/network detail stays server-side
        return unavailable(
            "Fireworks Batch status is temporarily unavailable",
            {"capability": "fireworks_batch"},
        )
    return ok({"job_id": job_id, **batch_status_view(result)})
