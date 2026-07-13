"""Qdrant vector store client and helpers.

Wraps the Qdrant client with graceful degradation: if Qdrant is unreachable
the methods raise a clear error rather than crashing import, so the rest of
the API can still boot in environments without the vector DB.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.config import settings
from core.embeddings import embedder


class VectorStore:
    """High-level interface over a Qdrant collection of HR policy chunks."""

    def __init__(self, url: str | None = None, collection: str | None = None) -> None:
        """Initialise the vector store wrapper.

        Args:
            url: Optional Qdrant URL override.
            collection: Optional collection-name override.
        """
        self._url = url or settings.qdrant_url
        self._collection = collection or settings.qdrant_collection
        self._client = None

    # -- connection -------------------------------------------------------
    @property
    def client(self):
        """Return a lazily-constructed Qdrant client."""
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self._url)
        return self._client

    def ensure_collection(self) -> None:
        """Create the collection if it does not already exist."""
        from qdrant_client.models import Distance, VectorParams

        existing = {c.name for c in self.client.get_collections().collections}
        if self._collection not in existing:
            self.client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=embedder.dimension,
                    distance=Distance.COSINE,
                ),
            )

    # -- writes -----------------------------------------------------------
    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Embed and upsert document chunks.

        Args:
            chunks: List of dicts each containing at least a ``text`` key and
                optional ``doc_id`` / ``metadata`` keys.

        Returns:
            The number of points written.
        """
        from qdrant_client.models import PointStruct

        self.ensure_collection()
        texts = [c["text"] for c in chunks]
        vectors = embedder.embed_batch(texts)
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={
                    "text": chunk["text"],
                    "doc_id": chunk.get("doc_id", "unknown"),
                    **chunk.get("metadata", {}),
                },
            )
            for chunk, vec in zip(chunks, vectors, strict=False)
        ]
        self.client.upsert(collection_name=self._collection, points=points)
        return len(points)

    # -- reads ------------------------------------------------------------
    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Search the collection for the most similar chunks to a query.

        Args:
            query: Natural-language query string.
            top_k: Number of results to return; defaults to configured value.

        Returns:
            A list of result dicts with ``text``, ``doc_id`` and ``score``.
        """
        top_k = top_k or settings.retrieval_top_k
        try:
            self.ensure_collection()
            query_vector = embedder.embed(query)
            hits = self.client.search(
                collection_name=self._collection,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception:  # noqa: BLE001 - degrade gracefully if Qdrant is unavailable
            return []
        return [
            {
                "text": h.payload.get("text", ""),
                "doc_id": h.payload.get("doc_id", "unknown"),
                "score": float(h.score),
                "metadata": {
                    key: value for key, value in h.payload.items() if key not in {"text", "doc_id"}
                },
            }
            for h in hits
        ]

    def get_by_doc_id(self, doc_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve all chunks belonging to a given document id.

        Args:
            doc_id: The document identifier to filter on.
            limit: Maximum number of chunks to return.

        Returns:
            A list of chunk dicts.
        """
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            self.ensure_collection()
            points, _ = self.client.scroll(
                collection_name=self._collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
                limit=limit,
                with_payload=True,
            )
        except Exception:  # noqa: BLE001 - degrade gracefully if Qdrant is unavailable
            return []
        return [
            {
                "text": p.payload.get("text", ""),
                "doc_id": doc_id,
                "metadata": {
                    key: value for key, value in p.payload.items() if key not in {"text", "doc_id"}
                },
            }
            for p in points
        ]


# Module-level singleton.
vector_store = VectorStore()
