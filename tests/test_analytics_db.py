"""Unit tests for analytics.db — AnalyticsDB CRUD operations."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from analytics.cost import is_peak
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


# --- credits_used column + get_credits_summary ---


def _credit_record(model="glm-5.3", credits=36.6, minutes_ago=0, provider="zai-coding"):
    created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "id": f"row-{model}-{minutes_ago}-{credits}",
        "provider": provider,
        "model": model,
        "prompt_tokens": 150000,
        "completion_tokens": 3000,
        "total_tokens": 153000,
        "credits_used": credits,
        "created_at": created.isoformat(),
    }


@pytest.mark.asyncio
async def test_log_request_persists_credits(db):
    await db.log_request(_credit_record(credits=12.5))
    summary = await db.get_credits_summary()
    assert summary["credits_5h"] == pytest.approx(12.5)
    assert summary["credits_7d"] == pytest.approx(12.5)


@pytest.mark.asyncio
async def test_credits_summary_windows(db):
    await db.log_request(_credit_record(credits=10, minutes_ago=60))       # inside 5h
    await db.log_request(_credit_record(credits=20, minutes_ago=8 * 60))   # outside 5h, inside 7d
    await db.log_request(_credit_record(credits=40, minutes_ago=8 * 24 * 60))  # outside both
    summary = await db.get_credits_summary()
    assert summary["credits_5h"] == pytest.approx(10)
    assert summary["credits_7d"] == pytest.approx(30)
    assert summary["by_model"]["glm-5.3"]["credits_used"] == pytest.approx(30)
    assert summary["by_model"]["glm-5.3"]["requests"] == 2


@pytest.mark.asyncio
async def test_credits_summary_excludes_manifest_rows(db):
    await db.log_request(_credit_record(provider="manifest", credits=99))
    summary = await db.get_credits_summary()
    assert summary["credits_5h"] == 0.0
    assert summary["by_model"] == {}


@pytest.mark.asyncio
async def test_credits_summary_off_peak_share_and_empty(db):
    assert (await db.get_credits_summary())["off_peak_share"] is None


@pytest.mark.asyncio
async def test_credits_summary_off_peak_share_single_row(db):
    await db.log_request(_credit_record(credits=10))
    summary = await db.get_credits_summary()
    expected = 0.0 if is_peak(datetime.now(timezone.utc)) else 1.0
    assert summary["off_peak_share"] == expected


@pytest.mark.asyncio
async def test_migration_adds_column_to_preexisting_schema(tmp_path):
    import sqlite3

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE request_logs (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0, latency_ms INTEGER DEFAULT 0,
            ttft_ms INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'success', error_message TEXT,
            created_at TEXT NOT NULL)"""
    )
    conn.commit()
    conn.close()

    db = AnalyticsDB(path)
    await db.initialize()
    await db.log_request(_credit_record(credits=5.0))
    summary = await db.get_credits_summary()
    await db.close()
    assert summary["credits_7d"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_initialize_is_idempotent_for_credits_column(tmp_path):
    db = AnalyticsDB(str(tmp_path / "fresh.db"))
    await db.initialize()
    await db.close()
    db = AnalyticsDB(str(tmp_path / "fresh.db"))
    await db.initialize()  # second init: CREATE IF NOT EXISTS + ALTER must not raise
    await db.close()
