"""Prometheus instrumentation remains content-free and route-bounded."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_prometheus_endpoint_exposes_route_template_metrics():
    import httpx

    from api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health")
        response = await client.get("/internal/metrics")

    assert response.status_code == 200
    assert "hrcc_http_requests_total" in response.text
    assert 'route="/health"' in response.text
    assert "anonymous@local" not in response.text
