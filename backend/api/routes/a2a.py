"""Protocol-shaped A2A endpoints for the Govern.ai demo.

Two roles are independently addressable under ``/a2a/agents``.  The endpoint
is intentionally small: Agent Card discovery, JSON-RPC ``message/send`` and a
read-only graph endpoint are enough to prove the handoff without pretending
that a remote federation or asynchronous broker is already deployed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from api.responses import fail, ok
from core.a2a_protocol import AGENT_CARDS, JsonRpcRequest, card_for, execute_agent_message

router = APIRouter(prefix="/a2a", tags=["a2a"])


@router.get("/graph")
async def a2a_graph() -> dict[str, Any]:
    """Expose the proof topology and its honest deployment boundary."""
    return ok(
        {
            "protocol": "A2A-shaped JSON-RPC over HTTP",
            "protocol_version": "0.3.0",
            "deployment_boundary": "two independently addressable endpoints in one service",
            "remote_federation": False,
            "handoffs": [
                {
                    "source": "resume_extractor",
                    "target": "policy_guard",
                    "message_method": "message/send",
                    "raw_resume_forwarded": False,
                },
                {
                    "source": "policy_guard",
                    "target": "human_reviewer",
                    "message_method": "message/send",
                    "human_approval_required": True,
                },
            ],
            "cards": [card.model_dump(mode="json") for card in AGENT_CARDS.values()],
        }
    )


@router.get("/agents/{agent_name}/.well-known/agent-card.json")
async def agent_card(agent_name: str) -> dict[str, Any]:
    """Return the card for one addressable role."""
    try:
        return card_for(agent_name).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown A2A agent") from exc


@router.post("/agents/{agent_name}/rpc")
async def agent_rpc(agent_name: str, body: JsonRpcRequest) -> dict[str, Any]:
    """Handle the minimal ``message/send`` and ``tasks/get`` contract."""
    if agent_name not in AGENT_CARDS:
        return fail("unknown A2A agent")
    if body.method != "message/send":
        return {
            "jsonrpc": "2.0",
            "id": body.id,
            "error": {"code": -32601, "message": "only message/send is supported in demo"},
        }
    try:
        task, envelope = await execute_agent_message(agent_name, body.params)
    except (KeyError, ValueError) as exc:
        return {
            "jsonrpc": "2.0",
            "id": body.id,
            "error": {"code": -32602, "message": str(exc)},
        }
    except Exception as exc:  # noqa: BLE001 - protocol error is stable and bounded
        return {
            "jsonrpc": "2.0",
            "id": body.id,
            "error": {"code": -32000, "message": f"agent execution failed: {type(exc).__name__}"},
        }
    return {
        "jsonrpc": "2.0",
        "id": body.id,
        "result": {
            "task": task.model_dump(mode="json"),
            "trace_id": envelope.trace_id,
            "certification": envelope.certification.model_dump(mode="json"),
        },
    }
