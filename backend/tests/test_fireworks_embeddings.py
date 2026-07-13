"""Fireworks embedding path contract tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_fireworks_embedding_dimension_is_probed_from_response(monkeypatch) -> None:
    from core import embeddings

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"index": 0, "embedding": [3.0, 4.0, 0.0]}]}

    calls: list[dict] = []

    def fake_post(url, *, headers, json, timeout):  # noqa: ANN001
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("EMBEDDING_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fixture-fireworks-key-not-real")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("FIREWORKS_EMBEDDING_MODEL", "provider/embed-model")
    monkeypatch.setattr("httpx.post", fake_post)
    embeddings._fireworks_dimension.cache_clear()

    assert embeddings.Embedder().dimension == 3
    assert calls[0]["url"] == "https://example.invalid/v1/embeddings"
    assert calls[0]["json"]["model"] == "provider/embed-model"


def test_fireworks_embeddings_are_normalized(monkeypatch) -> None:
    from core import embeddings

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"index": 0, "embedding": [3.0, 4.0]}]}

    monkeypatch.setenv("EMBEDDING_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fixture-fireworks-key-not-real")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("FIREWORKS_EMBEDDING_MODEL", "provider/embed-model")
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: FakeResponse())

    assert embeddings.Embedder().embed("hello") == [0.6, 0.8]
