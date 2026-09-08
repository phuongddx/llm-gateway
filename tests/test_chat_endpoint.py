"""Integration tests for POST /v1/chat/completions endpoint."""

import asyncio
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


# --- zai-coding credit logging + error mapping ---


class ZaiQuotaError(Exception):
    status_code = 429


class ZaiAuthError(Exception):
    status_code = 401


def _zai_stream_request():
    return {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "hi"}],
    }


@pytest.mark.asyncio
async def test_zai_coding_quota_error_frame(client, auth_headers):
    class QuotaProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            yield ("tok", None)
            raise ZaiQuotaError("429 too many requests")

    with patch("routes.chat.create_provider", return_value=QuotaProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        response = await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )
    assert "zai-coding quota exhausted" in response.text
    assert "Internal error" not in response.text


@pytest.mark.asyncio
async def test_zai_coding_auth_error_frame(client, auth_headers):
    class AuthFailProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            raise ZaiAuthError("401 unauthorized")
            yield ("", None)  # unreachable: makes this an async generator so the raise fires inside the stream

    with patch("routes.chat.create_provider", return_value=AuthFailProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        response = await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )
    assert "zai-coding authentication failed" in response.text


@pytest.mark.asyncio
async def test_zai_coding_1113_code_maps_to_quota(client, auth_headers):
    class BalanceError(Exception):
        status_code = 402

    class BalanceProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            raise BalanceError("1113 Insufficient Balance")
            yield ("", None)  # unreachable: makes this an async generator so the raise fires inside the stream

    with patch("routes.chat.create_provider", return_value=BalanceProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        response = await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )
    assert "zai-coding quota exhausted" in response.text


@pytest.mark.asyncio
async def test_generic_provider_error_unaffected(client, auth_headers):
    class GenericFailProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            yield ("start", None)
            raise RuntimeError("Provider failed")

    with patch("routes.chat.create_provider", return_value=GenericFailProvider()), \
         patch("routes.chat.resolve_provider", return_value=("manifest", "gpt-4o")):
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_headers,
        )
    assert "Internal error processing request" in response.text


@pytest.mark.asyncio
async def test_zai_coding_request_logs_credits(client, auth_headers, analytics_db):
    # 3-arg-tolerant signature: the route calls chat_stream(messages, system_prompt, gen_params)
    class CreditUsageProvider:
        async def chat_stream(self, *args, **kwargs):
            yield ("tok", None)
            yield ("", {
                "prompt_tokens": 150000,
                "completion_tokens": 3000,
                "total_tokens": 153000,
                "cached_tokens": 142500,
            })

    with patch("routes.chat.create_provider", return_value=CreditUsageProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )

    await asyncio.sleep(0.1)  # fire-and-forget log task
    summary = await analytics_db.get_credits_summary()
    # 36.6 peak / 18.3 off-peak depending on wall clock — accept either
    assert summary["credits_7d"] in (pytest.approx(36.6), pytest.approx(18.3))
