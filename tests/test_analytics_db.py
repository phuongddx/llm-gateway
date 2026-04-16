"""Unit tests for analytics.db — AnalyticsDB CRUD operations."""

import pytest
import pytest_asyncio
from analytics.db import AnalyticsDB


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh AnalyticsDB for each test."""
    database = AnalyticsDB(":memory:")
    await database.initialize()
    yield database
    await database.close()


async def _insert_sample(db: AnalyticsDB, count: int = 5):
    """Insert sample records for aggregation tests."""
    from datetime import datetime, timezone

    models = ["gpt-4o", "deepseek-chat", "gemini-2.5-flash"]
    for i in range(count):
        await db.log_request({
            "id": f"test-{i:04d}",
            "provider": "openai" if i % 2 == 0 else "deepseek",
            "model": models[i % len(models)],
            "prompt_tokens": 100 + i * 10,
            "completion_tokens": 50 + i * 5,
            "total_tokens": 150 + i * 15,
            "latency_ms": 200 + i * 100,
            "ttft_ms": 50 + i * 10,
            "cost_usd": 0.001 * (i + 1),
            "status": "success" if i < count - 1 else "error",
            "error_message": "test error" if i == count - 1 else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })


@pytest.mark.asyncio
async def test_log_and_read_single(db):
    """Insert one record and verify all fields readable."""
    await db.log_request({
        "id": "test-001",
        "provider": "openai",
        "model": "gpt-4o",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 300,
        "ttft_ms": 80,
        "cost_usd": 0.0075,
        "status": "success",
    })
    summary = await db.get_summary()
    assert summary["total_requests"] == 1
    assert summary["total_prompt_tokens"] == 100
    assert summary["total_completion_tokens"] == 50


@pytest.mark.asyncio
async def test_summary_aggregates(db):
    """Summary aggregates across multiple records."""
    await _insert_sample(db, 5)
    summary = await db.get_summary()
    assert summary["total_requests"] == 5
    assert summary["total_prompt_tokens"] > 0
    assert summary["avg_latency_ms"] > 0
    assert summary["error_rate"] > 0  # Last record is error


@pytest.mark.asyncio
async def test_model_stats_groups_by_model(db):
    """Model stats grouped by model name."""
    await _insert_sample(db, 5)
    result = await db.get_model_stats()
    models = result["models"]
    assert len(models) > 0
    # Each entry has required fields
    for m in models:
        assert "model" in m
        assert "provider" in m
        assert "request_count" in m
        assert "cost_usd" in m


@pytest.mark.asyncio
async def test_model_stats_filter_by_provider(db):
    """Filter model stats by provider."""
    await _insert_sample(db, 5)
    result = await db.get_model_stats(provider="openai")
    for m in result["models"]:
        assert m["provider"] == "openai"


@pytest.mark.asyncio
async def test_recent_pagination(db):
    """Pagination works correctly."""
    await _insert_sample(db, 5)
    page1 = await db.get_recent(limit=2, offset=0)
    assert len(page1["requests"]) == 2
    assert page1["total"] == 5
    assert page1["limit"] == 2
    assert page1["offset"] == 0

    page2 = await db.get_recent(limit=2, offset=2)
    assert len(page2["requests"]) == 2


@pytest.mark.asyncio
async def test_recent_since_filter(db):
    """Date filter excludes older records."""
    # Insert with old date
    await db.log_request({
        "id": "old-001",
        "provider": "openai",
        "model": "gpt-4o",
        "status": "success",
        "created_at": "2020-01-01T00:00:00+00:00",
    })
    # Insert with recent date
    await db.log_request({
        "id": "new-001",
        "provider": "openai",
        "model": "gpt-4o",
        "status": "success",
        "created_at": "2026-01-01T00:00:00+00:00",
    })

    result = await db.get_recent(since="2025-01-01T00:00:00+00:00")
    assert result["total"] == 1
    assert result["requests"][0]["id"] == "new-001"


@pytest.mark.asyncio
async def test_error_record_has_status(db):
    """Error records have status='error' and error_message set."""
    await db.log_request({
        "id": "err-001",
        "provider": "openai",
        "model": "gpt-4o",
        "status": "error",
        "error_message": "timeout",
    })
    result = await db.get_recent(limit=1)
    req = result["requests"][0]
    assert req["status"] == "error"
    assert req["error_message"] == "timeout"
