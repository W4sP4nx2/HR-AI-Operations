"""Batch embedding and bounded vector-write contracts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock


def test_embed_batch_is_bounded_and_preserves_order(monkeypatch):
    from core import embeddings
    from core.config import settings

    calls: list[list[str]] = []

    def fake_batch(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[float(int(text.removeprefix("item-")))] for text in texts]

    monkeypatch.setattr(settings, "embedding_batch_size", 2)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fireworks")
    monkeypatch.setattr(embeddings, "_fireworks_embed_batch", fake_batch)
    texts = [f"item-{index}" for index in range(5)]
    vectors = embeddings.Embedder().embed_batch(texts)
    assert calls == [texts[:2], texts[2:4], texts[4:]]
    assert vectors == [[0.0], [1.0], [2.0], [3.0], [4.0]]


def test_local_ingestion_calls_batch_embed_once_and_preserves_rows(tmp_path, monkeypatch):
    import core.memory as memory_module
    import services.local_vector_store as local_module
    from core.config import settings

    fresh = memory_module.Memory(str(tmp_path / "batching.db"))
    saved = memory_module.memory
    memory_module.memory = fresh
    store = local_module.LocalVectorStore()
    calls: list[list[str]] = []

    def fake_embed_batch(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[float(index), 1.0] for index, _ in enumerate(texts)]

    monkeypatch.setattr(local_module.embedder, "embed_batch", fake_embed_batch)
    monkeypatch.setattr(settings, "vector_write_batch_size", 2)
    chunks = [
        {
            "text": f"chunk-{index}",
            "doc_id": "policy",
            "metadata": {"chunk_index": index},
        }
        for index in range(5)
    ]
    try:
        assert asyncio.run(store.upsert_chunks(chunks)) == 5
        assert calls == [[f"chunk-{index}" for index in range(5)]]
    finally:
        memory_module.memory = saved


def test_pgvector_ingestion_executes_bounded_write_batches(monkeypatch):
    import services.pgvector_store as pg_module
    from core.config import settings

    executed: list[list[dict]] = []

    class Connection:
        async def execute(self, statement, rows):  # noqa: ANN001
            executed.append(rows)

    class Context:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Engine:
        def begin(self):
            return Context()

    class Memory:
        engine = Engine()

    store = pg_module.PgVectorStore()
    monkeypatch.setattr(store, "ensure_schema", AsyncMock(return_value=True))
    monkeypatch.setattr(pg_module, "_mem", lambda: Memory())
    monkeypatch.setattr(
        pg_module.embedder,
        "embed_batch",
        lambda texts: [[float(index), 1.0] for index, _ in enumerate(texts)],
    )
    monkeypatch.setattr(settings, "vector_write_batch_size", 2)
    chunks = [
        {
            "text": f"chunk-{index}",
            "doc_id": "policy",
            "metadata": {"chunk_index": index},
        }
        for index in range(5)
    ]
    assert asyncio.run(store.upsert_chunks(chunks)) == 5
    assert [len(batch) for batch in executed] == [2, 2, 1]
    assert [row["idx"] for batch in executed for row in batch] == list(range(5))


def test_gpu_scoring_launch_failure_is_visible_in_local_search(tmp_path, monkeypatch):
    import core.memory as memory_module
    import services.gpu_vector_scoring as gpu_module
    import services.local_vector_store as local_module
    from services.gpu_vector_scoring import GPUKernelEligibility

    fresh = memory_module.Memory(str(tmp_path / "gpu-failure.db"))
    saved = memory_module.memory
    memory_module.memory = fresh
    store = local_module.LocalVectorStore()
    try:
        asyncio.run(
            store.upsert_chunks(
                [{"text": "policy text", "doc_id": "p", "metadata": {"chunk_index": 0}}]
            )
        )
        monkeypatch.setattr(
            gpu_module,
            "eligibility",
            lambda corpus_size: GPUKernelEligibility(True, "test"),
        )
        monkeypatch.setattr(
            gpu_module,
            "score_candidates",
            lambda query, candidates: (_ for _ in ()).throw(RuntimeError("launch failed")),
        )
        monkeypatch.setattr(local_module, "eligibility", gpu_module.eligibility, raising=False)
        monkeypatch.setattr(
            local_module, "score_candidates", gpu_module.score_candidates, raising=False
        )
        try:
            asyncio.run(store.search("policy", top_k=1))
        except RuntimeError as exc:
            assert "launch failed" in str(exc)
        else:
            raise AssertionError("GPU launch failure was silently swallowed")
    finally:
        memory_module.memory = saved
