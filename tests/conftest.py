"""Shared test fixtures."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from analytics.db import AnalyticsDB
from analytics.writer import AnalyticsWriter


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer changeme"}


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
