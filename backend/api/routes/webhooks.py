"""Inbound webhook endpoints — let external systems trigger agents.

Upstream systems (ATS, ticketing/helpdesk, HRIS, web forms, scrapers) POST a
JSON event here; the webhook normalises it into text and routes it to an agent
(triage by default). This is how the system ingests *what the outside world
sends in*, with the same ``ok``/``error``/``unavailable`` status contract.

Security note: production deployments should verify a per-source signature
(HMAC) and/or a shared secret before processing. The verification hook is
stubbed (``_verify_signature``) and documented for the operations manual.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, Request

from api.responses import fail, ok, unavailable
from api.routes.agents import dispatch_agent
from core.config import settings
from pipelines.intake import CapabilityUnavailable, resolve_input

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Candidate keys, in priority order, used to find the text in an unknown payload.
_TEXT_KEYS = ("text", "message", "body", "description", "summary", "content", "subject")

# Map a webhook source name to the agent it should trigger.
_SOURCE_ROUTING = {
    "ticketing": "triage_agent",
    "helpdesk": "triage_agent",
    "form": "triage_agent",
    "ats": "resume_screener_agent",
    "policy": "policy_qa_agent",
}


def _verify_signature(request: Request, body: bytes) -> bool:
    """Verify the inbound request's authenticity.

    Precedence (when ``WEBHOOK_SECRET`` is set):
      1. **HMAC** — ``X-Webhook-Signature: sha256=<hexdigest>`` over the raw body,
         keyed by the secret (constant-time compared). This is the production path.
      2. **Shared secret** — ``X-Webhook-Secret: <secret>`` (simple back-compat).

    Returns ``True`` when no secret is configured (dev mode).
    """
    secret = settings.webhook_secret
    if not secret:
        return True

    sig = request.headers.get("x-webhook-signature", "")
    if sig:
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        provided = sig.split("=", 1)[1] if "=" in sig else sig
        return hmac.compare_digest(expected, provided)

    presented = request.headers.get("x-webhook-secret", "")
    return bool(presented) and hmac.compare_digest(presented, secret)


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull the most likely free-text field from an arbitrary JSON payload."""
    for key in _TEXT_KEYS:
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            # If both subject and body exist, prefer their combination.
            if key == "subject" and isinstance(payload.get("body"), str):
                return f"{val}\n\n{payload['body']}"
            return val
    return ""


@router.post("/{source}")
async def receive_webhook(source: str, request: Request) -> dict[str, Any]:
    """Receive an inbound event from ``source`` and trigger the routed agent.

    Body: arbitrary JSON. Recognised fields include ``text``/``message``/
    ``body``/``description``/``summary``/``subject``, an optional ``url`` to
    scrape, and an optional ``target_agent`` override.

    Returns the status envelope describing the triggered agent's outcome.
    """
    body = await request.body()
    if not _verify_signature(request, body):
        return fail("signature verification failed")

    try:
        import json

        payload = json.loads(body or b"{}")
    except Exception:  # noqa: BLE001
        return fail("invalid JSON body")
    if not isinstance(payload, dict):
        return fail("webhook body must be a JSON object")

    target_agent = payload.get("target_agent") or _SOURCE_ROUTING.get(source, "triage_agent")

    # Resolve the inbound content: an explicit URL scrapes, else free text.
    url = payload.get("url")
    text = _extract_text(payload)
    try:
        intake = resolve_input(text=text or None, url=url)
    except CapabilityUnavailable as exc:
        return unavailable(str(exc), {"capability": exc.capability})
    except ValueError as exc:
        return fail(str(exc))

    try:
        result = await dispatch_agent(target_agent, intake.text, None)
    except KeyError:
        return fail(f"unknown target agent: {target_agent}")
    except CapabilityUnavailable as exc:
        return unavailable(str(exc), {"capability": exc.capability})
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc), {"intake": intake.as_dict()})

    return ok(
        {
            "source": source,
            "routed_to": target_agent,
            "intake": intake.as_dict(),
            "result": result,
        }
    )
