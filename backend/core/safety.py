"""Safety & observability helpers: PII redaction, prompt hashing, structured audit.

These are deliberately small, dependency-free utilities so they can wrap every
tool call and audit write without adding latency or heavy deps.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from core.config import settings

# --------------------------------------------------------------------------- #
# PII redaction
# --------------------------------------------------------------------------- #

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{7,}\d)(?!\d)")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _regex_redact(text: str) -> str:
    """Regex PII redaction (the default, dependency-free engine)."""
    text = _EMAIL.sub("[redacted-email]", text)
    text = _SSN.sub("[redacted-ssn]", text)
    text = _CC.sub("[redacted-card]", text)
    text = _IP.sub("[redacted-ip]", text)
    text = _PHONE.sub("[redacted-phone]", text)
    return text


def _presidio_redact(text: str) -> str:
    """Microsoft Presidio redaction (NER-based: also catches names/locations).

    Activated by ``PII_ENGINE=presidio`` *and* presidio being installed; falls
    back to regex if the import or analysis fails so the app never breaks.
    """
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        analyzer = _get_presidio_analyzer(AnalyzerEngine)
        results = analyzer.analyze(text=text, language="en")
        anonymized = AnonymizerEngine().anonymize(text=text, analyzer_results=results)
        return anonymized.text
    except Exception:  # noqa: BLE001 - degrade to regex, never crash on PII path
        return _regex_redact(text)


_PRESIDIO_ANALYZER = None


def _get_presidio_analyzer(cls):
    """Cache the (expensive) Presidio analyzer engine."""
    global _PRESIDIO_ANALYZER
    if _PRESIDIO_ANALYZER is None:
        _PRESIDIO_ANALYZER = cls()
    return _PRESIDIO_ANALYZER


def redact_pii(text: str) -> str:
    """Mask PII in ``text`` using the configured engine.

    Engines:
      * ``regex`` (default) — emails, phones, SSNs, cards, IPs. Zero deps.
      * ``presidio`` — adds NER (names, locations, …) when presidio is installed.

    No-op when ``settings.redact_pii`` is False. Applied before writing free text
    to the audit log, chat history, and (optionally) before external tool calls.
    """
    if not settings.redact_pii or not text:
        return text
    if settings.pii_engine == "presidio":
        return _presidio_redact(text)
    return _regex_redact(text)


def redact_obj(obj: Any) -> Any:
    """Recursively redact strings inside dicts/lists for structured audit values."""
    if isinstance(obj, str):
        return redact_pii(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# Prompt hashing (drift detection)
# --------------------------------------------------------------------------- #


def prompt_hash(prompt: str) -> str:
    """Return a short stable hash of a prompt template (for audit / drift checks)."""
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Structured audit event
# --------------------------------------------------------------------------- #


def audit_event(
    step: str,
    tool: str | None = None,
    input_data: Any = None,
    output_data: Any = None,
    fallback: bool | None = None,
    confidence: float | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """Build a standardized, PII-redacted audit event payload.

    Schema: ``{step, tool, input, output, fallback, confidence, prompt_version,
    timestamp}`` — a consistent shape that makes tool-call failures debuggable.
    """
    return {
        "step": step,
        "tool": tool,
        "input": redact_obj(input_data),
        "output": redact_obj(output_data),
        "fallback": fallback,
        "confidence": confidence,
        "prompt_version": prompt_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------- #
# Tiny LRU cache (policy answers / tool outputs in demo mode)
# --------------------------------------------------------------------------- #


class LRUCache:
    """A minimal size-bounded LRU cache keyed by string, with optional TTL.

    ``ttl_seconds=0`` (default) means entries never expire; a positive value
    expires entries after that many seconds (wired to ``SEMANTIC_CACHE_TTL`` so
    cached RAG answers stay correct as policies change).
    """

    def __init__(self, maxsize: int = 32, ttl_seconds: int = 0) -> None:
        self._maxsize = max(1, maxsize)
        self._ttl = max(0, ttl_seconds)
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def _now(self) -> float:
        import time

        return time.monotonic()

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        ts, value = entry
        if self._ttl and self._now() - ts > self._ttl:
            del self._data[key]  # expired
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (self._now(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


def cache_key(*parts: str) -> str:
    """Build a stable cache key from parts."""
    return "sha256:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
