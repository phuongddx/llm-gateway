"""Tests for analytics retention — TTL purge lifecycle (knob → lifespan → purge)."""

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import analytics.db
from analytics.writer import AnalyticsWriter


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

_INSERT_SQL = """INSERT INTO request_logs
    (id, provider, model, prompt_tokens, completion_tokens, total_tokens,
     latency_ms, ttft_ms, cost_usd, credits_used, status, error_message, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""


def _row(record: dict) -> tuple:
    """13-column INSERT tuple in log_request's column order."""
    return (
        record["id"], record["provider"], record["model"],
        record["prompt_tokens"], record["completion_tokens"], record["total_tokens"],
        record["latency_ms"], record["ttft_ms"], record["cost_usd"],
        record["credits_used"], record["status"], record["error_message"],
        record["created_at"],
    )


async def _seed_bulk(db, records) -> None:
    """Large seeds: one executemany + single commit through the connection."""
    await db._db.executemany(_INSERT_SQL, [_row(r) for r in records])
    await db._db.commit()


async def _pragma(db, name: str) -> int:
    """Read a single-int pragma via the probe-verified cursor shape."""
    async with db._db.execute(f"PRAGMA {name}") as c:
        return (await c.fetchone())[0]


@pytest.mark.asyncio
async def test_purge_expired_boundary_trio_exact_cutoff_retained(analytics_db):
    """Strict predicate: 1µs-older-than-cutoff purged; exactly-at-cutoff and newest retained."""
    now = datetime.now(timezone.utc)
    await analytics_db.log_request({
        **_record(1), "id": "boundary-1us-older",
        "created_at": (now - timedelta(days=90, microseconds=1)).isoformat(),
    })
    await analytics_db.log_request({
        **_record(2), "id": "boundary-exact-cutoff",
        "created_at": (now - timedelta(days=90)).isoformat(),
    })
    await analytics_db.log_request({
        **_record(3), "id": "boundary-fresh",
        "created_at": now.isoformat(),
    })

    deleted = await analytics_db.purge_expired(90, now=now)

    assert deleted == 1
    recent = await analytics_db.get_recent(limit=10)
    assert {row["id"] for row in recent["requests"]} == {
        "boundary-exact-cutoff",
        "boundary-fresh",
    }


@pytest.mark.asyncio
async def test_purge_retention_zero_keep_forever_off(analytics_db):
    """retention_days=0 is the locked keep-forever opt-out — nothing is deleted."""
    now = datetime.now(timezone.utc)
    await analytics_db.log_request({
        **_record(1), "id": "keep-forever-row",
        "created_at": (now - timedelta(days=91)).isoformat(),
    })

    deleted = await analytics_db.purge_expired(0)

    assert deleted == 0
    assert (await analytics_db.get_recent(limit=10))["total"] == 1


@pytest.mark.asyncio
async def test_purge_multi_batch_deletes_all_expired(analytics_db):
    """2500 expired rows cross batch boundaries (batch=1000); all deleted, fresh kept, idempotent."""
    now = datetime.now(timezone.utc)
    expired_at = (now - timedelta(days=91)).isoformat()
    expired = [{**_record(i), "id": f"expired-{i:04d}", "created_at": expired_at}
               for i in range(2500)]
    fresh = [{**_record(10_000 + i), "id": f"fresh-{i:04d}", "created_at": now.isoformat()}
             for i in range(300)]
    await _seed_bulk(analytics_db, expired + fresh)

    assert await analytics_db.purge_expired(90) == 2500
    assert (await analytics_db.get_recent(limit=1))["total"] == 300
    assert await analytics_db.purge_expired(90) == 0  # second pass: nothing left


@pytest.mark.asyncio
async def test_purge_rejects_batch_below_one_instead_of_spinning(analytics_db):
    """batch=0/-1 make the loop's only exit (rowcount < batch) unreachable —
    the guard raises ValueError before deleting anything (WR-01), mirroring
    the writer's queue_size ctor guard. wait_for bounds each call so a
    regression fails in 2s instead of hanging the consumer forever."""
    now = datetime.now(timezone.utc)
    expired_at = (now - timedelta(days=91)).isoformat()
    await _seed_bulk(analytics_db, [
        {**_record(i), "id": f"guard-{i:04d}", "created_at": expired_at}
        for i in range(5)
    ])

    for bad_batch in (0, -1):
        with pytest.raises(ValueError, match="batch must be >= 1"):
            await asyncio.wait_for(
                analytics_db.purge_expired(90, batch=bad_batch), timeout=2.0
            )

    # The guard fires before the DELETE loop — no rows lost to a bad batch.
    assert (await analytics_db.get_recent(limit=10))["total"] == 5


@pytest.mark.asyncio
async def test_purge_reclaims_space_incremental_vacuum(tmp_path):
    """Fresh auto_vacuum=INCREMENTAL file: purge drains freelist to 0 and drops page_count."""
    db = analytics.db.AnalyticsDB(str(tmp_path / "reclaim.db"))
    await db.initialize()
    try:
        assert await _pragma(db, "auto_vacuum") == 2
        now = datetime.now(timezone.utc)
        expired_at = (now - timedelta(days=91)).isoformat()
        rows = [{**_record(i), "id": f"expired-{i:04d}", "created_at": expired_at}
                for i in range(3000)]
        rows += [{**_record(10_000 + i), "id": f"fresh-{i:04d}", "created_at": now.isoformat()}
                 for i in range(100)]
        await _seed_bulk(db, rows)
        pages_before = await _pragma(db, "page_count")

        assert await db.purge_expired(90) == 3000

        assert await _pragma(db, "freelist_count") == 0
        assert await _pragma(db, "page_count") < pages_before
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_vacuum_loop_terminates_on_legacy_auto_vacuum_zero_db(tmp_path):
    """Legacy auto_vacuum=0 file: the no-decrease guard bounds the vacuum loop — no spin."""
    db_path = str(tmp_path / "legacy.db")
    now = datetime.now(timezone.utc)
    expired_at = (now - timedelta(days=91)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.executescript(analytics.db._SCHEMA)  # raw create: auto_vacuum stays 0
    conn.executemany(
        _INSERT_SQL,
        [_row({**_record(i), "id": f"legacy-{i:04d}", "created_at": expired_at})
         for i in range(500)],
    )
    conn.commit()
    conn.close()

    db = analytics.db.AnalyticsDB(db_path)
    await db.initialize()  # the auto_vacuum pragma silently no-ops here
    try:
        await asyncio.wait_for(db.purge_expired(90), timeout=10.0)
        assert (await db.get_recent(limit=10))["total"] == 0  # delete works regardless
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_purge_log_reports_count_and_no_row_contents(analytics_db, caplog):
    """Purge log is count-only: deleted count present, row ids/models never logged."""
    now = datetime.now(timezone.utc)
    expired_at = (now - timedelta(days=91)).isoformat()
    await analytics_db.log_request({
        **_record(1), "id": "privacy-probe-aaa", "model": "glm-5.3-purge-probe",
        "created_at": expired_at,
    })
    await analytics_db.log_request({
        **_record(2), "id": "privacy-probe-bbb", "model": "glm-5.3-purge-probe",
        "created_at": expired_at,
    })

    with caplog.at_level(logging.INFO, logger="analytics.db"):
        assert await analytics_db.purge_expired(90) == 2

    purge_records = [r for r in caplog.records if "Analytics retention purge" in r.getMessage()]
    assert purge_records, "expected a purge log line"
    assert "2" in purge_records[0].getMessage()  # deleted count is reported
    assert "privacy-probe-aaa" not in caplog.text
    assert "privacy-probe-bbb" not in caplog.text
    assert "glm-5.3-purge-probe" not in caplog.text

# --- Periodic scheduling + mid-purge drain (02-02 Task 1) ---


@pytest.mark.asyncio
async def test_periodic_tick_purges_reseeded_expired_rows(
    analytics_retention_writer, analytics_db
):
    """Interval 0.05s: a row seeded AFTER startup is removed by a later,
    periodic pass — purges_run >= 2 proves the deadline wakeup keeps firing."""
    writer = analytics_retention_writer
    # Wait out the startup purge first so only a LATER pass can remove the
    # reseeded row (02-01 already pins the startup pass; this pins periodicity).
    deadline = time.monotonic() + 5.0
    while writer.last_purged is None:
        if time.monotonic() >= deadline:
            pytest.fail("startup purge did not complete within 5s")
        await asyncio.sleep(0.01)

    seeded = {
        **_record(1),
        "id": "tick-reseeded-expired",
        "created_at": (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(),
    }
    await analytics_db.log_request(seeded)  # direct DB write — bypasses the queue

    await asyncio.sleep(0.25)  # bounded: ~5 ticks at the 0.05s interval

    assert writer.purges_run >= 2  # the startup pass plus at least one tick
    recent = await analytics_db.get_recent(limit=10)
    assert "tick-reseeded-expired" not in {row["id"] for row in recent["requests"]}


@pytest.mark.asyncio
async def test_startup_purge_does_not_block_lifespan_readiness(monkeypatch, tmp_path):
    """With purge_expired gated on a never-set Event, the lifespan still
    reaches its yield point — request readiness never awaits a purge (NFR-04);
    the fire-and-forget guarantee holds at startup."""
    from main import app, lifespan
    from config import settings

    entered = asyncio.Event()  # set at the lifespan yield point (request-ready)
    gate = asyncio.Event()  # closed until the assertions are done
    hold_open = asyncio.Event()  # keeps the lifespan inside its async-with
    calls = {"started": 0, "returned": 0}
    original_purge = analytics.db.AnalyticsDB.purge_expired

    async def gated_purge(self, *args, **kwargs):
        calls["started"] += 1
        await gate.wait()
        result = await original_purge(self, *args, **kwargs)
        calls["returned"] += 1
        return result

    monkeypatch.setattr(analytics.db.AnalyticsDB, "purge_expired", gated_purge)
    monkeypatch.setattr(settings, "app_api_key", "test-key")
    monkeypatch.setattr(settings, "analytics_db_path", str(tmp_path / "nblock.db"))
    monkeypatch.setattr(settings, "analytics_retention_days", 90)

    async def run_lifespan():
        async with lifespan(app):
            entered.set()
            await hold_open.wait()

    lifespan_task = asyncio.create_task(run_lifespan())
    await asyncio.wait_for(entered.wait(), timeout=2.0)  # ready, bounded

    # The writer's startup purge has STARTED but has NOT returned (gate still
    # closed) while the app is already request-ready — proof readiness never
    # awaits a purge.
    deadline = time.monotonic() + 2.0
    while calls["started"] < 1:
        if time.monotonic() >= deadline:
            pytest.fail("writer startup purge did not start within 2s")
        await asyncio.sleep(0.01)
    assert calls["returned"] == 0

    gate.set()
    hold_open.set()
    await asyncio.wait_for(lifespan_task, timeout=5.0)


@pytest.mark.asyncio
async def test_interleave_queue_drained_between_purge_batches(analytics_db):
    """2500 expired rows in the startup purge; 30 fresh records enqueued
    synchronously right after start: the between-batches drain persists them
    mid-purge — dropped == 0, exactly 30 rows survive, queue empties."""
    expired = [
        {
            **_record(i),
            "created_at": (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(),
        }
        for i in range(2500)
    ]
    await _seed_bulk(analytics_db, expired)

    writer = AnalyticsWriter(
        analytics_db, queue_size=1000, retention_days=90, purge_interval_s=5.0
    )
    writer.start()
    for i in range(2500, 2530):  # 30 fresh records, synchronously — no await
        writer.enqueue(_record(i))

    # Bounded wait for the startup purge to finish all batches (convention:
    # poll last_purged, never a bare sleep — a loaded runner could otherwise
    # assert mid-purge partial state).
    deadline = time.monotonic() + 5.0
    while writer.last_purged != 2500:
        if time.monotonic() >= deadline:
            pytest.fail("startup purge did not complete within 5s")
        await asyncio.sleep(0.01)

    assert writer.dropped == 0
    recent = await analytics_db.get_recent(limit=100)
    assert recent["total"] == 30  # expired gone, fresh persisted exactly once
    assert {row["id"] for row in recent["requests"]} == {
        _record(i)["id"] for i in range(2500, 2530)
    }
    await writer.wait_drained(5.0)
    assert writer.qsize() == 0
    await writer.stop()


@pytest.mark.asyncio
async def test_purge_between_batches_hook_awaited_per_batch(analytics_db):
    """between_batches fires after EVERY per-batch commit, including the
    final partial one: 2500 rows at batch 1000 -> exactly 3 invocations,
    2500 deleted."""
    expired = [
        {
            **_record(i),
            "created_at": (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(),
        }
        for i in range(2500)
    ]
    await _seed_bulk(analytics_db, expired)
    calls: list[int] = []

    async def between_batches_hook():
        calls.append(1)

    deleted = await analytics_db.purge_expired(90, between_batches=between_batches_hook)

    assert len(calls) == 3  # batches of 1000 + 1000 + 500: hook after each commit
    assert deleted == 2500

# --- Integration proofs (02-02 Task 2) ---


def _stream_tokens(text: str) -> list[str]:
    """Token payloads from an SSE body, in stream order."""
    return [
        json.loads(line[len("data: "):])["token"]
        for line in text.splitlines()
        if line.startswith("data: ") and line[len("data: "):] != "[DONE]"
    ]


@pytest.mark.asyncio
async def test_endpoints_serve_retained_data_after_purge(
    client, auth_headers, analytics_db
):
    """After a purge pass, all four analytics endpoints report ONLY retained
    data — totals, model rows, request ids, and 5h/7d credit aggregates
    exclude the purged rows while correctly including the fresh ones."""
    now = datetime.now(timezone.utc)
    old_manifest = {
        **_record(0),
        "id": "purged-old-manifest",
        "model": "gpt-4-turbo",  # a model only the purged row used
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "total_tokens": 1500,
        "created_at": (now - timedelta(days=91)).isoformat(),
    }
    old_zai = {
        **_record(1),
        "id": "purged-old-zai",
        "provider": "zai-coding",
        "model": "glm-5.3-flash",
        "credits_used": 120.0,
        "created_at": (now - timedelta(days=91)).isoformat(),  # outside 7d anyway
    }
    fresh_manifest = {
        **_record(2),
        "id": "fresh-manifest",
        "model": "gpt-4o",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "created_at": (now - timedelta(hours=1)).isoformat(),
    }
    fresh_zai = {
        **_record(3),
        "id": "fresh-zai",
        "provider": "zai-coding",
        "model": "glm-5.3",
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
        "credits_used": 50.0,
        "created_at": (now - timedelta(hours=1)).isoformat(),  # inside 5h window
    }
    for row in (old_manifest, old_zai, fresh_manifest, fresh_zai):
        await analytics_db.log_request(row)

    assert await analytics_db.purge_expired(90) == 2

    response = await client.get("/v1/analytics/summary", headers=auth_headers)
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_requests"] == 2
    assert summary["total_prompt_tokens"] == 120  # 100 + 20; the 1000 is purged
    assert summary["total_completion_tokens"] == 60  # 50 + 10; the 500 is purged
    assert summary["total_tokens"] == 180

    response = await client.get("/v1/analytics/models", headers=auth_headers)
    assert response.status_code == 200
    models = response.json()
    assert {row["model"] for row in models["models"]} == {"gpt-4o", "glm-5.3"}

    response = await client.get(
        "/v1/analytics/requests?limit=50", headers=auth_headers
    )
    assert response.status_code == 200
    requests_page = response.json()
    assert requests_page["total"] == 2
    assert {row["id"] for row in requests_page["requests"]} == {
        "fresh-manifest",
        "fresh-zai",
    }

    response = await client.get("/v1/analytics/credits", headers=auth_headers)
    assert response.status_code == 200
    credits = response.json()
    assert credits["window_5h"]["credits_used"] == pytest.approx(50.0)
    assert credits["window_7d_rolling"]["credits_used"] == pytest.approx(50.0)
    assert credits["by_model"]["glm-5.3"]["credits_used"] == pytest.approx(50.0)
    assert credits["by_model"]["glm-5.3"]["requests"] == 1
    assert "glm-5.3-flash" not in credits["by_model"]


@pytest.mark.asyncio
async def test_burst_streams_unblocked_during_purge(
    client, auth_headers, analytics_writer, analytics_db
):
    """20 concurrent streams while a 0.03s-tick writer purges 1500 expired
    rows: every stream delivers its full token sequence + [DONE], exactly-once
    rows, zero drops — purging never blocks or delays streaming."""
    expired = [
        {
            **_record(i),
            "created_at": (datetime.now(timezone.utc) - timedelta(days=91)).isoformat(),
        }
        for i in range(1500)
    ]
    await _seed_bulk(analytics_db, expired)

    def _provider_for(i: int):
        class BurstProvider:
            async def chat_stream(self, messages, system_prompt, params=None):
                yield (f"tok{i}-a", None)
                yield (f"tok{i}-b", None)
                yield ("", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

        return BurstProvider()

    original_log = analytics_db.log_request

    async def slowed_log(record):
        await asyncio.sleep(0.005)  # deterministic lag — never a blocking sleep
        await original_log(record)

    analytics_db.log_request = slowed_log  # the fixture writer's db — slows its drain

    from main import app

    # Routes read app.state per request — the swap takes effect for every
    # burst request. The 0.03s tick makes purges interleave with the streams.
    ticking = AnalyticsWriter(
        analytics_db, queue_size=1000, retention_days=90, purge_interval_s=0.03
    )
    ticking.start()
    app.state.analytics_writer = ticking
    responses = []  # bound pre-try (IN-02): the post-finally asserts must
    # never hit an unbound name if the gather's error path is ever widened
    try:
        with patch(
            "routes.chat.create_provider", side_effect=[_provider_for(i) for i in range(20)]
        ), patch(
            "routes.chat.resolve_provider", return_value=("manifest", "gpt-4o")
        ):
            responses = await asyncio.gather(*[
                client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": "burst"}],
                    },
                    headers=auth_headers,
                )
                for _ in range(20)
            ])
        await ticking.wait_drained(5.0)
        # The tick keeps firing: bounded wait for at least one post-startup
        # purge (wait_drained can return mid-purge — the between-batches hook
        # empties the queue before the pass ends; never wall-clock waits).
        deadline = time.monotonic() + 2.0
        while ticking.purges_run < 2:
            if time.monotonic() >= deadline:
                pytest.fail("periodic purge tick did not fire within 2s")
            await asyncio.sleep(0.01)
    finally:
        app.state.analytics_writer = analytics_writer
        await ticking.stop()

    assert all(r.status_code == 200 for r in responses)
    for r in responses:
        assert r.text.endswith("data: [DONE]\n\n")
    tokens_per_response = [_stream_tokens(r.text) for r in responses]
    assert all(len(tokens) == 2 for tokens in tokens_per_response)
    all_tokens = [token for tokens in tokens_per_response for token in tokens]
    assert sorted(all_tokens) == sorted(
        token for i in range(20) for token in (f"tok{i}-a", f"tok{i}-b")
    )

    recent = await analytics_db.get_recent(limit=100)
    assert recent["total"] == 20  # exactly once; the 1500 expired rows are gone
    assert len({row["id"] for row in recent["requests"]}) == 20
    assert ticking.dropped == 0
    assert ticking.purges_run >= 2  # purges actually interleaved with the burst
