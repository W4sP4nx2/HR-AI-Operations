"""CrewAI hierarchical topology discovery and execution endpoints."""

from __future__ import annotations

import os
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from agents.hierarchical_crew import (
    CrewCapabilityUnavailable,
    hierarchical_system_manifest,
    run_hierarchical_system,
)
from api.responses import fail, ok, unavailable
from core.security import require_role

router = APIRouter(prefix="/crews", tags=["crews"])


class HierarchicalCrewRunRequest(BaseModel):
    """Input for one named hierarchical system."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["auto", "deterministic", "live"] = "auto"


class ResumeBatchItem(BaseModel):
    resume_id: str = Field(min_length=1, max_length=80)
    resume_text: str = Field(min_length=1, max_length=30_000)


class ResumeBatchRequest(BaseModel):
    job_description: str = Field(min_length=1, max_length=12_000)
    resumes: list[ResumeBatchItem] = Field(min_length=1, max_length=50)


@router.get("/hierarchical")
async def list_hierarchical_crews(
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Return both manager/worker topologies and their runtime readiness."""
    return ok(hierarchical_system_manifest())


@router.post("/hierarchical/{system_id}/run")
async def run_hierarchical_crew(
    system_id: str,
    body: HierarchicalCrewRunRequest,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Run a hierarchy in auto, deterministic, or explicit live mode."""
    try:
        envelope = await run_hierarchical_system(system_id, body.inputs, mode=body.mode)
    except KeyError as exc:
        return fail(str(exc))
    except ValueError as exc:
        return fail(str(exc))
    except CrewCapabilityUnavailable as exc:
        return unavailable(str(exc), {"capability": "crewai_hierarchical"})
    return ok(envelope.model_dump(mode="json"))


@router.post(
    "/hierarchical/resume_review/batch",
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_resume_review_batch(
    body: ResumeBatchRequest,
    response: Response,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Dispatch up to 50 redacted resume prompts through A2A to Fireworks Batch."""
    from agents.a2a_cards import get_card
    from agents.langsmith_cost_tracker import HierarchicalTrace, langsmith_configured
    from core.fireworks import build_batch_jsonl, validate_model
    from services.fireworks_batch import submit_jsonl_batch

    model_id = os.environ.get("FIREWORKS_BATCH_MODEL", "").strip()
    try:
        validate_model(model_id)
        card = get_card("resume_screener_agent")
        records = [
            {
                "custom_id": item.resume_id,
                "prompt": (
                    "Job description:\n"
                    f"{body.job_description}\n\nResume evidence:\n{item.resume_text}\n\n"
                    "Return advisory evidence only; a human makes the hiring decision."
                ),
            }
            for item in body.resumes
        ]
        payload = build_batch_jsonl(
            records,
            model_id=model_id,
            system_prompt=(
                "Extract job-relevant evidence into JSON. Do not infer protected attributes "
                "or make an autonomous hiring decision."
            ),
        )
        orchestration_id = f"batch-{uuid4().hex[:12]}"
        trace = HierarchicalTrace(
            name="a2a_resume_batch_dispatch",
            orchestration_id=orchestration_id,
            inputs={"resume_count": len(records), "agent": card.agent_name},
            metadata={"model_id": model_id, "serving_path": "fireworks_batch"},
        )
        submission = await submit_jsonl_batch(
            payload.encode("utf-8"), model_id=model_id, job_id=orchestration_id
        )
        trace.record_step("agent_registry", {"agent": card.agent_name})
        trace.record_step("fireworks_batch", submission)
        trace.finish({"accepted": True, "records": len(records)})
    except (RuntimeError, ValueError) as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return unavailable(
            str(exc),
            {
                "capability": "fireworks_batch",
                "required": ["FIREWORKS_BATCH_MODEL", "FIREWORKS_API_KEY", "FIREWORKS_ACCOUNT_ID"],
            },
        )
    return ok(
        {
            "accepted": True,
            "http_status": 202,
            "orchestration_id": orchestration_id,
            "agent_registry_match": card.agent_name,
            "langsmith_trace_started": langsmith_configured(),
            "model_id": model_id,
            "records": len(records),
            **submission,
        }
    )
