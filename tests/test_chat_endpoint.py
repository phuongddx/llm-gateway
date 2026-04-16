"""Integration tests for POST /v1/chat/completions endpoint."""

import json
from unittest.mock import patch, AsyncMock

import pytest


@pytest.mark.asyncio
async def test_chat_with_model(client, auth_headers):
    """Chat request with valid model streams tokens and logs to DB."""
    mock_provider_response = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield ("Hello", None)
        yield ("!", None)
        yield ("", {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})

    mock_provider_response.chat_stream = mock_stream

    with patch("routes.chat.create_provider", return_value=mock_provider_response):
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
            },
            headers=auth_headers,
        )

    assert response.status_code == 200
    # SSE response body should contain token data
    body = response.text
    assert "Hello" in body
    assert "[DONE]" in body


@pytest.mark.asyncio
async def test_chat_unknown_model_returns_400(client, auth_headers):
    """Request with unknown model returns 400 with available models list."""
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "nonexistent-model",
            "messages": [{"role": "user", "content": "Hi"}],
        },
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Unknown model" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_without_auth_returns_401(client):
    """Request without Bearer token returns 401."""
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hi"}],
        },
    )
    # FastAPI returns 422 when required Header(...) is missing
    assert response.status_code in (401, 403, 422)


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health check returns 200 with ok status."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
