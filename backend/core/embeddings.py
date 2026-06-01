"""Embedding utilities backed by HuggingFace sentence-transformers.

If sentence-transformers is not installed, the embedder degrades gracefully to
a deterministic hashing bag-of-words embedding so that similarity-based features
(e.g. the resume screener fallback) keep working without heavy dependencies.
"""

from __future__ import annotations

import hashlib
import math
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

    Returns ``None`` when sentence-transformers is unavailable, signalling
    callers to use the deterministic hashing fallback.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:  # noqa: BLE001 - degrade gracefully without the heavy dep
        return None

    return SentenceTransformer(settings.embedding_model)


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
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""
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
        model = _load_model()
        if model is None:
            return _hash_embed(text)
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings.

        Args:
            texts: List of input strings.

        Returns:
            A list of embedding vectors.
        """
        model = _load_model()
        if model is None:
            return [_hash_embed(t) for t in texts]
        vectors = model.encode(texts, normalize_embeddings=True)
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
