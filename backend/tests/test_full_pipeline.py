"""End-to-end tests for the full pipeline fixes and the seed data.

Covers:
  * RAGPipeline.ingest_chunks (public API used by the policy route).
  * chat_agent tool-call extraction helper against synthetic messages.
  * Improved fallback intent routing (list cases vs. triage).
  * The seed PDF generator + extraction round-trip.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_rag_ingest_chunks_public_api() -> None:
    """ingest_chunks exists and returns 0 for empty input without a vector store."""
    from pipelines.rag_pipeline import rag_pipeline

    assert rag_pipeline.ingest_chunks([]) == 0


def test_extract_tool_calls_from_parts() -> None:
    """_extract_tool_calls reads tool_name off ToolCallPart-like objects."""
    from agents.chat_agent import _extract_tool_calls

    class Part:
        def __init__(self, kind, name=None, args=None):
            self.part_kind = kind
            self.tool_name = name
            self.args = args or {}

    class Msg:
        def __init__(self, parts):
            self.parts = parts

    class Result:
        def all_messages(self):
            return [
                Msg([Part("text")]),
                Msg([Part("tool-call", "search_policy", {"query": "leave"})]),
                Msg([Part("tool-call", "triage_ticket", {})]),
            ]

    calls = _extract_tool_calls(Result())
    names = [c["tool"] for c in calls]
    assert names == ["search_policy", "triage_ticket"]
    assert calls[0]["args"] == {"query": "leave"}


def test_fallback_routes_list_cases_not_triage() -> None:
    """'list open urgent cases' routes to list_open_cases, not triage_ticket."""
    from agents.chat_agent import _fallback_chat

    result = asyncio.run(_fallback_chat("List all open urgent cases"))
    assert result["tool_calls"][0]["tool"] == "list_open_cases"


def test_fallback_case_lookup_by_id() -> None:
    """A message containing a case id routes to get_case_status."""
    from agents.chat_agent import _fallback_chat

    result = asyncio.run(_fallback_chat("what is the status of CASE-ABCD1234?"))
    assert result["tool_calls"][0]["tool"] == "get_case_status"


def test_seed_pdf_roundtrip() -> None:
    """The seed PDF generator produces text-extractable PDFs."""
    from pipelines.intake import extract_text_from_pdf_bytes
    from scripts.seed_data import SAMPLE_POLICIES, make_pdf

    text = next(iter(SAMPLE_POLICIES.values()))
    pdf = make_pdf(text)
    extracted = extract_text_from_pdf_bytes(pdf)
    # First few distinctive words should survive the round-trip.
    assert "Annual" in extracted or "Leave" in extracted or "leave" in extracted.lower()


def test_seed_tickets_cover_categories() -> None:
    """The sample tickets include at least one URGENT and one policy question."""
    from scripts.seed_data import SAMPLE_TICKETS

    joined = " ".join(SAMPLE_TICKETS).lower()
    assert "urgent" in joined
    assert "policy" in joined or "vacation" in joined or "remote" in joined
    assert len(SAMPLE_TICKETS) >= 5
