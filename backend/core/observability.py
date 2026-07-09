"""Low-cardinality Prometheus metrics for HTTP and controlled inference."""

from __future__ import annotations

from collections import Counter as CollectionCounter
from threading import Lock

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )
except ImportError:  # Lean custom builds may omit metrics without breaking the API.
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    Counter = None
    Histogram = None
    generate_latest = None

_LOCK = Lock()
_FALLBACK_REQUESTS: CollectionCounter[tuple[str, str, str]] = CollectionCounter()
_FALLBACK_LATENCY: dict[tuple[str, str], tuple[int, float]] = {}
_POLICY_CACHE: CollectionCounter[str] = CollectionCounter()


HTTP_REQUESTS = (
    Counter(
        "hrcc_http_requests_total",
        "HTTP requests by method, route template, and status.",
        ("method", "route", "status"),
    )
    if Counter
    else None
)
HTTP_LATENCY = (
    Histogram(
        "hrcc_http_request_duration_seconds",
        "HTTP request duration by method and route template.",
        ("method", "route"),
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    )
    if Histogram
    else None
)
INFERENCE_INPUTS = (
    Counter(
        "hrcc_inference_inputs_total",
        "Controlled inference inputs by role and transformation flags.",
        ("role", "truncated", "injection_signal"),
    )
    if Counter
    else None
)
EMBEDDING_CHUNKS = (
    Counter(
        "hrcc_embedding_chunks_total",
        "Embedded chunks by provider.",
        ("provider",),
    )
    if Counter
    else None
)
EMBEDDING_DURATION = (
    Histogram(
        "hrcc_embedding_batch_duration_seconds",
        "Embedding duration by provider.",
        ("provider",),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 15, 30),
    )
    if Histogram
    else None
)
VECTOR_WRITE_DURATION = (
    Histogram(
        "hrcc_vector_write_duration_seconds",
        "Vector write duration by backend.",
        ("backend",),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    )
    if Histogram
    else None
)
VECTOR_ROWS = (
    Counter(
        "hrcc_vector_rows_written_total",
        "Vector rows written by backend.",
        ("backend",),
    )
    if Counter
    else None
)
RETRIEVAL_DURATION = (
    Histogram(
        "hrcc_retrieval_duration_seconds",
        "Retrieval duration by backend.",
        ("backend",),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
    )
    if Histogram
    else None
)
CACHE_EVENTS = (
    Counter(
        "hrcc_policy_cache_events_total",
        "Policy answer cache events.",
        ("result",),
    )
    if Counter
    else None
)


def record_http(method: str, route: str, status: int, duration_seconds: float) -> None:
    """Record one request without user ids, raw paths, or tenant labels."""
    with _LOCK:
        _FALLBACK_REQUESTS[(method, route, str(status))] += 1
        count, total = _FALLBACK_LATENCY.get((method, route), (0, 0.0))
        _FALLBACK_LATENCY[(method, route)] = (count + 1, total + duration_seconds)
    if HTTP_REQUESTS is None or HTTP_LATENCY is None:
        return
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_LATENCY.labels(method=method, route=route).observe(duration_seconds)


def record_inference_input(role: str, *, truncated: bool, injection_signal: bool) -> None:
    """Record transformation outcomes without retaining prompt content."""
    if INFERENCE_INPUTS is None:
        return
    INFERENCE_INPUTS.labels(
        role=role,
        truncated=str(truncated).lower(),
        injection_signal=str(injection_signal).lower(),
    ).inc()


def record_embedding(provider: str, chunks: int, duration_seconds: float) -> None:
    """Record batch throughput inputs without document or tenant cardinality."""
    if EMBEDDING_CHUNKS is None or EMBEDDING_DURATION is None:
        return
    EMBEDDING_CHUNKS.labels(provider=provider).inc(chunks)
    EMBEDDING_DURATION.labels(provider=provider).observe(duration_seconds)


def record_vector_write(backend: str, rows: int, duration_seconds: float) -> None:
    """Record vector persistence count and duration."""
    if VECTOR_ROWS is None or VECTOR_WRITE_DURATION is None:
        return
    VECTOR_ROWS.labels(backend=backend).inc(rows)
    VECTOR_WRITE_DURATION.labels(backend=backend).observe(duration_seconds)


def record_retrieval(backend: str, duration_seconds: float) -> None:
    """Record retrieval latency for p50/p95 aggregation."""
    if RETRIEVAL_DURATION is not None:
        RETRIEVAL_DURATION.labels(backend=backend).observe(duration_seconds)


def record_policy_cache(result: str) -> None:
    """Record a policy-cache hit/miss without retaining the query."""
    label = "hit" if result == "hit" else "miss"
    with _LOCK:
        _POLICY_CACHE[label] += 1
    if CACHE_EVENTS is not None:
        CACHE_EVENTS.labels(result=label).inc()


def policy_cache_snapshot() -> dict[str, float | int | None]:
    """Return cache hit-rate telemetry for lifecycle/status endpoints."""
    with _LOCK:
        hits = int(_POLICY_CACHE["hit"])
        misses = int(_POLICY_CACHE["miss"])
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "total": total,
        "hit_rate": (hits / total) if total else None,
    }


def render_metrics() -> tuple[bytes, str]:
    """Render full client metrics or a minimal dependency-free fallback."""
    if generate_latest is not None:
        return generate_latest(), CONTENT_TYPE_LATEST

    lines = [
        "# HELP hrcc_http_requests_total HTTP requests by method, route template, and status.",
        "# TYPE hrcc_http_requests_total counter",
    ]
    with _LOCK:
        for (method, route, status), count in sorted(_FALLBACK_REQUESTS.items()):
            lines.append(
                f'hrcc_http_requests_total{{method="{method}",route="{route}",'
                f'status="{status}"}} {count}'
            )
        lines.extend(
            [
                "# HELP hrcc_http_request_duration_seconds Request duration summary.",
                "# TYPE hrcc_http_request_duration_seconds summary",
            ]
        )
        for (method, route), (count, total) in sorted(_FALLBACK_LATENCY.items()):
            labels = f'method="{method}",route="{route}"'
            lines.append(f"hrcc_http_request_duration_seconds_count{{{labels}}} {count}")
            lines.append(f"hrcc_http_request_duration_seconds_sum{{{labels}}} {total:.9f}")
    return ("\n".join(lines) + "\n").encode(), CONTENT_TYPE_LATEST
