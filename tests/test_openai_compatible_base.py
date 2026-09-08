"""Unit tests for OpenAICompatibleProvider usage extraction (cached tokens) and
tenacity-driven same-provider retry behavior (OBSV-03)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, InternalServerError

from providers.openai_compatible_base import OpenAICompatibleProvider


def _chunk(content: str | None = None, usage=None):
    delta = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def _usage(prompt=10, completion=3, total=13, cached=None):
    details = SimpleNamespace(cached_tokens=cached) if cached is not None else None
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                           total_tokens=total, prompt_tokens_details=details)


def _provider_with_chunks(chunks):
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=_aiter(chunks))))
    )
    return provider


def _aiter(chunks):
    async def gen():
        for c in chunks:
            yield c
    return gen()


@pytest.mark.asyncio
async def test_usage_chunk_includes_cached_tokens():
    provider = _provider_with_chunks([
        _chunk(content="Hi"),
        _chunk(usage=_usage(prompt=100, completion=5, total=105, cached=95)),
    ])
    collected = [c async for c in provider.chat_stream([{"role": "user", "content": "x"}], "")]
    assert collected[0] == ("Hi", None)
    token, usage = collected[1]
    assert token == ""
    assert usage["prompt_tokens"] == 100
    assert usage["cached_tokens"] == 95


@pytest.mark.asyncio
async def test_usage_without_cache_details_omits_key():
    provider = _provider_with_chunks([
        _chunk(usage=_usage(prompt=10, completion=3, total=13, cached=None)),
    ])
    _, usage = [c async for c in provider.chat_stream([{"role": "user", "content": "x"}], "")][0]  # noqa: RUF015 -- readability preference; list already fully materialized above
    assert "cached_tokens" not in usage


@pytest.mark.asyncio
async def test_zero_cached_tokens_omitted():
    provider = _provider_with_chunks([
        _chunk(usage=_usage(cached=0)),
    ])
    _, usage = [c async for c in provider.chat_stream([{"role": "user", "content": "x"}], "")][0]  # noqa: RUF015 -- readability preference; list already fully materialized above
    assert "cached_tokens" not in usage


def _api_connection_error():
    req = httpx.Request("POST", "https://example.com/v1/chat/completions")
    return APIConnectionError(request=req)


def _internal_server_error():
    req = httpx.Request("POST", "https://example.com/v1/chat/completions")
    resp = httpx.Response(500, request=req)
    return InternalServerError("upstream error", response=resp, body=None)


@pytest.mark.asyncio
async def test_retry_succeeds_on_third_attempt_after_transient_errors():
    """A create() that fails twice with APIConnectionError then succeeds on the
    third attempt still yields the real stream's tokens — proving the retry
    wrapper actually retries the pre-stream call, not merely constructs a
    generator that skips retrying (Pitfall 1)."""
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    create_mock = AsyncMock(
        side_effect=[
            _api_connection_error(),
            _internal_server_error(),
            _aiter([_chunk(content="ok")]),
        ]
    )
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    collected = [c async for c in provider.chat_stream([{"role": "user", "content": "x"}], "")]
    assert collected == [("ok", None)]
    assert create_mock.await_count == 3


def test_client_constructed_with_max_retries_zero():
    """AsyncOpenAI must be constructed with max_retries=0 so the SDK's own
    internal retry (default 2) cannot silently retry a z.ai quota/auth error
    before tenacity's allow-list predicate ever sees it (ZAI-3)."""
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    assert provider.client.max_retries == 0
