"""Two-node résumé analysis — extract structural history, then cross-validate it.

A small **in-process LangGraph pipeline** that runs alongside the Resume
Screener's scoring:

    extract ─▶ cross_validate ─▶ END

  * **extract** — pulls explicit employment *date ranges* out of the résumé text
    with conservative regex (no LLM).
  * **cross_validate** — checks those ranges for **internal logical
    inconsistencies** and emits advisory flags.

Honest scope (this is deliberate, not a limitation to hide):

  * It flags only **data-integrity anomalies** — a range that ends before it
    begins, a future-dated entry, or one role wholly contained inside another
    (possible concurrency to confirm). These indicate typos or fabricated
    timelines, which a reviewer can verify objectively.
  * It does **NOT** flag employment *gaps*. Gap-penalising adversely impacts
    caregiving and medical leave (a protected-class proxy — see MISSION /
    "blinding ≠ bias-proof"), so it's intentionally excluded.
  * It does **NOT** judge whether qualifications are "inflated" — no
    deterministic check can make that call honestly. Flags are **advisory**;
    they never change the score, only set ``needs_review`` for a human.

Same engineering guarantees as ``PolicyResolver``: runs off the event loop via
``asyncio.to_thread``, wrapped in a wall-clock timeout, and degrades to a plain
function if LangGraph isn't installed.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, TypedDict

# A year (1900–2099) … separator … a year or an "open" end (present/current/now).
_RANGE = re.compile(
    r"\b((?:19|20)\d{2})\s*(?:-|–|—|to|until|through)\s*"
    r"((?:19|20)\d{2}|present|current|now|ongoing)\b",
    re.IGNORECASE,
)
_MAX_SPANS = 60  # guard against pathological input


class ResumeAnalysisState(TypedDict):
    """State threaded through the analysis pipeline."""

    resume: str
    spans: list[dict[str, Any]]  # {start, end, open_ended, raw}
    flags: list[str]  # advisory consistency flags


class ResumeResolver:
    """Extracts a résumé's date history and cross-validates it for anomalies."""

    TIMEOUT_S = 10.0
    # Overlap shorter than this (years) is ignored — normal job transitions and
    # legitimate part-time/consulting concurrency shouldn't be flagged.
    MIN_OVERLAP_YEARS = 1

    def __init__(self) -> None:
        self._graph = self._build_graph()

    @staticmethod
    def _current_year() -> int:
        return datetime.now(timezone.utc).year

    # -- nodes ------------------------------------------------------------
    def _extract(self, state: ResumeAnalysisState) -> ResumeAnalysisState:
        """Parse explicit employment date ranges from the résumé text."""
        spans: list[dict[str, Any]] = []
        cur = self._current_year()
        for m in _RANGE.finditer(state["resume"]):
            start = int(m.group(1))
            end_raw = m.group(2).lower()
            open_ended = not end_raw.isdigit()
            end = cur if open_ended else int(end_raw)
            spans.append(
                {
                    "start": start,
                    "end": end,
                    "open_ended": open_ended,
                    "raw": m.group(0),
                }
            )
            if len(spans) >= _MAX_SPANS:
                break
        state["spans"] = spans
        return state

    def _cross_validate(self, state: ResumeAnalysisState) -> ResumeAnalysisState:
        """Emit advisory flags for internal logical inconsistencies only."""
        cur = self._current_year()
        flags: list[str] = []
        spans = state["spans"]

        for s in spans:
            if s["end"] < s["start"]:
                flags.append(
                    f"Date range '{s['raw']}' ends before it begins — likely a typo; verify."
                )
            if s["start"] > cur or (not s["open_ended"] and s["end"] > cur):
                flags.append(f"Entry '{s['raw']}' is dated in the future ({cur} now) — verify.")

        # One role wholly inside another → possible concurrency worth confirming
        # (conservative: only when one span strictly contains the other).
        for i, a in enumerate(spans):
            for b in spans[i + 1 :]:
                lo = max(a["start"], b["start"])
                hi = min(a["end"], b["end"])
                contains = (a["start"] <= b["start"] and a["end"] >= b["end"]) or (
                    b["start"] <= a["start"] and b["end"] >= a["end"]
                )
                if contains and (hi - lo) >= self.MIN_OVERLAP_YEARS:
                    flags.append(
                        f"Roles '{a['raw']}' and '{b['raw']}' overlap fully — "
                        "confirm whether concurrent."
                    )

        # De-duplicate while preserving order.
        state["flags"] = list(dict.fromkeys(flags))
        return state

    def _build_graph(self):
        """Compile the extract→cross_validate pipeline; None → plain-function path."""
        try:
            from langgraph.graph import END, StateGraph

            graph = StateGraph(ResumeAnalysisState)
            graph.add_node("extract", self._extract)
            graph.add_node("cross_validate", self._cross_validate)
            graph.set_entry_point("extract")
            graph.add_edge("extract", "cross_validate")
            graph.add_edge("cross_validate", END)
            return graph.compile()
        except Exception:  # noqa: BLE001 — langgraph absent → degrade to plain calls
            return None

    def _run_sequential(self, state: ResumeAnalysisState) -> ResumeAnalysisState:
        """The same pipeline without LangGraph (fallback path)."""
        return self._cross_validate(self._extract(state))

    # -- public API -------------------------------------------------------
    async def analyze(self, resume: str) -> dict[str, Any]:
        """Return ``{"flags": [...], "spans": [...]}`` for a résumé.

        Never raises: on timeout / any error it returns empty results so the
        screener's score is never blocked by the (advisory) consistency pass.
        """
        init: ResumeAnalysisState = {"resume": resume, "spans": [], "flags": []}
        runner = self._graph.invoke if self._graph is not None else self._run_sequential
        try:
            final = await asyncio.wait_for(asyncio.to_thread(runner, init), timeout=self.TIMEOUT_S)
        except Exception:  # noqa: BLE001 — advisory pass must never block scoring
            return {"flags": [], "spans": []}
        return {"flags": final["flags"], "spans": final["spans"]}


resume_resolver = ResumeResolver()
