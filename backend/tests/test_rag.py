"""Tests for the pgvector RAG backend + service selector.

The vector-literal formatting and backend selection are unit-tested on any DB.
The full pgvector round-trip is an integration test that **skips** unless a
Postgres-with-pgvector ``DATABASE_URL`` is provided (``RAG_TEST_DSN``).
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_vec_to_literal_format() -> None:
    from services.pgvector_store import _vec_to_literal

    assert _vec_to_literal([0.1, 0.2, -0.3]) == "[0.100000,0.200000,-0.300000]"
    assert _vec_to_literal([]) == "[]"


def test_pgvector_inactive_on_sqlite() -> None:
    """On the default SQLite DB, pgvector must report inactive (degrade path)."""
    from services.pgvector_store import pgvector_store

    assert pgvector_store.is_active() is False


def test_local_backend_active_on_sqlite() -> None:
    """On SQLite the zero-dependency local cosine store is the active backend."""
    from services import rag

    assert rag.active_backend() == "local"


def test_local_store_roundtrip(tmp_path) -> None:
    """The local fallback ingests chunks and retrieves the relevant one (no deps).

    Runs against an isolated temp SQLite DB so ranking is asserted against only
    the two chunks this test inserts (not whatever the dev DB happens to hold).
    """
    import core.memory as memmod
    import services.local_vector_store as lvs
    from services import rag

    fresh = memmod.Memory(str(tmp_path / "rag_test.db"))
    saved = memmod.memory
    saved_store = lvs.local_vector_store
    memmod.memory = fresh
    # Fresh store so its schema-ready cache binds to the temp engine, not the dev DB.
    lvs.local_vector_store = lvs.LocalVectorStore()
    try:

        async def scenario():
            await rag.ingest_chunks(
                [
                    {
                        "text": "Annual leave is 20 paid days per year for full-time staff.",
                        "doc_id": "leave",
                        "metadata": {"chunk_index": 0},
                    },
                    {
                        "text": "Remote work is permitted up to 3 days a week.",
                        "doc_id": "remote",
                        "metadata": {"chunk_index": 0},
                    },
                ]
            )
            return await rag.retrieve("how many vacation days do I get", top_k=2)

        hits = asyncio.run(scenario())
    finally:
        memmod.memory = saved
        lvs.local_vector_store = saved_store

    # Synonym-aware lexical retrieval should rank the leave policy first.
    assert hits and hits[0]["doc_id"] == "leave"
    assert hits[0]["score"] > 0.0


def test_service_query_shape() -> None:
    """rag.query returns the full Policy Q&A contract, with citable source text."""
    from services import rag

    res = asyncio.run(rag.query("vacation policy"))
    assert {"answer", "source_documents", "confidence_score", "needs_review"} <= set(res)
    assert isinstance(res["needs_review"], bool)
    # Sources now carry the excerpt text so the UI can render citation snippets.
    if res["source_documents"]:
        assert "text" in res["source_documents"][0]


def test_enable_rag_flag_off_returns_empty(monkeypatch) -> None:
    from core.config import settings
    from services import rag

    monkeypatch.setattr(settings, "enable_rag", False)
    assert asyncio.run(rag.retrieve("anything")) == []
    assert asyncio.run(rag.ingest_chunks([{"text": "x", "doc_id": "d"}])) == 0


@pytest.mark.skipif(
    not os.environ.get("RAG_TEST_DSN"),
    reason="set RAG_TEST_DSN to a postgres+pgvector DSN to run the integration test",
)
def test_pgvector_roundtrip_integration() -> None:
    """End-to-end: ensure schema, upsert chunks, retrieve the relevant one."""
    import core.memory as memmod
    import services.pgvector_store as pg

    fresh = memmod.Memory(os.environ["RAG_TEST_DSN"])
    saved = memmod.memory
    memmod.memory = fresh
    pg.pgvector_store = pg.PgVectorStore()
    try:

        async def scenario():
            store = pg.pgvector_store
            assert await store.ensure_schema() is True
            await store.upsert_chunks(
                [
                    {
                        "text": "Remote work is allowed 3 days a week.",
                        "doc_id": "remote",
                        "metadata": {"chunk_index": 0},
                    },
                    {
                        "text": "Annual leave is 20 days per year.",
                        "doc_id": "leave",
                        "metadata": {"chunk_index": 0},
                    },
                ]
            )
            hits = await store.search("how many days remote", top_k=1)
            assert hits and hits[0]["doc_id"] == "remote"
            await store.delete_policy("remote")

        asyncio.run(scenario())
    finally:
        memmod.memory = saved


@pytest.mark.skipif(
    not os.environ.get("RAG_TEST_DSN"),
    reason="set RAG_TEST_DSN to a postgres+pgvector DSN to run the integration test",
)
def test_pgvector_dimension_self_heal() -> None:
    """A stale table at the wrong vector dim is recreated, not failed on insert."""
    from sqlalchemy import text

    import core.memory as memmod
    import services.pgvector_store as pg
    from core.embeddings import embedder

    fresh = memmod.Memory(os.environ["RAG_TEST_DSN"])
    saved = memmod.memory
    memmod.memory = fresh
    pg.pgvector_store = pg.PgVectorStore()
    try:

        async def scenario():
            wrong = 1 if embedder.dimension != 1 else 2  # any dim != the real one
            async with fresh.engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.execute(text("DROP TABLE IF EXISTS policy_chunks"))
                await conn.execute(
                    text(
                        "CREATE TABLE policy_chunks (id TEXT PRIMARY KEY, policy_id TEXT, "
                        f"chunk_index INT, chunk_text TEXT, embedding vector({wrong}))"
                    )
                )
            # ensure_schema (via upsert) must detect the mismatch and recreate.
            n = await pg.pgvector_store.upsert_chunks(
                [
                    {
                        "text": "Annual leave is 20 days",
                        "doc_id": "leave",
                        "metadata": {"chunk_index": 0},
                    }
                ]
            )
            assert n == 1
            hits = await pg.pgvector_store.search("vacation days", top_k=1)
            assert hits and hits[0]["doc_id"] == "leave"
            await pg.pgvector_store.delete_policy("leave")

        asyncio.run(scenario())
    finally:
        memmod.memory = saved
