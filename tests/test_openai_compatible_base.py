"""Unit tests for OpenAICompatibleProvider usage extraction (cached tokens) and
tenacity-driven same-provider retry behavior (OBSV-03)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import tenacity
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)

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
    with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
        collected = [c async for c in provider.chat_stream([{"role": "user", "content": "x"}], "")]
    assert collected == [("ok", None)]
    assert create_mock.await_count == 3


def test_client_constructed_with_max_retries_zero():
    """AsyncOpenAI must be constructed with max_retries=0 so the SDK's own
    internal retry (default 2) cannot silently retry a z.ai quota/auth error
    before tenacity's allow-list predicate ever sees it (ZAI-3)."""
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    assert provider.client.max_retries == 0


def _balance_exhausted_error():
    """Real z.ai '1113' balance-exhaustion shape: HTTP 402, which the openai
    SDK's status->exception mapping does not special-case, so it surfaces as
    the generic `APIStatusError` (not a bespoke stand-in) -- still correctly
    excluded from the retry allow-list by omission (ZAI-3)."""
    req = httpx.Request("POST", "https://api.z.ai/v4/chat/completions")
    resp = httpx.Response(402, request=req)
    return APIStatusError("1113 Insufficient Balance", response=resp, body=None)


def _rate_limit_error():
    req = httpx.Request("POST", "https://api.z.ai/v4/chat/completions")
    resp = httpx.Response(429, request=req)
    return RateLimitError("quota exceeded", response=resp, body=None)


def _authentication_error():
    req = httpx.Request("POST", "https://api.z.ai/v4/chat/completions")
    resp = httpx.Response(401, request=req)
    return AuthenticationError("invalid api key", response=resp, body=None)


def _permission_denied_error():
    req = httpx.Request("POST", "https://api.z.ai/v4/chat/completions")
    resp = httpx.Response(403, request=req)
    return PermissionDeniedError("forbidden", response=resp, body=None)


@pytest.mark.asyncio
async def test_quota_1113_shaped_exception_is_never_retried():
    """The real z.ai '1113' balance-exhausted exception (HTTP 402, mapped by
    the openai SDK to the generic `APIStatusError`) must not be retried at
    all -- the allow-list excludes it by omission (it is not one of the
    three allow-listed types), not by matching its class name or status
    code (WR-01: real SDK type, not a bespoke stand-in)."""
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    create_mock = AsyncMock(side_effect=_balance_exhausted_error())
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    with pytest.raises(APIStatusError):
        async for _ in provider.chat_stream([{"role": "user", "content": "x"}], ""):
            pass
    assert create_mock.await_count == 1


@pytest.mark.asyncio
async def test_auth_failure_shaped_exception_is_never_retried():
    """A real `openai.AuthenticationError` (401) must not be retried -- same
    omission reasoning as the quota case, but against the actual SDK type
    rather than a fake stand-in (WR-01)."""
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    create_mock = AsyncMock(side_effect=_authentication_error())
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    with pytest.raises(AuthenticationError):
        async for _ in provider.chat_stream([{"role": "user", "content": "x"}], ""):
            pass
    assert create_mock.await_count == 1


@pytest.mark.asyncio
async def test_real_ratelimiterror_is_never_retried():
    """A real `openai.RateLimitError` (429, z.ai quota exhaustion) must not
    be retried -- verifies ZAI-3 against the actual SDK exception hierarchy,
    not a shape-alike fake (WR-01)."""
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    create_mock = AsyncMock(side_effect=_rate_limit_error())
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    with pytest.raises(RateLimitError):
        async for _ in provider.chat_stream([{"role": "user", "content": "x"}], ""):
            pass
    assert create_mock.await_count == 1


@pytest.mark.asyncio
async def test_real_permissiondeniederror_is_never_retried():
    """A real `openai.PermissionDeniedError` (403) must not be retried --
    the third ZAI-3-excluded sibling of `APIStatusError` (WR-01)."""
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    create_mock = AsyncMock(side_effect=_permission_denied_error())
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    with pytest.raises(PermissionDeniedError):
        async for _ in provider.chat_stream([{"role": "user", "content": "x"}], ""):
            pass
    assert create_mock.await_count == 1

@pytest.mark.asyncio
async def test_exhausted_transient_failure_reraises_original_exception():
    """When all 3 attempts raise APIConnectionError, the exception from the
    final attempt is re-raised as-is — a real APIConnectionError instance
    (not a tenacity RetryError wrapper) — preserving attribute access (e.g.
    .request) for routes/chat.py's unchanged error mapping. asyncio.sleep is
    patched so the 2 backoff waits don't slow the suite down."""

    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    final_exception = _api_connection_error()
    create_mock = AsyncMock(
        side_effect=[_api_connection_error(), _api_connection_error(), final_exception]
    )
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
        with pytest.raises(APIConnectionError) as exc_info:
            async for _ in provider.chat_stream([{"role": "user", "content": "x"}], ""):
                pass
    assert exc_info.value is final_exception
    assert not isinstance(exc_info.value, tenacity.RetryError)
    assert exc_info.value.request is final_exception.request
    assert create_mock.await_count == 3


@pytest.mark.asyncio
async def test_before_sleep_logging_never_includes_message_content():
    """The before_sleep retry-logging hook must only log base_url, attempt
    number, and exception class name — never the messages list or any of
    its string content (OBSV-03 retry-logging prohibition)."""
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    provider.base_url = "https://example.com/v1"
    create_mock = AsyncMock(
        side_effect=[_api_connection_error(), _aiter([_chunk(content="ok")])]
    )
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )
    secret_content = "super-secret-prompt-xyz"
    with patch("asyncio.sleep", new=AsyncMock(return_value=None)), \
         patch("providers.openai_compatible_base.logger") as mock_logger:
        collected = [
            c
            async for c in provider.chat_stream(
                [{"role": "user", "content": secret_content}], ""
            )
        ]
    assert collected == [("ok", None)]
    assert mock_logger.warning.call_count == 1
    logged_args = mock_logger.warning.call_args.args
    logged_str = " ".join(str(a) for a in logged_args)
    assert secret_content not in logged_str
    assert "messages" not in logged_str.lower()
    assert "https://example.com/v1" in logged_str
    assert "APIConnectionError" in logged_str
