"""Unit tests for analytics.writer — queue lifecycle + concurrent burst proof."""

import asyncio
import json
import logging
import time
from unittest.mock import patch
from uuid import uuid4

import pytest

from analytics.writer import AnalyticsWriter


def _record(i: int) -> dict:
    """Queue payload in the exact 12-key shape routes/chat.py enqueues."""
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


def test_constructor_rejects_nonpositive_queue_size():
    """queue_size<=0 would unbound asyncio.Queue (maxsize<=0 = infinite) — refuse."""
    with pytest.raises(ValueError, match="queue_size"):
        AnalyticsWriter(None, queue_size=0)
    with pytest.raises(ValueError, match="queue_size"):
        AnalyticsWriter(None, queue_size=-3)


# --- Queue unit suite (RELI-02b/c/d + edges) — direct AnalyticsWriter over the
# --- shared analytics_db fixture, no HTTP layer (matches test_analytics_db.py).


@pytest.mark.asyncio
async def test_drop_newest_when_full_counts_and_logs_every_50(analytics_db, caplog):
    """Cap-3 queue, no consumer, 57 enqueues: 3 kept, 54 dropped, one warning at #50."""
    writer = AnalyticsWriter(analytics_db, queue_size=3)  # deliberately never started

    with caplog.at_level(logging.WARNING):
        for i in range(57):
            writer.enqueue(_record(i))

    assert writer.qsize() == 3  # queued records are never evicted
    assert writer.dropped == 54  # the INCOMING record is dropped each time
    warnings = [r for r in caplog.records if "records dropped" in r.getMessage()]
    assert len(warnings) == 1  # every-50 cadence fired exactly once (at drop #50)
    assert "50 records dropped" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_identical_payload_records_stay_distinct(analytics_db):
    """Two records identical in every payload field stay two rows (uuid4 PK)."""
    writer = AnalyticsWriter(analytics_db, queue_size=10)
    writer.start()

    payload = {key: value for key, value in _record(0).items() if key != "id"}
    # Byte-identical payloads; distinct uuid4 ids exactly as routes/chat.py
    # generates them per request — equal content never merges or dedupes.
    writer.enqueue({**payload, "id": str(uuid4())})
    writer.enqueue({**payload, "id": str(uuid4())})

    await writer.wait_drained(5.0)
    recent = await analytics_db.get_recent(limit=10)
    assert recent["total"] == 2
    assert len({row["id"] for row in recent["requests"]}) == 2
    await writer.stop()


@pytest.mark.asyncio
async def test_gated_writer_drains_exactly_once_after_release(analytics_db):
    """Writer blocked on an Event gate drains nothing until release, then exactly once."""
    writer = AnalyticsWriter(analytics_db, queue_size=10)
    gate = asyncio.Event()
    original_log = analytics_db.log_request

    async def gated_log(record):
        await gate.wait()
        await original_log(record)

    analytics_db.log_request = gated_log
    writer.start()
    for i in range(5):
        writer.enqueue(_record(i))

    assert writer.qsize() == 5  # consumer task has not run yet (no yield since start)
    await asyncio.sleep(0)  # brief yield: consumer takes one record, blocks at the gate
    assert writer.qsize() == 4  # exactly one record in flight; nothing drained
    assert (await analytics_db.get_recent(limit=10))["total"] == 0

    gate.set()
    await writer.wait_drained(5.0)
    recent = await analytics_db.get_recent(limit=10)
    assert recent["total"] == 5
    assert len({row["id"] for row in recent["requests"]}) == 5
    await writer.stop()


@pytest.mark.asyncio
async def test_stop_bounded_on_stuck_writer_and_counts_residue(analytics_db, caplog):
    """stop(timeout) on a never-released writer returns bounded and logs the residue."""
    writer = AnalyticsWriter(analytics_db, queue_size=10)
    gate = asyncio.Event()  # never set
    original_log = analytics_db.log_request

    async def stuck_log(record):
        await gate.wait()
        await original_log(record)

    analytics_db.log_request = stuck_log
    writer.start()
    writer.enqueue(_record(0))
    writer.enqueue(_record(1))
    await asyncio.sleep(0)  # consumer takes record 0 and blocks forever

    with caplog.at_level(logging.INFO):
        started = time.monotonic()
        await writer.stop(timeout=0.5)
        elapsed = time.monotonic() - started

    assert elapsed < 2.0  # bounded well above the 0.5s drain timeout
    assert any("drain timed out" in r.getMessage() for r in caplog.records)
    assert any("1 queued records lost" in r.getMessage() for r in caplog.records)
    assert any("dropped total" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_stop_drains_healthy_writer_and_persists_all(analytics_db):
    """stop() on a healthy writer drains the queue and persists every row."""
    writer = AnalyticsWriter(analytics_db, queue_size=10)
    writer.start()
    for i in range(3):
        writer.enqueue(_record(i))

    await writer.stop()

    assert writer.qsize() == 0
    recent = await analytics_db.get_recent(limit=10)
    assert recent["total"] == 3
    assert len({row["id"] for row in recent["requests"]}) == 3


@pytest.mark.asyncio
async def test_stop_on_idle_or_never_started_writer_returns_immediately(analytics_db):
    """stop() is error-free on a never-started writer and on an idle started one."""
    never_started = AnalyticsWriter(analytics_db, queue_size=3)
    await never_started.stop()  # no consumer task — returns immediately

    idle = AnalyticsWriter(analytics_db, queue_size=3)
    idle.start()
    await asyncio.sleep(0)  # let the consumer reach queue.get()
    started = time.monotonic()
    await idle.stop()
    assert time.monotonic() - started < 2.0
    assert idle.qsize() == 0
    assert (await analytics_db.get_recent(limit=10))["total"] == 0  # zero requests → zero rows


@pytest.mark.asyncio
async def test_enqueue_after_stop_is_counted_and_logged_never_stranded(analytics_db, caplog):
    """Post-stop enqueues (in-flight stream racing shutdown) are dropped,
    counted, and logged — not silently stranded in a dead queue (MN-01)."""
    writer = AnalyticsWriter(analytics_db, queue_size=3)
    writer.start()
    await writer.stop()

    with caplog.at_level(logging.WARNING):
        writer.enqueue(_record(0))

    assert writer.qsize() == 0  # nothing left stranded in the dead queue
    assert writer.dropped == 1
    assert any(
        "writer stopped" in r.getMessage() and "dropped" in r.getMessage()
        for r in caplog.records
    )
    assert (await analytics_db.get_recent(limit=10))["total"] == 0  # never persisted


@pytest.mark.asyncio
async def test_single_record_exactly_once(analytics_db):
    """A single enqueued record lands as exactly one row."""
    writer = AnalyticsWriter(analytics_db, queue_size=3)
    writer.start()
    writer.enqueue(_record(0))

    await writer.wait_drained(5.0)

    recent = await analytics_db.get_recent(limit=10)
    assert recent["total"] == 1
    assert recent["requests"][0]["id"] == _record(0)["id"]
    await writer.stop()


# --- Concurrent burst + client-disconnect suite (RELI-02a + edge) ---


def _stream_tokens(text: str) -> list[str]:
    """Token payloads from an SSE body, in stream order."""
    return [
        json.loads(line[len("data: "):])["token"]
        for line in text.splitlines()
        if line.startswith("data: ") and line[len("data: "):] != "[DONE]"
    ]


@pytest.mark.asyncio
async def test_concurrent_burst_full_delivery_exactly_once(
    client, auth_headers, analytics_writer, analytics_db
):
    """20 concurrent streams over one ASGI client, slowed writer: full tokens, exactly-once rows."""

    def _provider_for(i: int):
        class BurstProvider:
            async def chat_stream(self, messages, system_prompt, params=None):
                yield (f"tok{i}", None)
                yield ("", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

        return BurstProvider()

    original_log = analytics_db.log_request

    async def slowed_log(record):
        await asyncio.sleep(0.005)  # deterministic lag — never a blocking sleep
        await original_log(record)

    analytics_db.log_request = slowed_log  # the fixture writer's db — slows its drain

    samples: list[int] = []

    async def sampler():
        for _ in range(50):
            samples.append(analytics_writer.qsize())
            await asyncio.sleep(0.001)

    sampler_task = asyncio.create_task(sampler())
    with patch("routes.chat.create_provider", side_effect=[_provider_for(i) for i in range(20)]), \
         patch("routes.chat.resolve_provider", return_value=("manifest", "gpt-4o")):
        responses = await asyncio.gather(*[
            client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "burst"}]},
                headers=auth_headers,
            )
            for _ in range(20)
        ])
    await sampler_task
    await analytics_writer.wait_drained(5.0)

    assert all(r.status_code == 200 for r in responses)
    tokens_per_response = [_stream_tokens(r.text) for r in responses]
    for r, tokens in zip(responses, tokens_per_response):
        assert r.text.endswith("data: [DONE]\n\n")
        assert len(tokens) == 1  # its provider's own token, and nothing else
    all_tokens = [token for tokens in tokens_per_response for token in tokens]
    assert sorted(all_tokens) == sorted(f"tok{i}" for i in range(20))  # every stream delivered

    # Bounded, sampled mid-burst: with exactly-once enqueue per stream, queue
    # depth can never exceed the 20 in-flight producers — an exactly-once
    # violation or runaway enqueue makes this fail. (The queue's own cap is
    # pinned by test_drop_newest_when_full_counts_and_logs_every_50 at queue_size=3.)
    assert samples and max(samples) <= 20

    recent = await analytics_db.get_recent(limit=100)
    assert recent["total"] == 20  # exactly once
    assert len({row["id"] for row in recent["requests"]}) == 20


@pytest.mark.asyncio
async def test_client_disconnect_midstream_still_enqueues_exactly_once(
    analytics_writer, analytics_db
):
    """Direct generator aclose (GeneratorExit) still enqueues exactly one record."""
    from routes.chat import ChatRequest, _tracked_stream

    class MultiTokenProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            for i in range(5):
                yield (f"chunk{i}", None)
            yield ("", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

    request = ChatRequest(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    gen = _tracked_stream(
        MultiTokenProvider(), request, "manifest", "gpt-4o", analytics_writer, None
    )
    first_frame = await gen.__anext__()
    assert first_frame.startswith("data: ")
    await gen.aclose()  # client disconnect → GeneratorExit → finally-block enqueues once

    await analytics_writer.wait_drained(5.0)
    recent = await analytics_db.get_recent(limit=10)
    assert recent["total"] == 1
    assert len({row["id"] for row in recent["requests"]}) == 1
