"""Optional LangSmith cost attribution for governed agent steps."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

COST_PER_1K_TOKENS = {
    "economy": 0.0002,
    "standard": 0.0009,
    "premium": 0.0009,
}


def redact_trace_text(value: str) -> dict[str, Any]:
    """Return stable trace metadata without exporting user text or PII."""
    text = str(value or "")
    scrubbed = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email]", text)
    scrubbed = re.sub(r"\b(?:\+?\d[\d ()-]{7,}\d)\b", "[phone]", scrubbed)
    return {
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "text_chars": len(text),
        "redaction_applied": scrubbed != text,
    }


def trace_payload_metadata(value: Any) -> dict[str, Any]:
    """Describe a payload for tracing without exporting any raw HR values."""
    encoded = json.dumps(value, sort_keys=True, default=str)
    return {
        "payload_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16],
        "payload_chars": len(encoded),
        "top_level_keys": sorted(value) if isinstance(value, dict) else [],
        "raw_payload_sent": False,
    }


def langsmith_configured() -> bool:
    """Return whether current or legacy LangSmith tracing env is enabled."""
    key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    flag = os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2")
    return bool(key) and str(flag or "").strip().lower() in {"1", "true", "yes"}


class HierarchicalTrace:
    """Best-effort nested LangSmith trace for manager and worker steps.

    The trace only receives hashes, sizes, identifiers, and status fields. Raw
    resumes, tickets, policy text, names, and contact information never leave
    the application through this integration.
    """

    def __init__(
        self,
        *,
        name: str,
        orchestration_id: str,
        inputs: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._root: Any | None = None
        if not langsmith_configured():
            return
        try:
            from langsmith.run_trees import RunTree

            self._root = RunTree(
                name=name,
                run_type="chain",
                inputs=trace_payload_metadata(inputs),
                extra={
                    "metadata": {
                        "orchestration_id": orchestration_id,
                        "raw_payload_sent": False,
                        **(metadata or {}),
                    }
                },
                project_name=os.environ.get("LANGSMITH_PROJECT", "govern-ai-crewai"),
            )
            self._root.post()
        except Exception:  # noqa: BLE001 - tracing must never break orchestration
            self._root = None

    def record_step(self, agent_id: str, output: dict[str, Any]) -> None:
        if self._root is None:
            return
        try:
            child = self._root.create_child(
                name=f"worker_{agent_id}",
                run_type="chain",
                inputs={"agent_id": agent_id, "raw_payload_sent": False},
            )
            child.post()
            child.end(outputs=trace_payload_metadata(output))
            child.patch()
        except Exception:  # noqa: BLE001
            return

    def finish(self, output: dict[str, Any]) -> None:
        if self._root is None:
            return
        try:
            self._root.end(outputs=trace_payload_metadata(output))
            self._root.patch()
        except Exception:  # noqa: BLE001
            return


@dataclass(frozen=True)
class CostAttribution:
    tier: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cost_per_1k: float


def estimate_cost_usd(tier: str, tokens_in: int, tokens_out: int) -> CostAttribution:
    """Return deterministic approximate spend for one agent step."""
    normalized_tier = tier if tier in COST_PER_1K_TOKENS else "standard"
    cost_per_1k = COST_PER_1K_TOKENS[normalized_tier]
    total_tokens = max(0, tokens_in) + max(0, tokens_out)
    return CostAttribution(
        tier=normalized_tier,
        tokens_in=max(0, tokens_in),
        tokens_out=max(0, tokens_out),
        cost_usd=round((total_tokens / 1000) * cost_per_1k, 6),
        cost_per_1k=cost_per_1k,
    )


class CostAwareTracer:
    """Best-effort LangSmith bridge; never required for local/no-key tests."""

    def trace_agent_step(
        self,
        *,
        name: str,
        query: str,
        tier: str,
        tokens_in: int,
        tokens_out: int,
        metadata: dict[str, Any] | None = None,
    ) -> CostAttribution:
        attribution = estimate_cost_usd(tier, tokens_in, tokens_out)
        trace_name = f"{name}_{attribution.tier}"
        try:
            from langsmith import Client

            Client().create_run(
                name=trace_name,
                run_type="chain",
                inputs={"query": redact_trace_text(query)},
                outputs={
                    "cost_usd": attribution.cost_usd,
                    "tier": attribution.tier,
                },
                metadata={
                    "tokens_in": attribution.tokens_in,
                    "tokens_out": attribution.tokens_out,
                    "cost_per_1k": attribution.cost_per_1k,
                    "tier": attribution.tier,
                    **(metadata or {}),
                },
            )
        except Exception:  # noqa: BLE001 - cost telemetry cannot break product flow
            pass
        return attribution
