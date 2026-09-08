"""SQLite-backed analytics storage with async queries."""

import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import aiosqlite

from analytics.cost import is_peak

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS request_logs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    ttft_ms INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    credits_used REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'success',
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_model ON request_logs(model);
CREATE INDEX IF NOT EXISTS idx_logs_provider ON request_logs(provider);
"""
_PURGE_BATCH = 1000  # ≈1000 rows per commit (locked) — keeps WAL checkpoints short


class AnalyticsDB:
    def __init__(self, db_path: str = "data/analytics.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create tables and enable WAL mode."""
        self._db = await aiosqlite.connect(self.db_path)
        # auto_vacuum must be set BEFORE any CREATE TABLE — SQLite silently
        # refuses the flip on a DB that already has tables (probe P1).
        try:
            await self._db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        except sqlite3.OperationalError:
            # Read-only DB files reject the header write here — write_probe()
            # owns the curated abort for that case (Phase-1 contract, IM-02).
            pass
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        # Migration: older databases predate the credits_used column
        try:
            await self._db.execute(
                "ALTER TABLE request_logs ADD COLUMN credits_used REAL NOT NULL DEFAULT 0.0"
            )
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e):
                raise
        await self._db.commit()
        async with self._db.execute("PRAGMA auto_vacuum") as c:
            auto_vacuum = (await c.fetchone())[0]
        if auto_vacuum == 0:
            # Pre-existing populated file: the pragma above silently no-ops
            # (Pitfall 2) — informational only, never an error.
            logger.info(
                "auto_vacuum is off on this legacy analytics DB — the one-time "
                "VACUUM migration documented in README enables space reclamation"
            )
        logger.info("Analytics DB initialized at %s", self.db_path)

    async def write_probe(self) -> None:
        """Prove the handle is writable with a real write.

        A read-only DB file (mode 0444, ro-mounted volume) passes connect()
        and the WAL pragma silently — every later log_request would then fail
        per-record. Startup calls this to fail fast instead.
        """
        await self._db.execute("CREATE TABLE IF NOT EXISTS _write_probe(x)")
        await self._db.execute("DROP TABLE _write_probe")
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def log_request(self, record: dict) -> None:
        """Insert a request log record. Fire-and-forget safe."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO request_logs
                   (id, provider, model, prompt_tokens, completion_tokens,
                    total_tokens, latency_ms, ttft_ms, cost_usd, credits_used,
                    status, error_message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["id"],
                    record["provider"],
                    record["model"],
                    record.get("prompt_tokens", 0),
                    record.get("completion_tokens", 0),
                    record.get("total_tokens", 0),
                    record.get("latency_ms", 0),
                    record.get("ttft_ms", 0),
                    record.get("cost_usd", 0.0),
                    record.get("credits_used", 0.0),
                    record.get("status", "success"),
                    record.get("error_message"),
                    record.get("created_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
            await self._db.commit()
        except Exception:
            logger.exception("Failed to log request to analytics DB")

    async def purge_expired(
        self,
        retention_days: int,
        batch: int = _PURGE_BATCH,
        *,
        now: datetime | None = None,
        between_batches: Callable[[], Awaitable[None]] | None = None,
    ) -> int:
        """Delete request_logs rows strictly older than retention_days; reclaim space.

        A row exactly AT the cutoff instant is RETAINED (strict <). Returns the
        number of rows deleted. Unlike log_request this propagates DB errors —
        it returns int for test asserts and the writer loop owns containment.
        between_batches, when given, is awaited after every per-batch commit
        (including the final partial one) so the caller can drain work between
        DELETE batches.
        """
        if not self._db or retention_days <= 0:  # 0 = keep-forever opt-out
            return 0
        if batch < 1:
            # batch=0: DELETE...LIMIT 0 deletes 0 rows and rowcount(0) < 0 is
            # never true; negative: SQLite reads LIMIT -1 as unlimited, then
            # 0 < -1 never fires — either way the loop below spins forever on
            # the one shared connection. Same treatment as the writer's
            # queue_size guard: fail fast on misconfiguration.
            raise ValueError(
                f"batch must be >= 1 (got {batch}); 0/negative never terminates the DELETE loop"
            )
        cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=retention_days)).isoformat()
        deleted = 0
        while True:
            # No DELETE...LIMIT on this build (probe P3a) — the rowid-subquery
            # form rides the covering index idx_logs_created_at (probe P3c).
            cur = await self._db.execute(
                "DELETE FROM request_logs WHERE rowid IN "
                "(SELECT rowid FROM request_logs WHERE created_at < ? LIMIT ?)",
                (cutoff, batch),
            )
            deleted += cur.rowcount
            await self._db.commit()  # per-batch: short WAL checkpoints (locked)
            if between_batches is not None:
                # Inter-batch hook: lets the writer drain queue records that
                # arrived mid-purge (Pitfall 3 — purge-starved queue drops).
                await between_batches()
            if cur.rowcount < batch:
                break
        # Guarded reclamation: this SQLite build moves exactly ONE page per
        # incremental_vacuum call (probes R2/R3a); the no-decrease break also
        # terminates legacy auto_vacuum=0 files where the pragma no-ops
        # (Pitfalls 1/2) instead of spinning forever.
        async with self._db.execute("PRAGMA freelist_count") as c:
            last_free = (await c.fetchone())[0]
        for _ in range(last_free * 2 + 16):  # hard bound: freelist size + slack
            await self._db.execute("PRAGMA incremental_vacuum")
            async with self._db.execute("PRAGMA freelist_count") as c:
                free = (await c.fetchone())[0]
            if free == 0 or free >= last_free:  # freelist drained, or stalled
                break
            last_free = free
        # Non-blocking checkpoint (busy=0 verified, probe P5) keeps the -wal
        # file bounded after a purge pass; never TRUNCATE from the hot path.
        await self._db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        if deleted:
            logger.info(
                "Analytics retention purge: %d rows older than %dd removed",
                deleted,
                retention_days,
            )
        return deleted

    async def get_summary(self, since: str | None = None) -> dict:
        """Aggregate stats across all requests, optionally filtered by date."""
        if not self._db:
            return {"total_requests": 0, "since": since}
        query = """
            SELECT COUNT(*) as total_requests,
                   COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                   COALESCE(SUM(total_tokens), 0) as total_total_tokens,
                   COALESCE(SUM(cost_usd), 0.0) as total_cost_usd,
                   COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
                   COALESCE(AVG(ttft_ms), 0) as avg_ttft_ms,
                   COALESCE(SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) * 1.0
                       / NULLIF(COUNT(*), 0), 0) as error_rate
            FROM request_logs
        """
        params: list = []
        if since:
            query += " WHERE created_at >= ?"
            params.append(since)

        async with self._db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return {
                "total_requests": row[0],
                "total_prompt_tokens": row[1],
                "total_completion_tokens": row[2],
                "total_tokens": row[3],
                "total_cost_usd": round(row[4], 6),
                "avg_latency_ms": round(row[5], 1),
                "avg_ttft_ms": round(row[6], 1),
                "error_rate": round(row[7], 4),
                "since": since,
            }

    async def get_model_stats(self, since: str | None = None, provider: str | None = None) -> dict:
        """Per-model stats grouped by model name."""
        if not self._db:
            return {"models": [], "since": since}
        conditions = []
        params: list = []
        if since:
            conditions.append("created_at >= ?")
            params.append(since)
        if provider:
            conditions.append("provider = ?")
            params.append(provider)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""
            SELECT model, provider,
                   COUNT(*) as request_count,
                   COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                   COALESCE(SUM(total_tokens), 0) as total_tokens,
                   COALESCE(SUM(cost_usd), 0.0) as cost_usd,
                   COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
                   COALESCE(AVG(ttft_ms), 0) as avg_ttft_ms
            FROM request_logs{where}
            GROUP BY model, provider
            ORDER BY request_count DESC
        """
        models = []
        async with self._db.execute(query, params) as cursor:
            async for row in cursor:
                models.append({
                    "model": row[0],
                    "provider": row[1],
                    "request_count": row[2],
                    "prompt_tokens": row[3],
                    "completion_tokens": row[4],
                    "total_tokens": row[5],
                    "cost_usd": round(row[6], 6),
                    "avg_latency_ms": round(row[7], 1),
                    "avg_ttft_ms": round(row[8], 1),
                })
        return {"models": models, "since": since}

    async def get_recent(self, limit: int = 50, offset: int = 0, since: str | None = None) -> dict:
        """Paginated list of recent requests."""
        if not self._db:
            return {"requests": [], "total": 0, "limit": limit, "offset": offset}
        conditions = []
        params: list = []
        if since:
            conditions.append("created_at >= ?")
            params.append(since)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # Count total
        count_query = f"SELECT COUNT(*) FROM request_logs{where}"
        async with self._db.execute(count_query, params) as cursor:
            total = (await cursor.fetchone())[0]

        # Fetch page
        query = f"""
            SELECT id, provider, model, prompt_tokens, completion_tokens,
                   total_tokens, latency_ms, ttft_ms, cost_usd, status,
                   error_message, created_at
            FROM request_logs{where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        requests = []
        async with self._db.execute(query, params + [limit, offset]) as cursor:
            async for row in cursor:
                requests.append({
                    "id": row[0],
                    "provider": row[1],
                    "model": row[2],
                    "prompt_tokens": row[3],
                    "completion_tokens": row[4],
                    "total_tokens": row[5],
                    "latency_ms": row[6],
                    "ttft_ms": row[7],
                    "cost_usd": round(row[8], 6),
                    "status": row[9],
                    "error_message": row[10],
                    "created_at": row[11],
                })
        return {"requests": requests, "total": total, "limit": limit, "offset": offset}

    async def get_credits_summary(self) -> dict:
        """Rolling 5h/7d zai-coding credit totals (estimates; spec §2.4)."""
        now = datetime.now(timezone.utc)
        since_7d = (now - timedelta(days=7)).isoformat()
        since_5h = (now - timedelta(hours=5)).isoformat()
        async with self._db.execute(
            """SELECT model, credits_used, created_at FROM request_logs
               WHERE provider = 'zai-coding' AND created_at >= ?""",
            (since_7d,),
        ) as cursor:
            rows = await cursor.fetchall()

        credits_5h = 0.0
        credits_7d = 0.0
        by_model: dict[str, dict] = {}
        off_peak = 0
        for model, credits_used, created_at in rows:
            credits_7d += credits_used
            if created_at >= since_5h:
                credits_5h += credits_used
            entry = by_model.setdefault(model, {"credits_used": 0.0, "requests": 0})
            entry["credits_used"] += credits_used
            entry["requests"] += 1
            if not is_peak(datetime.fromisoformat(created_at)):
                off_peak += 1

        return {
            "credits_5h": round(credits_5h, 4),
            "credits_7d": round(credits_7d, 4),
            "by_model": by_model,
            "off_peak_share": (off_peak / len(rows)) if rows else None,
        }
