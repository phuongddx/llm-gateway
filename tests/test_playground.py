"""Tests for playground route and static file serving."""

import pytest


@pytest.mark.asyncio
async def test_playground_route_returns_html(client):
    """GET /playground returns 200 with HTML content type."""
    res = await client.get("/playground")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "playground" in res.text.lower()


@pytest.mark.asyncio
async def test_playground_no_auth_required(client):
    """Playground route does NOT require Bearer auth."""
    res = await client.get("/playground")
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_static_files_mounted(client):
    """Static files route exists — non-existent file returns 404, not 500."""
    res = await client.get("/static/nonexistent.css")
    assert res.status_code == 404
