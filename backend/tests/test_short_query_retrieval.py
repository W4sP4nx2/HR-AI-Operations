"""Regression tests for the short / keyword-style query retrieval miss.

Reproduces the reported bug: a loaded ``equal_opportunity`` policy was missed by
the shorthand query "equal opportunity" — the chat fallback never even searched
(it gated on a fixed keyword list), and short queries have low vector density.
"""

from __future__ import annotations

import asyncio


def test_title_boost_ranks_named_policy_first() -> None:
    """A short query naming a policy by title surfaces it via the structural boost."""
    from services import rag

    async def scenario():
        await rag.ingest_chunks(
            [
                {
                    "text": "Equal Opportunity Policy. The company hires and promotes without "
                    "regard to race, gender, age, disability or marital status.",
                    "doc_id": "equal_opportunity",
                    "metadata": {"chunk_index": 0},
                },
                {
                    "text": "Annual leave is 20 days per year for full-time staff.",
                    "doc_id": "annual_leave_policy",
                    "metadata": {"chunk_index": 0},
                },
            ]
        )
        return await rag.retrieve("equal opportunity", top_k=3)

    hits = asyncio.run(scenario())
    assert hits and hits[0]["doc_id"] == "equal_opportunity"
    assert hits[0]["score"] >= 0.5  # lifted by the title-match boost, not raw cosine


def test_short_query_routes_to_policy_search() -> None:
    """The chat fallback now treats an unrecognised fragment as a policy search."""
    from agents.chat_agent import _fallback_chat
    from services import rag

    async def scenario():
        await rag.ingest_chunks(
            [
                {
                    "text": "Equal Opportunity Policy. Hires without regard to race or gender.",
                    "doc_id": "equal_opportunity",
                    "metadata": {"chunk_index": 0},
                }
            ]
        )
        return await _fallback_chat("equal opportunity")

    r = asyncio.run(scenario())
    assert r["tool_calls"] and r["tool_calls"][0]["tool"] == "search_policy"
    assert any(c["doc_id"] == "equal_opportunity" for c in r["citations"])


def test_offtopic_query_gets_helper_not_a_random_policy() -> None:
    """Off-topic input must fall to the capability helper, not surface a stray excerpt."""
    from agents.chat_agent import _fallback_chat

    r = asyncio.run(_fallback_chat("hello there how are you today"))
    assert "can help with" in r["reply"]
    assert not r["citations"]
