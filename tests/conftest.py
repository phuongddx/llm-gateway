"""Shared test fixtures."""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from analytics.db import AnalyticsDB
from analytics.writer import AnalyticsWriter
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
async def analytics_writer(analytics_db):
    """AnalyticsWriter over the test DB (lifespan never runs under ASGITransport)."""
    from main import app

    writer = AnalyticsWriter(analytics_db, queue_size=1000)
    writer.start()
    app.state.analytics_writer = writer
    yield writer
    await writer.stop()


@pytest_asyncio.fixture
async def client(analytics_db, analytics_writer):
    """Async test client with analytics DB + writer injected."""
    from main import app

    # Override app.state handles with test instances (ASGITransport never runs the lifespan)
    app.state.analytics_db = analytics_db
    app.state.analytics_writer = analytics_writer

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
