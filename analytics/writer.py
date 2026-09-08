"""Serial analytics writer — bounds fire-and-forget DB writes."""

import asyncio
import logging

logger = logging.getLogger(__name__)

_DRAIN_TIMEOUT_S = 5.0  # bounded shutdown drain wait


class AnalyticsWriter:
    """Serial analytics writer — bounds fire-and-forget DB writes.

    Producers enqueue without blocking (drop-newest on full); a single
    consumer task drains to AnalyticsDB. Client streams never wait on SQLite.
    """

    def __init__(self, db, queue_size: int = 1000):
        if queue_size < 1:
            # asyncio.Queue treats maxsize <= 0 as UNBOUNDED — refuse instead
            # of silently recreating the OOM hazard this writer exists to prevent.
            raise ValueError(
                f"queue_size must be >= 1 (got {queue_size}); 0 would unbound the queue"
            )
        self._db = db
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task | None = None
        self._stopped = False
        self.dropped = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="analytics-writer")

    def qsize(self) -> int:
        return self._queue.qsize()

    def enqueue(self, record: dict) -> None:
        if self._stopped:
            # Consumer is gone (in-flight stream's finally raced past shutdown)
            # — count + log rather than stranding the record uncounted.
            self.dropped += 1
            logger.warning(
                "Analytics writer stopped — record dropped (%d records dropped total)",
                self.dropped,
            )
            return
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self.dropped += 1  # drop-NEWEST: the incoming record is dropped
            if self.dropped % 50 == 0:
                logger.warning("Analytics queue full — %d records dropped so far", self.dropped)

    async def _run(self) -> None:
        while True:
            record = await self._queue.get()
            try:
                await self._db.log_request(record)
            except Exception:
                logger.exception("Analytics write failed")
            finally:
                self._queue.task_done()  # in finally so join() never deadlocks

    async def wait_drained(self, timeout: float = _DRAIN_TIMEOUT_S) -> None:
        await asyncio.wait_for(self._queue.join(), timeout=timeout)

    async def stop(self, timeout: float = _DRAIN_TIMEOUT_S) -> None:
        if self._task is None:
            self._stopped = True
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Analytics drain timed out after %ss — %d queued records lost",
                timeout,
                self._queue.qsize(),
            )
        # Flip only now — the drain window above still accepts+persists late
        # records ("no lost tail"); from here on the consumer is gone and
        # enqueue() drops+logs instead of stranding records uncounted.
        self._stopped = True
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        logger.info(
            "Analytics writer stopped — %d records dropped total",
            self.dropped + self._queue.qsize(),
        )
