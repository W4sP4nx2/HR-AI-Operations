"""Retrieval-Augmented Generation pipeline over HR policy documents.

Combines:
  * ingestion (pypdf + chunking) from :mod:`pipelines.ingestion`,
  * embeddings (local or Fireworks, depending on environment),
  * vector storage and cosine retrieval (Qdrant, top-k=5),
  * answer synthesis via the configured live provider.

The pipeline degrades gracefully: if the live provider or vector store is unavailable it still
returns retrieved context so callers can decide how to proceed.
"""

from __future__ import annotations

import re
from typing import Any

from agents.prompts import POLICY_RAG
from core.config import settings
from core.vectorstore import vector_store
from pipelines.ingestion import ingest_directory, ingest_pdf


class RAGPipeline:
    """End-to-end RAG pipeline for HR policy question answering."""

    # The synthesis prompt is hashed into the audit trail for drift detection.
    # Strict "context-or-null" grounding: the model must answer ONLY from the
    # provided policy chunks and must refuse rather than use training knowledge.
    SYNTHESIS_PROMPT_TEMPLATE = POLICY_RAG.text

    # Below this top-retrieval cosine score we treat the context as too weak to
    # ground an LLM answer and fall back to the verbatim excerpt instead of
    # risking a fabricated synthesis.
    GROUNDING_FLOOR = 0.2
    _CITATION = re.compile(r"\[(\d+)\]")

    def __init__(self) -> None:
        """Initialise the pipeline against the shared vector store."""
        from core.safety import prompt_hash
        from services.semantic_cache import HRSemanticCache

        self._store = vector_store
        self._cache = HRSemanticCache(
            maxsize=settings.policy_cache_size,
            ttl_seconds=settings.semantic_cache_ttl,
        )
        self.prompt_version = prompt_hash(self.SYNTHESIS_PROMPT_TEMPLATE)

    # -- ingestion --------------------------------------------------------
    def ingest_pdf(self, path: str, doc_id: str | None = None) -> int:
        """Ingest a single PDF into the vector store.

        Args:
            path: Path to the PDF file.
            doc_id: Optional document id override.

        Returns:
            Number of chunks written.
        """
        chunks = ingest_pdf(path, doc_id)
        return self._store.upsert_chunks(chunks) if chunks else 0

    def ingest_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Write already-chunked records to the vector store.

        Args:
            chunks: Chunk dicts with ``text``, ``doc_id`` and ``metadata``.

        Returns:
            The number of chunks written.
        """
        return self._store.upsert_chunks(chunks) if chunks else 0

    def ingest_directory(self, directory: str) -> int:
        """Ingest all PDFs in a directory.

        Args:
            directory: Directory of policy PDFs.

        Returns:
            Total number of chunks written.
        """
        chunks = ingest_directory(directory)
        return self._store.upsert_chunks(chunks) if chunks else 0

    # -- retrieval --------------------------------------------------------
    def retrieve(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Retrieve the most relevant chunks for a query.

        Args:
            query: Natural-language question.
            top_k: Optional override of the number of chunks.

        Returns:
            Ranked list of chunk dicts (``text``, ``doc_id``, ``score``).
        """
        return self._store.search(query, top_k=top_k or settings.retrieval_top_k)

    # -- generation -------------------------------------------------------
    def _synthesize_answer(self, query: str, contexts: list[dict[str, Any]]) -> str:
        """Answer string only (back-compat wrapper around :meth:`_synthesize`)."""
        return self._synthesize(query, contexts)[0]

    @classmethod
    def _citations_valid(cls, answer: str, context_count: int) -> bool:
        """Require citations and reject references outside retrieved context."""
        citations = [int(value) for value in cls._CITATION.findall(answer)]
        return bool(citations) and all(1 <= value <= context_count for value in citations)

    def _synthesize(self, query: str, contexts: list[dict[str, Any]]) -> tuple[str, str]:
        """Generate an answer **and the reasoning mode that produced it**.

        The mode is returned so the UI can be honest about *what answered* — a
        premium LLM synthesis vs. a deterministic verbatim excerpt — instead of
        letting a local heuristic masquerade as elite reasoning. One of:

          * ``"llm"`` — synthesised by the configured provider.
          * ``"grounded_excerpt"`` — verbatim top chunk (no live LLM, or the match
            is too weak to ground a synthesis): deterministic, zero spend.
          * ``"no_context"`` — nothing retrieved; refuses rather than fabricating.
          * ``"llm_error"`` — the LLM call failed; degraded to the excerpt.

        Returns:
            ``(answer, mode)``.
        """
        from core.llm_factory import run_text_completion
        from core.runtime_key import llm_active

        # Context-or-null: with no relevant chunk, never let the model invent a
        # policy from training data — say so plainly.
        if not contexts:
            return (
                "The provided policy documents don't cover that. Please check with "
                "HR or ask an admin to upload the relevant policy.",
                "no_context",
            )

        top_score = contexts[0]["score"]
        # Deterministic verbatim excerpt when there's no live LLM, or when the
        # match is too weak to ground a synthesis (avoids fabricated blends).
        if not llm_active() or top_score < self.GROUNDING_FLOOR:
            return (
                f"(Grounded excerpt — strict mode)\n\n{contexts[0]['text']} [1]",
                "grounded_excerpt",
            )

        joined = "\n\n".join(
            f"[{i + 1}] (source: {c['doc_id']})\n{c['text']}" for i, c in enumerate(contexts)
        )
        try:
            prompt = self.SYNTHESIS_PROMPT_TEMPLATE.format(context=joined, query=query)
            answer = run_text_completion(
                prompt,
                role="policy_rag",
                max_tokens=600,
                temperature=0,  # grounded, deterministic — minimise creative drift
            )
            if answer is None:
                return (
                    f"(LLM unavailable) Top excerpt: {contexts[0]['text']} [1]",
                    "llm_error",
                )
            if not self._citations_valid(answer, len(contexts)):
                return (
                    f"(Uncited model output rejected) Top excerpt: {contexts[0]['text']} [1]",
                    "llm_error",
                )
            return answer, "llm"
        except Exception as exc:  # noqa: BLE001 - degrade gracefully to the excerpt
            return f"(LLM error: {exc}) Top excerpt: {contexts[0]['text']} [1]", "llm_error"

    def query(self, query: str, top_k: int | None = None) -> dict[str, Any]:
        """Run the full RAG flow: retrieve then synthesise an answer.

        Args:
            query: Natural-language question.
            top_k: Optional override of retrieved chunk count.

        Returns:
            Dict with ``answer``, ``source_documents`` and ``confidence_score``.
        """
        from core.observability import record_policy_cache
        from core.runtime_settings import runtime_settings
        from services.semantic_cache import context_hash

        cache_enabled = (
            bool(runtime_settings.value("caching_enabled", True))
            if runtime_settings.active
            else True
        )
        policy_context = context_hash(
            "rag",
            self.prompt_version,
            str(top_k or settings.retrieval_top_k),
            settings.qdrant_collection,
        )
        cached = self._cache.get(query, policy_context) if cache_enabled else None
        if cached is not None:
            record_policy_cache("hit")
            return {**cached, "cached": True}
        record_policy_cache("miss")

        contexts = self.retrieve(query, top_k=top_k)
        answer, mode = self._synthesize(query, contexts)
        # Confidence proxy: top retrieval cosine score (already 0..1 for cosine).
        confidence = round(contexts[0]["score"], 4) if contexts else 0.0
        sources = [
            {
                "doc_id": c["doc_id"],
                "score": round(c["score"], 4),
                "metadata": c.get("metadata", {}),
            }
            for c in contexts
        ]
        # Low-confidence answers are flagged so the UI / triage can route to a
        # human. The saved operator control overrides the env default here too,
        # keeping the compatibility wrapper behavior aligned with services.rag.
        from core.runtime_settings import runtime_settings

        review_threshold = settings.confidence_threshold
        if runtime_settings.active and not runtime_settings.value("human_review_required", True):
            review_threshold = 0.0
        needs_review = confidence < review_threshold
        result = {
            "answer": answer,
            "mode": mode,  # what produced the answer: llm vs deterministic excerpt
            "source_documents": sources,
            "confidence_score": confidence,
            "needs_review": needs_review,
            "prompt_version": self.prompt_version,
            "cached": False,
        }
        if cache_enabled:
            self._cache.set(query, policy_context, result)
        return result


# Module-level singleton.
rag_pipeline = RAGPipeline()
