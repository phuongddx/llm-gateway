"""Serial analytics writer — bounds fire-and-forget DB writes."""

import asyncio
import logging

logger = logging.getLogger(__name__)

_DRAIN_TIMEOUT_S = 5.0  # bounded shutdown drain wait
_PURGE_INTERVAL_S = 6 * 3600.0  # locked 6h purge cadence; module constant,
                                # NOT env — the locked env surface gains only
                                # ANALYTICS_RETENTION_DAYS (tests inject via ctor)


class AnalyticsWriter:
    """Serial analytics writer — bounds fire-and-forget DB writes.

    Producers enqueue without blocking (drop-newest on full); a single
    consumer task drains to AnalyticsDB. Client streams never wait on SQLite.
    """

    def __init__(
        self,
        db,
        queue_size: int = 1000,
        retention_days: int = 90,
        purge_interval_s: float = _PURGE_INTERVAL_S,
    ):
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
        self._retention_days = retention_days
        self._purge_interval_s = purge_interval_s
        # Public purge observables (precedent: self.dropped).
        self.purges_run = 0
        self.last_purged = None

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

    async def _drain_queued(self) -> None:
        """Drain records that queued while a purge pass was running.

        Called between DELETE batches (purge_expired's between_batches hook)
        so a burst during a long purge persists mid-pass instead of filling
        the queue cap and dropping (Pitfall 3). Mirrors _run's record path
        exactly — log_request contained, task_done in finally — so join()
        semantics and error containment are identical.
        """
        while True:
            try:
                record = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                await self._db.log_request(record)
            except Exception:
                logger.exception("Analytics write failed")
            finally:
                self._queue.task_done()  # in finally so join() never deadlocks

    async def _purge(self) -> None:
        """One retention pass; failures contained — a purge error must never
        kill the consumer task (all analytics writes would stop)."""
        # Increment first so bounded waits on last_purged stay reliable even
        # if the purge raises before assigning it.
        self.purges_run += 1
        try:
            # between_batches keeps the queue drained between DELETE batches:
            # records enqueued mid-purge are persisted in the batch gaps
            # instead of piling onto the capped queue (Pitfall 3).
            self.last_purged = await self._db.purge_expired(
                self._retention_days, between_batches=self._drain_queued
            )
        except Exception:
            logger.exception("Analytics retention purge failed")

    async def _run(self) -> None:
        # STARTUP purge — first action of the consumer task (locked "before/
        # alongside writer start"): keeps lifespan startup instant (NFR-04)
        # because the purge runs inside the task, and serializes with queued
        # writes on the single connection. Mid-shutdown cancel safety: stop()
        # may cancel mid-purge; each DELETE batch commits individually, so at
        # most one uncommitted batch rolls back at close and the next startup
        # purge resumes.
        await self._purge()
        loop = asyncio.get_running_loop()
        next_purge = loop.time() + self._purge_interval_s
        while True:
            # Deadline wakeup: the wait expires exactly when the next purge
            # is due — one task owns both the record path and the tick
            # (locked: no new scheduler). timeout=0.0 fires immediately when
            # the deadline has already passed.
            timeout = max(0.0, next_purge - loop.time())
            try:
                record = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                record = None
                # queue.get is cancellation-safe on this interpreter (probe
                # R3e: a raced item stays queued); the salvage only reduces
                # pickup latency for an item racing the timeout.
                try:
                    record = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            if record is not None:
                try:
                    await self._db.log_request(record)
                except Exception:
                    logger.exception("Analytics write failed")
                finally:
                    self._queue.task_done()  # in finally so join() never deadlocks
            if loop.time() >= next_purge:
                await self._purge()
                next_purge = loop.time() + self._purge_interval_s  # no drift

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
