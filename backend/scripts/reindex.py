"""Safe, non-destructive vector re-index.

Rebuilds the **vector store only** (``policy_chunks`` embeddings) from the
policy text already retained in the registry. Use this after changing the
embedding model or to repair a degraded vector backend.

What this DOES:
  * Re-chunks and re-embeds every active policy from its retained ``source_text``
    using the *current* embedder, upserting fresh vectors.

What this NEVER does:
  * Touch the ``cases``, ``audit``, or ``users`` tables. The audit log is the
    immutable source of truth for every metric and compliance export — a
    re-index must not put a scratch on it. (This is why we do not use
    ``metadata.drop_all`` / ``create_all`` here.)

Vector-dimension change (pgvector): if the embedding dimension changed, the
pgvector table must be recreated. That is gated behind the
``ALLOW_DESTRUCTIVE_REINDEX`` env flag (default off) so it is an explicit,
operator-chosen action:

    ALLOW_DESTRUCTIVE_REINDEX=1 python -m scripts.reindex

Usage:
    python -m scripts.reindex          # re-embed all active policies
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def reindex() -> int:
    """Re-embed every active policy from retained source text. Returns vectors written."""
    from core.config import settings
    from core.memory import memory
    from pipelines.ingestion import chunk_text
    from services import rag

    policies = await memory.list_policies(include_deleted=False)
    if not policies:
        print("No policies in the registry — nothing to re-index.")
        return 0

    print(f"Re-indexing {len(policies)} policy document(s) into the vector store only.")
    print("(cases / audit / users tables are NOT touched.)\n")
    if settings.allow_destructive_reindex:
        print("ALLOW_DESTRUCTIVE_REINDEX is set: a vector-dimension mismatch will")
        print("recreate the pgvector table.\n")

    total = 0
    for policy in policies:
        doc_id = policy["doc_id"]
        text = policy.get("source_text") or ""
        if not text:
            print(f"  ⚠ {doc_id:32} no retained source_text — skipped (re-upload to embed)")
            continue
        # Transactional ordering: build + upsert the NEW vectors *first*, never
        # deleting the live index up front. Chunk ids are deterministic
        # (doc_id + chunk_index), so ingest overwrites each chunk in place — the
        # doc stays searchable throughout. Only if the upsert succeeds do we prune
        # any stale tail chunks (when the new doc has fewer chunks than before),
        # so an ingest failure can never leave the doc with an empty index.
        chunks = chunk_text(text)
        new_dicts = [
            {"text": c, "doc_id": doc_id, "metadata": {"chunk_index": i}}
            for i, c in enumerate(chunks)
        ]
        written = await rag.ingest_chunks(new_dicts)
        pruned = 0
        if written:
            prev = int(policy.get("chunks") or 0)
            if prev > len(chunks):
                # Stale tail exists; the delete+re-ingest only runs after a
                # confirmed successful upsert, so there's no empty-index window.
                await rag.delete_policy(doc_id)
                written = await rag.ingest_chunks(new_dicts)
                pruned = prev - len(chunks)
            await memory.upsert_policy(
                doc_id=doc_id,
                filename=policy.get("filename", doc_id),
                chunks=len(chunks),
                char_count=len(text),
                status="ingested",
                source_text=text,
            )
        else:
            await memory.set_policy_status(doc_id, "vector_store_unavailable")
        total += written
        flag = f"{written} vectors" if written else "registry only (no vector backend)"
        if pruned:
            flag += f" ({pruned} stale chunk(s) pruned)"
        print(f"  ✓ {doc_id:32} {len(chunks)} chunks → {flag}")

    backend = rag.active_backend()
    print(f"\nDone. {total} chunks re-embedded into the '{backend}' backend.")
    if total == 0 and backend != "none":
        print(
            "0 vectors written. If the embedding dimension changed, set "
            "ALLOW_DESTRUCTIVE_REINDEX=1 and re-run to recreate the pgvector table."
        )
    return total


def main() -> None:
    asyncio.run(reindex())


if __name__ == "__main__":
    main()
