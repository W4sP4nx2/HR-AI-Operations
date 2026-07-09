"""Deterministic HR cache with policy-version-aware keys."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from core.safety import LRUCache


class HRSemanticCache:
    """Cache governed HR answers by normalized query and context hash.

    The class intentionally works without Redis or embedding downloads. When a
    Redis-compatible client is supplied it can use that backend; otherwise it
    falls back to the same in-process LRU cache used by local/no-key demos.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        *,
        maxsize: int = 128,
        ttl_seconds: int = 0,
    ) -> None:
        self.redis = redis_client
        self._local = LRUCache(maxsize=maxsize, ttl_seconds=ttl_seconds)
        self.ttl_seconds = max(0, ttl_seconds)

    def key_for(self, query: str, context_hash: str) -> str:
        normalized = normalize_query(query)
        query_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
        return f"hr_cache:{context_hash}:{query_hash}"

    def get(self, query: str, context_hash: str) -> dict[str, Any] | None:
        cached = self._local.get(self.key_for(query, context_hash))
        return dict(cached) if isinstance(cached, dict) else None

    def set(self, query: str, context_hash: str, response: dict[str, Any]) -> None:
        self._local.set(self.key_for(query, context_hash), dict(response))

    async def get_cached(self, query: str, context_hash: str) -> dict[str, Any] | None:
        key = self.key_for(query, context_hash)
        if self.redis is None:
            return self.get(query, context_hash)
        cached = await self.redis.get(key)
        if not cached:
            return None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")
        parsed = json.loads(cached)
        return parsed if isinstance(parsed, dict) else None

    async def set_cached(
        self,
        query: str,
        context_hash: str,
        response: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        key = self.key_for(query, context_hash)
        ttl_seconds = self.ttl_seconds if ttl is None else max(0, ttl)
        if self.redis is None:
            self.set(query, context_hash, response)
            return
        payload = json.dumps(response, sort_keys=True)
        if ttl_seconds:
            await self.redis.setex(key, ttl_seconds, payload)
        else:
            await self.redis.set(key, payload)


def normalize_query(query: str) -> str:
    """Normalize repetitive HR questions without retaining raw PII."""
    lowered = query.strip().lower()
    collapsed = re.sub(r"\s+", " ", lowered)
    return re.sub(r"[^\w\s-]", "", collapsed).strip()


def context_hash(*parts: str) -> str:
    """Create a compact version key for policy/cache context."""
    normalized = "|".join(part.strip().lower() for part in parts if part.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
