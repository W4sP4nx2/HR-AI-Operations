"""Agent status and manual trigger endpoints.

Agents can be triggered three ways, all funnelling through :func:`dispatch_agent`:

  * ``POST /agents/{name}/trigger``         — JSON ``{input, payload}``
  * ``POST /agents/{name}/trigger/upload``  — multipart text / PDF / URL intake
  * (inbound) webhooks — see :mod:`api.routes.webhooks`

Every response uses the status envelope (``ok`` / ``error`` / ``unavailable``)
so the dashboard's trigger button can show a precise outcome.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agents.attrition_agent import attrition_agent
from agents.contracts import AGENT_SPECS
from agents.onboarding_agent import onboarding_agent
from agents.policy_qa_agent import policy_qa_agent
from agents.resume_screener_agent import resume_screener_agent
from agents.triage_agent import triage_agent
from api.responses import fail, ok, unavailable
from core.config import settings
from core.memory import memory
from core.security import get_current_user, has_role
from pipelines.intake import CapabilityUnavailable, enforce_upload_size, resolve_input
from services.input_shield import InvalidAgentInput


def _enforce_agent_role(agent_name: str, user: dict[str, Any]) -> None:
    """Gate *triggering* an agent on its declared ``min_role`` (write authority).

    Each agent's required role lives in ``contracts.AGENT_SPECS`` (viewer for
    Policy Q&A, analyst for Triage/Resume Screener, manager for Onboarding/
    Attrition). Advisory in demo mode; under ``AUTH_ENFORCE`` an under-privileged
    caller is blocked with 403 — so an Analyst can't drive manager-only agents,
    even via the raw API.
    """
    spec = AGENT_SPECS.get(agent_name)
    min_role = spec.min_role if spec else "manager"
    if settings.auth_enforce and not has_role(user, min_role):
        raise HTTPException(
            status_code=403, detail=f"triggering '{agent_name}' requires '{min_role}' or higher"
        )

router = APIRouter(prefix="/agents", tags=["agents"])

# Static registry describing each agent for the Fleet panel.
AGENT_REGISTRY = [
    {"name": "policy_qa_agent", "label": "Policy Q&A", "framework": "LangGraph"},
    {"name": "onboarding_agent", "label": "Onboarding Orchestrator", "framework": "LangGraph"},
    {"name": "resume_screener_agent", "label": "Resume Screener", "framework": "CrewAI"},
    {"name": "triage_agent", "label": "Triage", "framework": "CrewAI"},
    {"name": "attrition_agent", "label": "Attrition Predictor", "framework": "scikit-learn"},
]


class TriggerRequest(BaseModel):
    """Payload for manually triggering an agent.

    Attributes:
        input: Free-text input (query, ticket, resume, etc.).
        payload: Optional structured payload (e.g. new-hire dict or features).
    """

    input: str = ""
    payload: dict[str, Any] | None = None


async def dispatch_agent(
    agent_name: str, input_text: str = "", payload: dict[str, Any] | None = None
) -> Any:
    """Run a named agent with text and/or a structured payload.

    Args:
        agent_name: Registry name of the agent.
        input_text: Free-text input (query/ticket/resume text).
        payload: Optional structured payload.

    Returns:
        The agent's result object.

    Raises:
        KeyError: if ``agent_name`` is unknown.
        InvalidAgentInput: if input can't be shaped into the agent's contract.
    """
    # Pre-flight: sanitise text + validate structured input before any agent runs.
    from services.input_shield import prepare

    input_text, payload = prepare(agent_name, input_text, payload)

    if agent_name == "policy_qa_agent":
        return await policy_qa_agent.run(input_text)
    if agent_name == "triage_agent":
        return await triage_agent.run(input_text)
    if agent_name == "resume_screener_agent":
        payload = payload or {}
        return await resume_screener_agent.run(
            payload.get("job_description", input_text),
            payload.get("resume", input_text),
        )
    if agent_name == "onboarding_agent":
        new_hire = payload or {
            "name": input_text or "New Hire",
            "email": "new.hire@example.com",
            "department": "engineering",
            "manager": "manager@example.com",
        }
        return await onboarding_agent.start(new_hire)
    if agent_name == "attrition_agent":
        return await attrition_agent.run(payload or {})
    raise KeyError(agent_name)


@router.get("")
async def list_agents() -> dict[str, Any]:
    """Return runtime status for every agent, merged with registry metadata."""
    runtime = {a["name"]: a for a in await memory.list_agents()}
    merged = []
    for entry in AGENT_REGISTRY:
        state = runtime.get(entry["name"], {})
        merged.append(
            {
                **entry,
                "status": (state.get("status") or "idle").upper(),
                "last_action": state.get("last_action"),
                "last_run": state.get("last_run"),
                "total_runs": state.get("total_runs", 0),
            }
        )
    return ok(merged)


@router.post("/{agent_name}/trigger")
async def trigger_agent(
    agent_name: str,
    body: TriggerRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Manually invoke an agent with JSON ``{input, payload}`` (write authority).

    Returns the status envelope: ``ok`` on success, ``unavailable`` when a
    required capability is missing, ``error`` otherwise.
    """
    _enforce_agent_role(agent_name, user)
    try:
        result = await dispatch_agent(agent_name, body.input, body.payload)
    except KeyError:
        return fail(f"unknown agent: {agent_name}")
    except InvalidAgentInput as exc:
        return unavailable(str(exc), {"capability": exc.capability})
    except CapabilityUnavailable as exc:
        return unavailable(str(exc), {"capability": exc.capability})
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))
    return ok(_attach_mode(result))


@router.post("/{agent_name}/trigger/upload")
async def trigger_agent_upload(
    agent_name: str,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    text: str | None = Form(default=None),
    job_description: str | None = Form(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Trigger an agent from a typed text, an uploaded PDF, or a scraped URL.

    Form fields (provide one of file/url/text):
        file: a PDF attachment (e.g. resume, policy, ticket export).
        url: a link to scrape for its readable text.
        text: raw text typed directly.
        job_description: optional JD text for the resume screener (the uploaded
            document is treated as the candidate resume).

    Returns the status envelope, with an ``intake`` summary describing what was
    passed into the system (source type, reference, char count).
    """
    if agent_name not in {a["name"] for a in AGENT_REGISTRY}:
        return fail(f"unknown agent: {agent_name}")
    _enforce_agent_role(agent_name, user)

    # 1) Resolve the input into normalised text (this is "what gets passed in").
    try:
        pdf_bytes = await file.read() if file is not None else None
        enforce_upload_size(pdf_bytes)
        intake = resolve_input(
            text=text,
            pdf_bytes=pdf_bytes,
            filename=file.filename if file is not None else None,
            url=url,
        )
    except CapabilityUnavailable as exc:
        return unavailable(str(exc), {"capability": exc.capability})
    except ValueError as exc:
        return fail(str(exc))

    # 2) Map the extracted text to the agent's expected shape.
    payload: dict[str, Any] | None = None
    if agent_name == "resume_screener_agent":
        payload = {"job_description": job_description or "", "resume": intake.text}
    elif agent_name == "attrition_agent":
        # Attrition needs six structured signals, not free text — guide the user
        # to the right surface instead of throwing a hard error on raw input.
        return unavailable(
            "Attrition scoring needs structured employee signals (tenure, performance, "
            "absence, …), not free text. Open the Attrition panel to enter them.",
            {"capability": "structured_input", "panel": "attrition"},
        )

    # 3) Dispatch and classify the outcome.
    try:
        result = await dispatch_agent(agent_name, intake.text, payload)
    except InvalidAgentInput as exc:
        return unavailable(str(exc), {"capability": exc.capability})
    except CapabilityUnavailable as exc:
        return unavailable(str(exc), {"capability": exc.capability})
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc), {"intake": intake.as_dict()})

    data = _attach_mode(result)
    return ok({"result": data, "intake": intake.as_dict()})


def _attach_mode(result: Any) -> Any:
    """Annotate a result with whether the system ran in degraded (no-LLM) mode.

    Keeps the trigger button honest: a successful run with no API key is ``ok``
    but flagged ``degraded`` so operators know answers are deterministic
    fallbacks rather than LLM-grounded.
    """
    degraded = not settings.anthropic_api_key
    if isinstance(result, dict):
        return {**result, "_mode": "degraded" if degraded else "full"}
    return {"result": result, "_mode": "degraded" if degraded else "full"}
