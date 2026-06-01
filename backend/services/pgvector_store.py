"""pgvector-backed vector store — keeps RAG inside Postgres (one datastore).

Instead of running a separate Qdrant service, policy chunks and their embeddings
live in a ``policy_chunks`` table with a ``vector`` column. Retrieval is a single
``ORDER BY embedding <=> query LIMIT k`` with an ivfflat index. This removes a
moving part for self-hosters (Postgres only) and scales fine for HR-sized corpora.

Embeddings come from the existing ``core.embeddings.embedder`` abstraction:
- no heavy deps installed  → deterministic 256-dim hashing embedding (works in the
  lean image / free tier; keyword-ish but functional),
- sentence-transformers installed → 384-dim MiniLM (real semantic search).

Everything is raw SQL via the shared async engine (string-cast vectors), so no
extra Python dependency beyond a Postgres server with the ``vector`` extension.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

import core.memory as core_memory
from core.config import settings
from core.embeddings import embedder


def _mem():
    """Resolve the current memory singleton (supports test rebinding)."""
    return core_memory.memory


def _vec_to_literal(vec: list[float]) -> str:
    """Format an embedding as a pgvector literal: ``[0.1,0.2,...]``."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


class PgVectorStore:
    """Postgres + pgvector implementation of the vector-store interface."""

    def __init__(self) -> None:
        self._ready = False
        self._dim: int | None = None

    def is_active(self) -> bool:
        """Whether pgvector should be used, given config + a Postgres backend."""
        if not settings.enable_rag:
            return False
        if settings.vector_backend == "qdrant" or settings.vector_backend == "none":
            return False
        return _mem().is_postgres  # auto + pgvector both require Postgres

    async def ensure_schema(self) -> bool:
        """Create the extension, table and index on first use.

        Returns ``True`` if pgvector is usable, ``False`` (degrade) otherwise.
        """
        if self._ready:
            return True
        if not self.is_active():
            return False
        dim = embedder.dimension
        try:
            async with _mem().engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                # Self-heal a dimension mismatch: if the table exists at a
                # different vector size (e.g. the embedding model changed), drop
                # and recreate it. Embeddings are derived data — re-ingestable
                # from the retained policy source_text — so this is safe and far
                # better than failing cryptically on every insert/search.
                existing_dim = (
                    await conn.execute(
                        text(
                            "SELECT a.atttypmod FROM pg_attribute a "
                            "JOIN pg_class c ON c.oid = a.attrelid "
                            "WHERE c.relname = 'policy_chunks' AND a.attname = 'embedding'"
                        )
                    )
                ).scalar()
                if existing_dim is not None and existing_dim != dim:
                    import logging

                    from core.config import settings

                    log = logging.getLogger("uvicorn.error")
                    if not settings.allow_destructive_reindex:
                        # Refuse to wipe live data implicitly. Degrade (return
                        # False → callers treat pgvector as unavailable and RAG
                        # falls back) and tell the operator how to recover.
                        log.error(
                            "policy_chunks vector dim %s != embedder dim %s. Refusing "
                            "to DROP the table (would erase live policy embeddings). "
                            "Run an explicit re-index, or set "
                            "ALLOW_DESTRUCTIVE_REINDEX=1 to permit the destructive "
                            "self-heal.",
                            existing_dim,
                            dim,
                        )
                        return False
                    log.warning(
                        "policy_chunks vector dim %s != embedder dim %s — "
                        "ALLOW_DESTRUCTIVE_REINDEX is set, recreating table; re-ingest "
                        "policies (Policies → Restore) to repopulate.",
                        existing_dim,
                        dim,
                    )
                    await conn.execute(text("DROP TABLE IF EXISTS policy_chunks"))
                await conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS policy_chunks ("
                        "id TEXT PRIMARY KEY, policy_id TEXT, chunk_index INT, "
                        f"chunk_text TEXT, embedding vector({dim}))"
                    )
                )
                # HNSW (not ivfflat): correct at any corpus size. ivfflat needs
                # training data and returns nothing on a near-empty table; HNSW
                # builds incrementally and is fast for HR-sized corpora.
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_policy_chunks_emb "
                        "ON policy_chunks USING hnsw (embedding vector_cosine_ops)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_policy_chunks_policy "
                        "ON policy_chunks(policy_id)"
                    )
                )
            self._dim = dim
            self._ready = True
            return True
        except Exception:  # noqa: BLE001 - degrade gracefully if pgvector absent
            return False

    async def upsert_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Embed and upsert chunk dicts ({text, doc_id, metadata{chunk_index}})."""
        if not await self.ensure_schema() or not chunks:
            return 0
        rows = []
        for c in chunks:
            idx = int(c.get("metadata", {}).get("chunk_index", 0))
            pid = c.get("doc_id", "unknown")
            rows.append(
                {
                    "id": f"{pid}:{idx}",
                    "pid": pid,
                    "idx": idx,
                    "txt": c["text"],
                    "emb": _vec_to_literal(embedder.embed(c["text"])),
                }
            )
        stmt = text(
            "INSERT INTO policy_chunks (id, policy_id, chunk_index, chunk_text, embedding) "
            "VALUES (:id, :pid, :idx, :txt, CAST(:emb AS vector)) "
            "ON CONFLICT (id) DO UPDATE SET "
            "chunk_text = EXCLUDED.chunk_text, embedding = EXCLUDED.embedding"
        )
        async with _mem().engine.begin() as conn:
            await conn.execute(stmt, rows)
        return len(rows)

    async def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Return the top-k most similar chunks (cosine) for a query."""
        if not await self.ensure_schema():
            return []
        k = top_k or settings.retrieval_top_k
        q = _vec_to_literal(embedder.embed(query))
        stmt = text(
            "SELECT chunk_text, policy_id, "
            "1 - (embedding <=> CAST(:q AS vector)) AS score "
            "FROM policy_chunks ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
        )
        async with _mem().engine.connect() as conn:
            rows = (await conn.execute(stmt, {"q": q, "k": k})).mappings().all()
        return [
            {"text": r["chunk_text"], "doc_id": r["policy_id"], "score": float(r["score"])}
            for r in rows
        ]

    async def delete_policy(self, policy_id: str) -> int:
        """Remove all chunks for a policy (keeps the vector store in sync)."""
        if not await self.ensure_schema():
            return 0
        async with _mem().engine.begin() as conn:
            res = await conn.execute(
                text("DELETE FROM policy_chunks WHERE policy_id = :p"), {"p": policy_id}
            )
        return res.rowcount or 0


pgvector_store = PgVectorStore()
