"""Chat endpoints — conversational HR assistant via Pydantic AI.

POST /chat          Single-turn: send a message, get a JSON reply.
POST /chat/stream   Streaming: server-sent events (text/event-stream) for token-
                    by-token display in the chat panel.

The Pydantic AI agent decides which tools to call (RAG search, triage, case
lookup, attrition scoring) and returns a grounded reply. Without an API key
the agent falls back to deterministic tool dispatch with a "degraded mode"
notice.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.chat_agent import chat
from agents.pydantic_chat_agent import governed_chat
from api.responses import fail, ok
from core.memory import memory
from core.security import get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """Single chat turn payload.

    Attributes:
        message: The user's message.
        history: Prior conversation turns (role + content pairs).
        session_id: Optional session identifier for tracking + persistence.
    """

    message: str
    history: list[dict[str, str]] = []
    session_id: str = ""


def _record_stream_usage(stream: Any, agent: Any, query: str) -> str | None:
    """Record provider-reported usage for one completed Pydantic AI stream.

    Pydantic AI exposes run usage after the stream closes. Capturing it here
    keeps the operations UI honest for the browser-scoped Fireworks path while
    retaining no prompt content or API key.
    """
    try:
        usage = getattr(stream, "usage", None)
        # New Pydantic AI releases expose ``usage`` as a property. Older
        # releases used a callable compatibility wrapper, so only invoke it
        # when it is not already a RunUsage-shaped value.
        if usage is not None and not hasattr(usage, "input_tokens") and callable(usage):
            usage = usage()
        if usage is None:
            return None
        model = getattr(agent, "model", None)
        model_id = str(
            getattr(model, "model_name", None)
            or getattr(model, "model_id", None)
            or "unknown"
        )
        if model_id == "unknown":
            return None
        from core.cost_attribution import record_cost_event, record_provider_usage
        from core.cost_router import CostRouter

        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        record_provider_usage(
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_prompt_tokens=int(getattr(usage, "cache_read_tokens", 0) or 0),
        )
        # The cost tier is classified before recording the completed call, so
        # command and analytics surfaces show the same governed route that the
        # operator sees in the browser. The dollar value remains a local
        # estimate until an external billing export is connected.
        record_cost_event(
            tier=CostRouter.classify(query).tier,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            provider_call=True,
        )
        return model_id
    except Exception:  # noqa: BLE001 - telemetry must not disrupt a response
        return None


async def _ensure_session(session_id: str, message: str, user: dict[str, Any]) -> str:
    """Return a valid session id, creating one (titled from the message) if needed."""
    if session_id:
        return session_id
    uid = None if user.get("id") in (None, "anon") else user["id"]
    title = message.strip()[:60] or "New chat"
    session = await memory.create_chat_session(user_id=uid, title=title)
    return session["id"]


@router.post("")
async def chat_turn(
    body: ChatRequest, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Process a single chat message, persist the turn, and return the reply.

    Returns the status envelope with ``reply``, ``tool_calls``, ``mode`` and the
    ``session_id`` the turn was stored under.
    """
    session_id = await _ensure_session(body.session_id, body.message, user)
    await memory.add_chat_message(session_id, "user", body.message)
    result = await governed_chat(body.message, body.history, session_id)
    await memory.add_chat_message(
        session_id,
        "assistant",
        result["reply"],
        result.get("tool_calls"),
        result.get("mode"),
    )
    result["session_id"] = session_id
    return ok(result)


# --------------------------------------------------------------------------- #
# Chat history controls (list / read / delete sessions)
# --------------------------------------------------------------------------- #


@router.get("/sessions")
async def list_sessions(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """List the caller's chat sessions (all sessions for admins/anonymous dev)."""
    uid = None if user.get("id") in (None, "anon") else user["id"]
    return ok(await memory.list_chat_sessions(user_id=uid))


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str, _: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Return all messages in a chat session."""
    return ok(await memory.get_chat_messages(session_id))


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str, _: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Delete a chat session and all its messages (data control)."""
    deleted = await memory.delete_chat_session(session_id)
    if not deleted:
        return fail("session not found")
    return ok({"session_id": session_id, "deleted": True})


@router.post("/stream")
async def chat_stream(
    body: ChatRequest, user: dict[str, Any] = Depends(get_current_user)
) -> StreamingResponse:
    """Stream the assistant reply as server-sent events, persisting the turn.

    Each event is one of:
        data: {"type": "token",     "content": "…"}   incremental text
        data: {"type": "tool",      "name": "…", "args": {}}  tool call started
        data: {"type": "done",      "mode": "…", "session_id": "…"} end of stream
        data: {"type": "error",     "content": "…"}   agent error

    When running in degraded mode (no API key) the full reply is emitted as a
    single ``token`` event followed immediately by ``done``.
    """
    session_id = await _ensure_session(body.session_id, body.message, user)
    await memory.add_chat_message(session_id, "user", body.message)

    async def generate():
        reply_parts: list[str] = []
        tools_used: list[dict[str, Any]] = []
        mode = "degraded"
        try:
            from core.runtime_key import llm_active

            if not llm_active():
                result = await chat(body.message, body.history, session_id)
                mode = result.get("mode", "degraded")
                reply_parts.append(result["reply"])
                tools_used = result.get("tool_calls", [])
                yield f"data: {json.dumps({'type': 'token', 'content': result['reply']})}\n\n"
                for tc in tools_used:
                    yield f"data: {json.dumps({'type': 'tool', 'name': tc.get('tool'), 'args': {}})}\n\n"
                citations = result.get("citations") or []
                if citations:
                    yield f"data: {json.dumps({'type': 'citations', 'items': citations})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'mode': mode, 'session_id': session_id})}\n\n"
            else:
                try:
                    from pydantic_ai import Agent  # noqa: F401 — availability check

                    from agents.chat_agent import ChatDeps, get_agent

                    agent = get_agent(session_id)
                    if agent is None:
                        raise RuntimeError("agent not initialised")

                    from core.genai_lifecycle import controlled_parameters
                    from core.safety import redact_pii
                    from services.input_shield import sanitize_text

                    safe_history = [
                        {
                            **turn,
                            "content": redact_pii(sanitize_text(turn.get("content", ""))),
                        }
                        for turn in body.history[-6:]
                    ]
                    deps = ChatDeps(session_id=session_id, history=safe_history)
                    prompt = redact_pii(sanitize_text(body.message))
                    if safe_history:
                        convo = "\n".join(
                            f"{turn.get('role', 'user')}: {turn.get('content', '')}"
                            for turn in safe_history
                        )
                        prompt = f"Conversation so far:\n{convo}\n\nUser: {prompt}"

                    seen: set[str] = set()
                    async with agent.run_stream(
                        prompt,
                        deps=deps,
                        model_settings=controlled_parameters("chat"),
                    ) as stream:
                        async for chunk in stream.stream_text(delta=True):
                            reply_parts.append(chunk)
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

                        for msg in stream.all_messages():
                            for part in getattr(msg, "parts", []) or []:
                                if getattr(part, "part_kind", None) == "tool-call":
                                    name = getattr(part, "tool_name", "tool")
                                    if name not in seen:
                                        seen.add(name)
                                        tools_used.append({"tool": name})
                                        yield f"data: {json.dumps({'type': 'tool', 'name': name, 'args': {}})}\n\n"

                    mode = "full"
                    model_id = _record_stream_usage(stream, agent, prompt)
                    yield f"data: {json.dumps({'type': 'done', 'mode': 'full', 'session_id': session_id, 'model': model_id})}\n\n"

                except Exception as exc:  # noqa: BLE001 — stream fallback
                    from core.fireworks import is_scale_up_exception

                    if is_scale_up_exception(exc):
                        reply = (
                            "AI capacity is starting and this request was not queued. "
                            "Retry shortly, or continue in deterministic mode."
                        )
                        mode = "unavailable"
                        reply_parts = [reply]
                        yield f"data: {json.dumps({'type': 'token', 'content': reply})}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'mode': mode, 'session_id': session_id, 'error_code': 'DEPLOYMENT_SCALING_UP'})}\n\n"
                    else:
                        result = await chat(body.message, body.history, session_id)
                        mode = result.get("mode", "error")
                        reply_parts = [result["reply"]]
                        tools_used = result.get("tool_calls", [])
                        yield f"data: {json.dumps({'type': 'token', 'content': result['reply']})}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'mode': mode, 'session_id': session_id, 'error': str(exc)})}\n\n"

        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'mode': 'error', 'session_id': session_id})}\n\n"
        finally:
            # Persist the assembled assistant reply once the stream completes.
            reply = "".join(reply_parts)
            if reply:
                await memory.add_chat_message(session_id, "assistant", reply, tools_used, mode)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
