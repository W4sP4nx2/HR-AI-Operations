"""Input shield — a pre-flight data firewall for agent dispatch.

Raw, arbitrary user text (``"sdsd"``, a pasted essay, control characters) must
never drop straight into a specialised calculation module. This module sits in
front of :func:`api.routes.agents.dispatch_agent`:

  * **Sanitises** free text (strip control chars, collapse whitespace, cap length).
  * **Validates** structured agents' payloads against their declared contract
    (``contracts.AGENT_SPECS[name].input_model``) so e.g. the attrition model only
    ever sees six numeric features — not a string — and a bad request fails *here*
    with a clear, human-readable message instead of crashing downstream.

The shield is intentionally small and deterministic (no LLM, no deps).
"""

from __future__ import annotations

import re
from typing import Any

# Align with pipelines.intake.MAX_CHARS — one ceiling for "how much text can enter".
MAX_TEXT_CHARS = 20_000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS = re.compile(r"[ \t\f\v]+")

# The six numeric signals the attrition model needs (mirrors AttritionInput).
_ATTRITION_FEATURES = (
    "tenure_months",
    "performance_score",
    "absence_days",
    "last_promotion_months",
    "salary_band",
    "manager_rating",
)


class InvalidAgentInput(ValueError):
    """Raised when input can't be safely shaped into an agent's contract.

    Carries a ``capability`` hint so the API can return ``status="unavailable"``
    with a pointer to the right surface, rather than a generic 500.
    """

    def __init__(self, message: str, capability: str = "structured_input") -> None:
        self.capability = capability
        super().__init__(message)


def sanitize_text(text: str | None) -> str:
    """Strip control characters, collapse runs of spaces, and cap length."""
    if not text:
        return ""
    cleaned = _CONTROL_CHARS.sub("", text)
    cleaned = _WS.sub(" ", cleaned).strip()
    return cleaned[:MAX_TEXT_CHARS]


def _looks_numeric(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def prepare(
    agent_name: str, input_text: str = "", payload: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Sanitise + validate input before dispatch; raise on un-shapeable input.

    Args:
        agent_name: Registry name of the target agent.
        input_text: Free-text input.
        payload: Optional structured payload.

    Returns:
        ``(clean_text, payload)`` ready for ``dispatch_agent``.

    Raises:
        InvalidAgentInput: when a structured agent was handed free text instead
            of the numeric signals its contract requires.
    """
    clean_text = sanitize_text(input_text)
    payload = payload or {}

    if agent_name in {"policy_qa_agent", "triage_agent", "resume_screener_agent"}:
        from core.safety import redact_obj, redact_pii

        clean_text = redact_pii(clean_text)
        payload = redact_obj(payload)

    if agent_name == "attrition_agent":
        # Attrition is a maths module: it needs structured signals, not prose.
        # Reject early (with guidance) when no numeric feature is present, so a
        # string like "sdsd" can never reach the model.
        numeric = {k: payload[k] for k in _ATTRITION_FEATURES if _looks_numeric(payload.get(k))}
        if not numeric:
            raise InvalidAgentInput(
                "Attrition scoring needs structured employee signals (tenure, "
                "performance, absence, time-since-promotion, salary band, manager "
                "rating) — not free text. Open the Attrition panel to enter them.",
                capability="structured_input",
            )
        # Coerce the recognised features to float; the agent fills any gaps with
        # neutral defaults. Out-of-range values are clamped by the model contract.
        payload = {**payload, **{k: float(v) for k, v in numeric.items()}}

    return clean_text, payload
