"""Consistent API envelope helpers.

Every endpoint returns the envelope::

    {success: bool, status: "ok"|"error"|"unavailable", data: any, error: str|null}

``status`` is the machine-readable outcome the UI trigger button maps to:

  * ``ok``           — the action succeeded.
  * ``error``        — the action was attempted but failed (bad input, exception).
  * ``unavailable``  — the action could not run because a capability/dependency
                       is not configured (e.g. no LLM key, scraper libs missing,
                       vector store offline). Distinct from ``error`` so callers
                       can show "temporarily unavailable" vs. "it failed".

``success`` (bool) is kept for backward compatibility: it is ``True`` only when
``status == "ok"``.
"""

from __future__ import annotations

from typing import Any

# Public status constants.
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_UNAVAILABLE = "unavailable"


def ok(data: Any = None) -> dict[str, Any]:
    """Build a success envelope (``status == "ok"``).

    Args:
        data: The payload to return.

    Returns:
        A standard success response dict.
    """
    return {"success": True, "status": STATUS_OK, "data": data, "error": None}


def fail(error: str, data: Any = None) -> dict[str, Any]:
    """Build an error envelope (``status == "error"``).

    Args:
        error: Human-readable error message.
        data: Optional partial data.

    Returns:
        A standard error response dict.
    """
    return {"success": False, "status": STATUS_ERROR, "data": data, "error": error}


def unavailable(error: str, data: Any = None) -> dict[str, Any]:
    """Build an "unavailable" envelope (``status == "unavailable"``).

    Use when an action cannot run because a capability or dependency is not
    configured/reachable — not because the request itself was wrong.

    Args:
        error: Human-readable explanation of what is unavailable.
        data: Optional partial data (e.g. which capability is missing).

    Returns:
        A standard unavailable response dict.
    """
    return {
        "success": False,
        "status": STATUS_UNAVAILABLE,
        "data": data,
        "error": error,
    }
