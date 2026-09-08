"""Tests for per-key rate limiting (OBSV-02).

extract_bearer_key keys the per-key limit on the Bearer token, falling back
to remote IP when missing/malformed; RATE_LIMIT_PER_KEY stacks alongside the
existing per-IP RATE_LIMIT (both apply, per 04-CONTEXT.md).
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from config import Settings, settings
from rate_limiter import limiter


@pytest.fixture(autouse=True)
def _reset_rate_limiter_storage():
    """slowapi's in-memory storage is a module-level singleton shared across
    the whole test session -- reset before and after every test in this file
    so an earlier test's hits against the same Bearer token (auth_headers is
    a fixed "changeme" token reused suite-wide) never leak into this file's
    low, monkeypatched-limit boundary assertions."""
    limiter.reset()
    yield
    limiter.reset()


async def _mock_stream(*args, **kwargs):
    yield ("ok", None)


def _mock_provider():
    provider = AsyncMock()
    provider.chat_stream = _mock_stream
    return provider


async def _post_chat(client, auth_headers, headers=None):
    return await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=headers if headers is not None else auth_headers,
    )


@pytest.mark.asyncio
async def test_per_key_limit_429s_on_third_request_same_token(client, auth_headers, monkeypatch):
    """Two requests carrying the same Bearer token succeed under a
    monkeypatched 2/minute per-key limit; a third within the window 429s --
    and create_provider is never called on the 429 path (429 fires before
    any provider is constructed or called)."""
    monkeypatch.setattr(settings, "rate_limit_per_key", "2/minute")

    with patch("routes.chat.create_provider", return_value=_mock_provider()) as mock_create:
        r1 = await _post_chat(client, auth_headers)
        r2 = await _post_chat(client, auth_headers)
        r3 = await _post_chat(client, auth_headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert mock_create.call_count == 2


def test_settings_rejects_malformed_rate_limit_per_key():
    with pytest.raises(ValidationError, match="RATE_LIMIT_PER_KEY"):
        Settings(_env_file=None, rate_limit_per_key="bogus/zzz")
