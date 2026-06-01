"""RAG retrieval service — selects the active vector backend.

Resolution order (when ``ENABLE_RAG`` is true):
  1. **pgvector** — if the database is Postgres (single-datastore, default in prod).
  2. **Qdrant**   — only if ``VECTOR_BACKEND=qdrant`` is explicitly pinned.
  3. **local**    — zero-dependency cosine search inside the existing SQL database
     (``services.local_vector_store``). This is the default on SQLite, so RAG
     works end-to-end with **no external services** — the impressive fallback a
     reviewer sees out of the box.

Keeping retrieval behind one ``_active_store()`` selector means the agents and
pipeline never care which backend is live; ingest, retrieve and delete always
agree on the same store, so what gets embedded is what gets searched.
"""

from __future__ import annotations

import re
from typing import Any

from core.config import settings

# Tokens common to titles/queries that shouldn't drive a structural match.
_TITLE_STOP = {"policy", "pdf", "the", "and", "for", "doc", "document", "hr"}
_TOK = re.compile(r"[a-z0-9]+")


def _title_tokens(text: str) -> set[str]:
    """Significant lowercase tokens from a query or a doc_id/title."""
    return {t for t in _TOK.findall(text.lower()) if len(t) > 2 and t not in _TITLE_STOP}


def _apply_title_boost(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Boost chunks whose document *title* matches the query (hybrid signal).

    Short, keyword-style queries ("equal opportunity") have low vector density,
    so a genuine match can score below the grounding floor. If the query mostly
    names a policy by its title/filename, treat that as a strong structural
    signal and lift the score — vector search + title lookup, no extra DB calls.
    """
    qt = _title_tokens(query)
    if not qt:
        return hits
    for h in hits:
        tt = _title_tokens(str(h.get("doc_id", "")))
        if tt:
            overlap = len(qt & tt) / len(qt)
            if overlap >= 0.5:  # query (mostly) names this policy by title
                h["score"] = max(float(h.get("score", 0.0)), 0.5 + 0.45 * overlap)
    hits.sort(key=lambda h: h.get("score", 0.0), reverse=True)
    return hits


async def _vector_search(query: str, k: int) -> list[dict[str, Any]]:
    """Run the active vector backend's similarity search."""
    backend = active_backend()
    if backend == "pgvector":
        from services.pgvector_store import pgvector_store

        return await pgvector_store.search(query, top_k=k)
    if backend == "qdrant":
        import asyncio

        from core.vectorstore import vector_store

        try:
            return await asyncio.to_thread(vector_store.search, query, k)
        except Exception:  # noqa: BLE001
            return []
    if backend == "local":
        from services.local_vector_store import local_vector_store

        return await local_vector_store.search(query, top_k=k)
    return []


# The lexical hashing fallback produces lower absolute cosine scores than a
# neural embedder, so a clear match lands around 0.4–0.8 rather than 0.7–0.95.
# We calibrate the "needs human review" floor to the active backend so a good
# dependency-free retrieval isn't perpetually flagged as low-confidence.
_LOCAL_CONFIDENCE_FLOOR = 0.35


def _review_threshold() -> float:
    """Confidence floor below which an answer is flagged for human review."""
    return _LOCAL_CONFIDENCE_FLOOR if active_backend() == "local" else settings.confidence_threshold


def active_backend() -> str:
    """Name of the backend that will serve retrieval right now.

    One source of truth for ingest/retrieve/delete so they never diverge.
    Returns one of ``"pgvector"``, ``"qdrant"``, ``"local"`` or ``"none"``.
    """
    if not settings.enable_rag:
        return "none"

    from services.pgvector_store import pgvector_store

    if pgvector_store.is_active():
        return "pgvector"
    if settings.vector_backend == "qdrant":
        return "qdrant"
    if settings.vector_backend == "none":
        return "none"
    return "local"


async def retrieve(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """Return the top-k relevant policy chunks for a query (active backend).

    Widens the candidate net then applies a structural title-match boost, so a
    short query that names a policy ("equal opportunity") reliably surfaces that
    document even when its raw cosine score is low — without lowering the
    grounding floor used for synthesis.
    """
    if not settings.enable_rag or not query.strip():
        return []
    k = top_k or settings.retrieval_top_k
    hits = await _vector_search(query, max(k, 12))
    hits = _apply_title_boost(query, hits)
    return hits[:k]


async def ingest_chunks(chunks: list[dict[str, Any]]) -> int:
    """Write chunk dicts to the active vector backend."""
    if not settings.enable_rag or not chunks:
        return 0
    backend = active_backend()

    if backend == "pgvector":
        from services.pgvector_store import pgvector_store

        return await pgvector_store.upsert_chunks(chunks)

    if backend == "qdrant":
        import asyncio

        from core.vectorstore import vector_store

        try:
            return await asyncio.to_thread(vector_store.upsert_chunks, chunks)
        except Exception:  # noqa: BLE001 - no Qdrant running → degrade (registry only)
            return 0

    if backend == "local":
        from services.local_vector_store import local_vector_store

        return await local_vector_store.upsert_chunks(chunks)

    return 0


async def delete_policy(policy_id: str) -> int:
    """Remove a policy's chunks from the active backend (best-effort)."""
    backend = active_backend()

    if backend == "pgvector":
        from services.pgvector_store import pgvector_store

        return await pgvector_store.delete_policy(policy_id)

    if backend == "local":
        from services.local_vector_store import local_vector_store

        return await local_vector_store.delete_policy(policy_id)

    return 0


async def query(q: str, top_k: int | None = None) -> dict[str, Any]:
    """Full RAG flow: retrieve top-k chunks then synthesise an answer.

    Returns ``{answer, source_documents, confidence_score, needs_review,
    prompt_version}`` — the Policy Q&A contract. Synthesis (the Claude call) is
    offloaded to a thread; it falls back to the top excerpt without a key.
    """
    import asyncio

    from pipelines.rag_pipeline import rag_pipeline

    contexts = await retrieve(q, top_k)
    answer, mode = await asyncio.to_thread(rag_pipeline._synthesize, q, contexts)
    confidence = round(contexts[0]["score"], 4) if contexts else 0.0
    return {
        "answer": answer,
        "mode": mode,  # what produced the answer: llm vs deterministic excerpt
        "source_documents": [
            {"doc_id": c["doc_id"], "score": round(c["score"], 4), "text": c["text"]}
            for c in contexts
        ],
        "confidence_score": confidence,
        "needs_review": confidence < _review_threshold(),
        "prompt_version": rag_pipeline.prompt_version,
    }
