"""Agentic policy resolution — a bounded, self-correcting RAG loop.

This is the *agency* layer for the POLICY auto-resolve path. Instead of a single
straight-line RAG call, it runs a small **in-process LangGraph state machine**:

    retrieve ─grade─▶ accept (confidence cleared the floor, or out of attempts)
        ▲              │
        └─ reformulate ◀ retry (low confidence → widen the query and try again)

Why in-process and bounded (not a distributed event bus):

  * It runs inside the API process, off the event loop (the caller invokes it via
    ``asyncio.to_thread``), so it adds **zero new infrastructure** — consistent
    with the project's "runs on a laptop, zero external services" guarantee.
  * The loop is **hard-bounded** by ``max_attempts`` and wrapped in a wall-clock
    ``TIMEOUT_S``, and on any failure it falls back to a single deterministic
    pass — so a volatile agent loop can never block the event loop or spin
    forever (the failure mode that *would* justify decoupling).
  * It does **not** change triage's routing contract: POLICY still auto-resolves.
    The loop improves the *answer*; it does not hijack resolved/escalated routing
    (that's a product decision, and the metrics tests pin it).

It degrades gracefully if LangGraph isn't installed (mirrors OnboardingAgent):
the same logic runs as a plain Python loop.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, TypedDict

from pipelines.rag_pipeline import rag_pipeline
from services.rag import _review_threshold

# Words that carry no retrieval signal — stripped during query reformulation so
# the second pass leads with policy-bearing nouns ("remote work" not "what is").
_STOP = {
    "what",
    "is",
    "the",
    "a",
    "an",
    "are",
    "how",
    "do",
    "i",
    "to",
    "of",
    "for",
    "where",
    "can",
    "find",
    "my",
    "our",
    "in",
    "on",
    "about",
    "please",
    "tell",
    "me",
    "this",
    "that",
    "and",
    "or",
    "with",
    "when",
    "which",
    "you",
}


class PolicyState(TypedDict):
    """State threaded through the resolution graph."""

    query: str  # the query for the current attempt (reformulated on retry)
    original: str  # the untouched user query (reformulation source)
    attempt: int  # 1-based attempt counter
    max_attempts: int  # hard cap on retrieval attempts
    best: dict[str, Any] | None  # highest-confidence resolution seen so far
    trace: list[dict[str, Any]]  # node-by-node steps (for the UI execution trace)


class PolicyResolver:
    """Runs the bounded retrieve→grade→reformulate loop for POLICY tickets."""

    MAX_ATTEMPTS = 2  # one initial pass + one reformulated retry
    TIMEOUT_S = 20.0  # wall-clock guard around the whole graph

    def __init__(self) -> None:
        self._graph = self._build_graph()

    # -- graph nodes (sync; rag_pipeline.query is synchronous) ------------
    def _retrieve(self, state: PolicyState) -> PolicyState:
        """Run one RAG pass and keep it if it's the best confidence so far."""
        res = rag_pipeline.query(state["query"])
        conf = float(res.get("confidence_score", 0.0))
        best = state["best"]
        if best is None or conf > float(best.get("confidence_score", 0.0)):
            state["best"] = res
        state["trace"].append(
            {
                "step": "retrieve",
                "attempt": state["attempt"],
                "query": state["query"],
                "confidence": conf,
                "chunks": len(res.get("source_documents", [])),
            }
        )
        return state

    def _reformulate(self, state: PolicyState) -> PolicyState:
        """Widen the query (strip filler, lead with policy nouns) and try again."""
        state["attempt"] += 1
        new_query = self._reformulate_query(state["original"])
        state["query"] = new_query
        state["trace"].append(
            {
                "step": "reformulate",
                "attempt": state["attempt"],
                "query": new_query,
                "reason": "confidence below floor — widening the query",
            }
        )
        return state

    def _grade(self, state: PolicyState) -> str:
        """Conditional edge: accept a good-enough answer, else retry (bounded)."""
        best = state["best"]
        conf = float(best.get("confidence_score", 0.0)) if best else 0.0
        if conf >= _review_threshold() or state["attempt"] >= state["max_attempts"]:
            return "accept"
        return "retry"

    @staticmethod
    def _reformulate_query(original: str) -> str:
        """Deterministic, zero-dep query expansion (no LLM)."""
        tokens = [t for t in re.findall(r"[a-z0-9]+", original.lower()) if t not in _STOP]
        base = " ".join(tokens).strip() or original.strip()
        return f"{base} policy guidelines"

    def _build_graph(self):
        """Compile the resolution loop; return None to fall back to a plain loop."""
        try:
            from langgraph.graph import END, StateGraph

            graph = StateGraph(PolicyState)
            graph.add_node("retrieve", self._retrieve)
            graph.add_node("reformulate", self._reformulate)
            graph.set_entry_point("retrieve")
            graph.add_conditional_edges(
                "retrieve", self._grade, {"accept": END, "retry": "reformulate"}
            )
            graph.add_edge("reformulate", "retrieve")
            return graph.compile()
        except Exception:  # noqa: BLE001 — langgraph absent → degrade to plain loop
            return None

    def _run_sequential(self, state: PolicyState) -> PolicyState:
        """The same bounded loop without LangGraph (fallback path)."""
        while True:
            state = self._retrieve(state)
            if self._grade(state) == "accept":
                return state
            state = self._reformulate(state)

    # -- public API -------------------------------------------------------
    async def resolve(self, query: str) -> dict[str, Any]:
        """Resolve a POLICY query through the bounded loop.

        Returns ``{"resolution": <best RAG result>, "trace": [...steps]}``.
        Never raises: on timeout / any error it returns a single deterministic
        RAG pass so triage always gets an answer.
        """
        init: PolicyState = {
            "query": query,
            "original": query,
            "attempt": 1,
            "max_attempts": self.MAX_ATTEMPTS,
            "best": None,
            "trace": [],
        }
        runner = self._graph.invoke if self._graph is not None else self._run_sequential
        try:
            final = await asyncio.wait_for(asyncio.to_thread(runner, init), timeout=self.TIMEOUT_S)
        except Exception:  # noqa: BLE001 — timeout or loop error → safe single pass
            res = await asyncio.to_thread(rag_pipeline.query, query)
            return {
                "resolution": res,
                "trace": [
                    {
                        "step": "retrieve",
                        "attempt": 1,
                        "query": query,
                        "confidence": float(res.get("confidence_score", 0.0)),
                        "chunks": len(res.get("source_documents", [])),
                        "note": "fallback (loop unavailable)",
                    }
                ],
            }
        best = final["best"] or await asyncio.to_thread(rag_pipeline.query, query)
        return {"resolution": best, "trace": final["trace"]}


policy_resolver = PolicyResolver()
