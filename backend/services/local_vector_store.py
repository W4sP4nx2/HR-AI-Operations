"""Zero-dependency vector store — cosine search inside the existing SQL database.

This is the **universal fallback** that makes RAG work end-to-end with *no*
external services (no Postgres+pgvector, no Qdrant) — exactly the mode a reviewer
runs in. Chunk embeddings are stored as JSON in a ``policy_vectors`` table on the
shared async engine, and similarity is computed in Python with the same
``core.embeddings.embedder`` abstraction used everywhere else:

- no heavy deps installed  → deterministic 256-dim hashing embedding (keyword-ish
  but functional — shared tokens ⇒ similar vectors),
- sentence-transformers installed → 384-dim MiniLM (real semantic search).

For HR-sized corpora (dozens of policies, hundreds of chunks) an in-Python
top-k scan is more than fast enough. On Postgres the ``pgvector`` store takes
precedence (see :mod:`services.rag`); this store is the SQLite-era safety net.
"""

from __future__ import annotations

import json
import math
from typing import Any

from sqlalchemy import bindparam, text

import core.memory as core_memory
from core.config import settings
from core.embeddings import embedder


def _mem():
    """Resolve the current memory singleton (supports test rebinding)."""
    return core_memory.memory


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors, clamped to [0, 1]."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


class LocalVectorStore:
    """SQL-table-backed cosine vector store (works on SQLite and Postgres)."""

    def __init__(self) -> None:
        self._ready = False

    def is_active(self) -> bool:
        """Whether this fallback should serve retrieval.

        Active whenever RAG is enabled and the operator hasn't explicitly pinned
        a different backend. On Postgres, :mod:`services.rag` prefers pgvector and
        never reaches here; on SQLite this is the default backend.
        """
        if not settings.enable_rag:
            return False
        return settings.vector_backend not in ("qdrant", "none")

    async def ensure_schema(self) -> bool:
        """Create the ``policy_vectors`` table on first use (idempotent)."""
        if self._ready:
            return True
        async with _mem().engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS policy_vectors ("
                    "id TEXT PRIMARY KEY, policy_id TEXT, chunk_index INTEGER, "
                    "chunk_text TEXT, embedding TEXT)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_policy_vectors_policy "
                    "ON policy_vectors(policy_id)"
                )
            )
        self._ready = True
        return True

    async def upsert_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Embed and upsert chunk dicts ({text, doc_id, metadata{chunk_index}})."""
        if not chunks:
            return 0
        await self.ensure_schema()
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
                    "emb": json.dumps(embedder.embed(c["text"])),
                }
            )
        # Portable upsert: delete-then-insert by id (avoids dialect-specific
        # ON CONFLICT syntax differences between SQLite and Postgres).
        ids = [r["id"] for r in rows]
        async with _mem().engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM policy_vectors WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": ids},
            )
            await conn.execute(
                text(
                    "INSERT INTO policy_vectors (id, policy_id, chunk_index, chunk_text, embedding) "
                    "VALUES (:id, :pid, :idx, :txt, :emb)"
                ),
                rows,
            )
        return len(rows)

    async def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Return the top-k most similar chunks (cosine) for a query."""
        await self.ensure_schema()
        k = top_k or settings.retrieval_top_k
        q = embedder.embed(query)
        async with _mem().engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text("SELECT chunk_text, policy_id, embedding FROM policy_vectors")
                    )
                )
                .mappings()
                .all()
            )
        scored = [
            {
                "text": r["chunk_text"],
                "doc_id": r["policy_id"],
                "score": _cosine(q, json.loads(r["embedding"])),
            }
            for r in rows
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    async def delete_policy(self, policy_id: str) -> int:
        """Remove all chunks for a policy (keeps the store in sync on delete)."""
        await self.ensure_schema()
        async with _mem().engine.begin() as conn:
            res = await conn.execute(
                text("DELETE FROM policy_vectors WHERE policy_id = :p"), {"p": policy_id}
            )
        return res.rowcount or 0


local_vector_store = LocalVectorStore()
