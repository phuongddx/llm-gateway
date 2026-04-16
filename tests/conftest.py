"""Shared test fixtures."""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from analytics.db import AnalyticsDB
from providers.base import LLMProvider, StreamChunk, UsageData


class MockProvider(LLMProvider):
    """Mock provider that yields predetermined tokens + usage."""

    def __init__(self, tokens: list[str] | None = None, usage: UsageData | None = None):
        self.tokens = tokens or ["Hello", " world", "!"]
        self.usage = usage or UsageData(prompt_tokens=10, completion_tokens=3, total_tokens=13)

    async def chat_stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncGenerator[StreamChunk, None]:
        for token in self.tokens:
            yield (token, None)
        yield ("", self.usage)


class FailingProvider(LLMProvider):
    """Provider that raises an error during streaming."""

    async def chat_stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncGenerator[StreamChunk, None]:
        yield ("start", None)
        raise RuntimeError("Provider failed")


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer changeme"}


@pytest.fixture
def mock_provider():
    return MockProvider()


@pytest_asyncio.fixture
async def analytics_db(tmp_path):
    """In-memory AnalyticsDB for testing."""
    db = AnalyticsDB(":memory:")
    await db.initialize()
    yield db
    await db.close()


@pytest_asyncio.fixture
async def client(analytics_db):
    """Async test client with analytics DB injected."""
    from main import app

    # Override app.state.analytics_db with test DB
    app.state.analytics_db = analytics_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
