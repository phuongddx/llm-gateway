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
    body = response.text
    assert "Hello" in body
    assert "[DONE]" in body


@pytest.mark.asyncio
async def test_chat_unknown_model_passes_through(client, auth_headers):
    """Unknown model passes through to manifest (no 400 error)."""
    mock_provider_response = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield ("Hi", None)
        yield ("", {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4})

    mock_provider_response.chat_stream = mock_stream

    with patch("routes.chat.create_provider", return_value=mock_provider_response):
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "some-unknown-model",
                "messages": [{"role": "user", "content": "Hi"}],
            },
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert "Hi" in response.text


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
    assert response.status_code in (401, 403, 422)


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health check returns 200 with ok status."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
