"""Tests for dashboard route and static file serving."""

import pytest


@pytest.mark.asyncio
async def test_dashboard_route_returns_html(client):
    """GET /dashboard returns 200 with HTML content type."""
    res = await client.get("/dashboard")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "dashboard" in res.text.lower()


@pytest.mark.asyncio
async def test_dashboard_no_auth_required(client):
    """Dashboard route does NOT require Bearer auth (assets do; data endpoints do)."""
    res = await client.get("/dashboard")
    assert res.status_code == 200
