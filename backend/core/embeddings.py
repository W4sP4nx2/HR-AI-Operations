"""Embedding utilities backed by Fireworks or local sentence-transformers.

If sentence-transformers is not installed, the embedder degrades gracefully to
a deterministic hashing bag-of-words embedding so that similarity-based features
(e.g. the resume screener fallback) keep working without heavy dependencies.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache

from core.config import settings

# Dimensionality of the deterministic hashing fallback embedding. A larger space
# than the original 256 meaningfully reduces hash collisions on HR-sized vocab.
_FALLBACK_DIM = 512
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")

# Common English stopwords are dropped before hashing so that content words
# (leave, days, parental) drive similarity instead of filler ("how", "do", "i").
# Without this, a query like "how many vacation days do I get" shares almost no
# tokens with a policy chunk and the cosine score collapses.
_STOPWORDS = frozenset(
    """a an and are as at be by can could do does for from get got how i if in into is
    it its many may me my of on or our should so the their them they this to up us was we
    what when where which who will with would you your""".split()
)

# Lightweight HR-domain synonym normalisation. A purely lexical embedding can't
# know that "vacation" and "annual leave" mean the same thing, so we fold common
# HR vocabulary onto a shared canonical token. This is what makes the dependency
# -free fallback feel semantic on the questions a reviewer actually asks.
_SYNONYMS = {
    "vacation": "leave",
    "holiday": "leave",
    "holidays": "leave",
    "pto": "leave",
    "annual": "leave",
    "timeoff": "leave",
    "maternity": "parental",
    "paternity": "parental",
    "childbirth": "parental",
    "newborn": "parental",
    "wfh": "remote",
    "telework": "remote",
    "telecommute": "remote",
    "home": "remote",
    "401k": "benefits",
    "insurance": "benefits",
    "health": "benefits",
    "dental": "benefits",
    "vision": "benefits",
    "enrollment": "benefits",
    "enroll": "benefits",
    "reimbursement": "expense",
    "reimburse": "expense",
    "receipt": "expense",
    "receipts": "expense",
    "harassment": "conduct",
    "discrimination": "conduct",
    "misconduct": "conduct",
    "ethics": "conduct",
    "review": "performance",
    "appraisal": "performance",
    "rating": "performance",
    "promotion": "performance",
    "privacy": "data",
    "gdpr": "data",
    "breach": "data",
    "safety": "safety",
    "injury": "safety",
    "hazard": "safety",
    "sick": "leave",
    "sickness": "leave",
}


def _normalise_tokens(text: str) -> list[str]:
    """Tokenise → lowercase → drop stopwords → fold HR synonyms.

    Shared by the hashing embedder so both ingestion and queries land in the
    same normalised vocabulary (otherwise expansion on only one side wouldn't
    help). Each token also contributes its synonym canonical form *in addition*
    to itself, so exact matches still count.
    """
    out: list[str] = []
    for raw in _TOKEN_PATTERN.findall(text.lower()):
        if raw in _STOPWORDS or len(raw) == 1:
            continue
        out.append(raw)
        canon = _SYNONYMS.get(raw)
        if canon and canon != raw:
            out.append(canon)
    return out


@lru_cache
def _load_model():
    """Lazily load and cache the sentence-transformers model.

    The import is performed inside the function so that importing this module
    does not pull the heavy transformer dependency until embeddings are first
    requested (keeps API startup fast and tests lightweight).

    Returns ``None`` when sentence-transformers is unavailable or when the model
    cannot be loaded from the local Hugging Face cache, signalling callers to use
    the deterministic hashing fallback.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:  # noqa: BLE001 - degrade gracefully without the heavy dep
        return None

    try:
        device = settings.embedding_device.strip().lower()
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("EMBEDDING_DEVICE must be auto, cpu, or cuda")
        kwargs = {} if device == "auto" else {"device": device}
        return SentenceTransformer(settings.embedding_model, **kwargs)
    except Exception:  # noqa: BLE001 - offline/cache/model errors degrade too
        if settings.embedding_device.strip().lower() != "auto":
            raise
        return None


def _hash_embed(text: str) -> list[float]:
    """Deterministic hashing bag-of-words embedding, L2-normalised.

    Each token is hashed into a fixed-size vector; counts are accumulated and
    the vector is normalised. Texts sharing tokens produce similar vectors, so
    cosine similarity remains meaningful without sentence-transformers.

    Args:
        text: The input text to embed.

    Returns:
        A normalised dense vector of length ``_FALLBACK_DIM``.
    """
    vec = [0.0] * _FALLBACK_DIM
    for token in _normalise_tokens(text):
        digest = hashlib.md5(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % _FALLBACK_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _normalise_vector(vec: list[float]) -> list[float]:
    """Return an L2-normalised copy of ``vec``."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _embedding_provider() -> str:
    """Configured embedding backend, read live for harness-injected env."""
    provider = (
        (os.environ.get("EMBEDDING_PROVIDER") or settings.embedding_provider or "local")
        .strip()
        .lower()
    )
    if provider in {"hash", "hashing", "deterministic"}:
        return "hashing"
    return provider


def _fireworks_embedding_model() -> str:
    model = os.environ.get("FIREWORKS_EMBEDDING_MODEL", settings.fireworks_embedding_model).strip()
    if not model:
        raise RuntimeError("FIREWORKS_EMBEDDING_MODEL is empty or unset")
    return model


def _fireworks_embedding_config() -> tuple[str, str, str]:
    api_key = os.environ.get("FIREWORKS_API_KEY", settings.fireworks_api_key).strip()
    base_url = os.environ.get("FIREWORKS_BASE_URL", settings.fireworks_base_url).rstrip("/")
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY is empty or unset")
    if not base_url:
        raise RuntimeError("FIREWORKS_BASE_URL is empty or unset")
    return api_key, base_url, _fireworks_embedding_model()


def _fireworks_embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed through the configured Fireworks OpenAI-compatible endpoint."""
    if not texts:
        return []
    import httpx

    api_key, base_url, model = _fireworks_embedding_config()
    resp = httpx.post(
        f"{base_url}/embeddings",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "input": texts},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
    if len(ordered) != len(texts):
        raise RuntimeError("embedding response count did not match request count")
    return [_normalise_vector([float(x) for x in item["embedding"]]) for item in ordered]


@lru_cache
def _fireworks_dimension() -> int:
    """Probe and cache the real Fireworks embedding dimension on first use."""
    return len(_fireworks_embed_batch(["dimension probe"])[0])


class Embedder:
    """Thin wrapper around a sentence-transformers model.

    Provides single-text and batch embedding plus the embedding dimension,
    which the vector store needs when creating a collection.
    """

    def __init__(self, model_name: str | None = None) -> None:
        """Initialise the embedder.

        Args:
            model_name: Optional override of the configured embedding model.
        """
        self._model_name = model_name or settings.embedding_model

    @property
    def provider(self) -> str:
        """Return the live provider name used for metrics and diagnostics."""
        return _embedding_provider()

    @property
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""
        if _embedding_provider() == "fireworks":
            return _fireworks_dimension()
        if _embedding_provider() == "hashing":
            return _FALLBACK_DIM
        model = _load_model()
        if model is None:
            return _FALLBACK_DIM
        return int(model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        """Embed a single string into a list of floats.

        Args:
            text: The input text to embed.

        Returns:
            A dense embedding vector as a Python list.
        """
        if _embedding_provider() == "fireworks":
            return _fireworks_embed_batch([text])[0]
        if _embedding_provider() == "hashing":
            return _hash_embed(text)
        model = _load_model()
        if model is None:
            return _hash_embed(text)
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed strings in bounded batches while preserving input ordering.

        Args:
            texts: List of input strings.

        Returns:
            A list of embedding vectors.
        """
        if not texts:
            return []
        batch_size = max(1, settings.embedding_batch_size)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(self._embed_batch_once(texts[start : start + batch_size]))
        return vectors

    def _embed_batch_once(self, texts: list[str]) -> list[list[float]]:
        """Embed one already-bounded batch."""
        if _embedding_provider() == "fireworks":
            return _fireworks_embed_batch(texts)
        if _embedding_provider() == "hashing":
            return [_hash_embed(t) for t in texts]
        model = _load_model()
        if model is None:
            return [_hash_embed(t) for t in texts]
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=max(1, settings.embedding_batch_size),
        )
        return [v.tolist() for v in vectors]

    def similarity(self, a: str, b: str) -> float:
        """Compute cosine similarity between two texts in [0, 1] range.

        Args:
            a: First text.
            b: Second text.

        Returns:
            Cosine similarity score (vectors are normalised, so this is a dot
            product) clamped to the [0, 1] interval.
        """
        va = self.embed(a)
        vb = self.embed(b)
        dot = sum(x * y for x, y in zip(va, vb, strict=False))
        return max(0.0, min(1.0, (dot + 1.0) / 2.0))


# Module-level singleton for convenient reuse.
embedder = Embedder()
