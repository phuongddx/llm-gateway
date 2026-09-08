"""Tests for analytics retention — TTL purge lifecycle (knob → lifespan → purge)."""

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

import analytics.db


def _record(i: int) -> dict:
    """Row payload in the exact 12-key shape routes/chat.py enqueues."""
    return {
        "id": f"00000000-0000-0000-0000-{i:012d}",
        "provider": "manifest",
        "model": "gpt-4o",
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": 13,
        "latency_ms": 42,
        "ttft_ms": 5,
        "cost_usd": 0.0,
        "credits_used": 0.0,
        "status": "success",
        "error_message": None,
    }


@pytest.mark.asyncio
async def test_lifespan_startup_purge_removes_expired_rows_end_to_end(monkeypatch, tmp_path):
    """One real lifespan startup: the writer task's first action purges the
    expired row from a pre-seeded existing DB file and retains the fresh one."""
    from main import app, lifespan
    from config import settings

    # Seed a real file DB before lifespan — the purge must apply to existing
    # databases with no manual SQL (ANLT-01).
    db_path = str(tmp_path / "analytics.db")
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    conn.executescript(analytics.db._SCHEMA)
    for row_id, created_at in (
        ("purge-e2e-expired", (now - timedelta(days=91)).isoformat()),
        ("purge-e2e-fresh", now.isoformat()),
    ):
        conn.execute(
            """INSERT INTO request_logs
               (id, provider, model, prompt_tokens, completion_tokens,
                total_tokens, latency_ms, ttft_ms, cost_usd, credits_used,
                status, error_message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row_id, "manifest", "gpt-4o", 0, 0, 0, 0, 0, 0.0, 0.0,
             "success", None, created_at),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "app_api_key", "test-key")
    monkeypatch.setattr(settings, "analytics_db_path", db_path)
    monkeypatch.setattr(settings, "analytics_retention_days", 90)

    async with lifespan(app):
        writer = app.state.analytics_writer
        deadline = time.monotonic() + 5.0  # bounded wait — never a bare sleep
        while writer.last_purged is None:
            if time.monotonic() >= deadline:
                pytest.fail("startup purge did not complete within 5s")
            await asyncio.sleep(0.01)
        assert writer.last_purged == 1

        # Read the file through a fresh raw connection (WAL readers coexist).
        reader = sqlite3.connect(db_path)
        try:
            ids = {row[0] for row in reader.execute("SELECT id FROM request_logs")}
        finally:
            reader.close()
        assert ids == {"purge-e2e-fresh"}
