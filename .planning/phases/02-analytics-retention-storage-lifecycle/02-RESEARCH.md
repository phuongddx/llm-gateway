# Phase 2: Analytics Retention & Storage Lifecycle - Research

**Researched:** 2026-09-08
**Domain:** SQLite/aiosqlite retention purge lifecycle — TTL config knob, batched DELETE on ISO-UTC string index, `auto_vacuum=INCREMENTAL` + `incremental_vacuum` space reclamation, deadline-scheduled purge riding the existing `AnalyticsWriter` loop, deterministic pytest-asyncio testing
**Confidence:** HIGH (all mechanics verified empirically against this repo's own venv — Python 3.14.7, SQLite 3.53.4, aiosqlite 0.22.1, pydantic-settings 2.13.1, pytest 9.0.3 / pytest-asyncio 1.3.0 — plus cross-check against sqlite.org pragma docs; two doc-vs-build discrepancies found and resolved by probe)

## Summary

Phase 2 adds a TTL retention policy to `request_logs` on top of the Phase 1 write path, and every mechanism it needs is already structurally present: the purge predicate is sargable via the existing index (`CREATE INDEX IF NOT EXISTS idx_logs_created_at ON request_logs(created_at)` — [VERIFIED: analytics/db.py:30]); the scheduling host is the existing `AnalyticsWriter` background task ([VERIFIED: analytics/writer.py:54-62]); the config pattern (`analytics_queue_size: int = 1000` + `model_validator`) transfers one-for-one to `analytics_retention_days` ([VERIFIED: config.py:31,53-61]); and `AnalyticsDB.log_request` already accepts an injected `created_at` (`record.get("created_at", datetime.now(timezone.utc).isoformat())` — [VERIFIED: analytics/db.py:97]), so boundary tests seed old rows through the real write path with no monkeypatching. One new env knob, one new `AnalyticsDB.purge_expired()` method, one writer-loop change, pragma additions in `initialize()`, and doc updates carry the whole phase. **No new packages** (REQ-NFR-02 honored).

Five probe-backed findings drive the plan's shape. **First**, `DELETE ... WHERE ... LIMIT` does not exist on this build (`ENABLE_UPDATE_DELETE_LIMIT` absent from `PRAGMA compile_options`; `near "LIMIT": syntax error` — [VERIFIED: runtime probe]); the batched delete must be `DELETE FROM request_logs WHERE rowid IN (SELECT rowid FROM request_logs WHERE created_at < ? LIMIT ?)`, which `EXPLAIN QUERY PLAN` shows as a COVERING INDEX scan on `idx_logs_created_at` feeding an `INTEGER PRIMARY KEY (rowid=?)` delete, with exact per-batch `cursor.rowcount` — 100,000 rows deleted in 1000-row batches in **0.18s** [VERIFIED: runtime probe]. **Second**, `PRAGMA auto_vacuum=INCREMENTAL` set before schema creation works on fresh DBs (reported `2`), but on an existing populated DB it is **silently rejected** (reported value stays `0`, no error) and `PRAGMA incremental_vacuum` no-ops until a one-time plain `VACUUM` rebuilds the file [VERIFIED: runtime probe; CITED: sqlite.org/pragma.html#pragma_auto_vacuum] — exactly matching the locked "docs note, not code" migration. The actual `data/analytics.db` is such a legacy DB (auto_vacuum=0) [VERIFIED: runtime probe on a copy]. **Third** — the phase's biggest trap — on SQLite 3.53.4 **each `PRAGMA incremental_vacuum` call (bare or with N) removes exactly ONE page**, contradicting the current sqlite.org text ("N omitted → entire freelist cleared"); the working recipe is a bounded loop-until-stable (re-read `freelist_count`, stop at 0 or no-decrease), which cleared 4,400 free pages (100k-row DB) in 4,500 calls / 0.15s [VERIFIED: runtime probe, raw sqlite3 + aiosqlite, WAL + rollback, front-free + tail-free layouts]. The no-decrease guard is mandatory: on an auto_vacuum=0 DB the pragma silently no-ops and an unguarded loop spins (observed 200k calls / 25s) [VERIFIED: runtime probe]. **Fourth**, WAL concurrent reads are fully preserved during the whole purge (412 concurrent `COUNT(*)` reads across a 20k-row batched purge, zero failures) and `wait_for(queue.get(), timeout)` deadline wakeups lose zero items on Python 3.14 (stress: 3,000 items, ~1,850 real timeouts, 0 lost with and without a `get_nowait()` salvage) [VERIFIED: runtime probe]. **Fifth**, a full writer-tick prototype (startup purge as the consumer task's first action + 50 ms interval ticks + 30 concurrently enqueued records) ran end-to-end: 0 expired rows left, 30/30 fresh records persisted, freelist cleared [VERIFIED: runtime probe].

**Primary recommendation:** Add `analytics_retention_days: int = 90` (+`ANALYTICS_RETENTION_DAYS` docs, `>= 0` validator, `0`=off) to `Settings`; set `PRAGMA auto_vacuum=INCREMENTAL` in `AnalyticsDB.initialize()` **before** `executescript(_SCHEMA)`; add `AnalyticsDB.purge_expired(retention_days, batch=1000) -> int` (cutoff = `(datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()`, strict `<`, `rowid IN (SELECT rowid ... LIMIT ?)` batches with per-batch commit, then the guarded `incremental_vacuum` loop + `wal_checkpoint(PASSIVE)`); run the startup purge as the **first action of the writer task** and every 6 h (module-constant default `purge_interval_s=21600.0`, constructor-injectable for tests) via a deadline-based `wait_for(queue.get(), timeout=remaining)` wakeup in `_run()`, draining pending queue records between DELETE batches.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Retention Policy**
- Env knob `ANALYTICS_RETENTION_DAYS` (int, default 90; `0` = keep-forever opt-out), documented in `.env.example` + README env table
- Policy applies to existing databases with no manual SQL

**Purge Mechanism**
- Purge runs once at startup (after DB init, before/alongside writer start) and then every 6 hours inside the existing AnalyticsWriter background loop — no new scheduler dependency
- `DELETE FROM request_logs WHERE created_at < cutoff`, batched (≈1000 rows per commit) to keep WAL checkpoints short; never blocks response streaming (fire-and-forget preserved); WAL concurrent reads keep working during purge

**Space Reclamation**
- `PRAGMA auto_vacuum=INCREMENTAL` set at DB creation; `PRAGMA incremental_vacuum` after each purge pass
- Existing databases: documented one-time migration (plain `VACUUM` to rebuild with auto_vacuum) — a docs note, not code
- Docs: README env table + AGENTS.md analytics section updated

**Verification**
- Tests: purge correctness incl. boundary rows (exactly-old-enough purged, newest retained), periodic scheduling (6h tick), endpoints (`/v1/analytics/{summary,models,requests,credits}`) serve retained data correctly post-purge, streaming not blocked during purge
- Deterministic: injected clock/short intervals, no sleeps on real 6h cadence

### Claude's Discretion
None — all areas resolved.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ANLT-01 | Operator can bound `request_logs` growth via a `.env` retention setting (TTL in days) with a documented default, applied to existing databases without manual SQL | `Settings` field + validator mechanics verified on installed pydantic-settings 2.13.1 (default 90 accepted, `0` accepted, negative rejected naming the env var, `ANALYTICS_RETENTION_DAYS` env mapping works) [VERIFIED: runtime probe R4a]; pattern is byte-for-byte the existing `analytics_queue_size` validator [VERIFIED: config.py:53-61]. "Applies to existing DBs": the DELETE predicate works on any DB the current schema creates — no schema change needed; verified against a copy of the real `data/analytics.db` (23 rows, all >90d old) [VERIFIED: runtime probe R3g]. |
| ANLT-02 | Rows older than the TTL are purged automatically (startup + periodic); `/v1/analytics/{summary,models,requests,credits}` serve retained data correctly; purging never blocks or delays response streaming (fire-and-forget preserved, WAL intact); on-disk growth is bounded and purged space is reclaimable | Batched `rowid IN (subquery LIMIT ?)` delete verified (rowcount exact, covering-index plan, 100k rows/0.18s) [VERIFIED: probes P3/R4b]; writer-loop startup-purge + interval-tick prototype verified end-to-end (0 expired left, 30/30 concurrent enqueues persisted) [VERIFIED: probe R3d]; WAL readers unaffected during full batched purge [VERIFIED: probe P5]; `wait_for(queue.get(), timeout)` wakeup lossless on Python 3.14 [VERIFIED: probe R3e]; space reclaim via guarded `incremental_vacuum` loop verified (freelist 4395→0, 4454→54 pages) [VERIFIED: probe R5]; endpoint correctness post-purge testable through existing `client` fixture (`ASGITransport` never runs lifespan — injection pattern established) [VERIFIED: tests/conftest.py:36-47]. |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Retention TTL config (ANLT-01) | Application process (pydantic `Settings`) | — | Single-`.env` contract [VERIFIED: config.py:33-37]; validator must fail at import time like `RATE_LIMIT`/`ANALYTICS_QUEUE_SIZE` |
| Purge execution (ANLT-02) | Storage tier (`AnalyticsDB.purge_expired`) | Application process (writer task owns scheduling) | DELETE/pragma work is a DB concern; *when* it runs is the writer loop's concern — same split as `log_request` |
| Purge scheduling (startup + 6h tick) | Application process (`AnalyticsWriter._run`) | — | Locked decision: rides the existing background loop, no new scheduler; single aiosqlite connection serializes purge with writes by construction |
| Space reclamation | Storage tier (pragmas in `initialize` + after purge) | — | `auto_vacuum` is a database-header property set at creation; `incremental_vacuum` is a storage operation |
| Streaming non-blocking guarantee | Application process (queue producers) | — | Producers only `put_nowait` [VERIFIED: analytics/writer.py:48]; purge running inside the consumer task cannot block producers — drop-newest still bounds memory |
| Docs (env table, migration note) | Repository docs (README, .env.example, AGENTS.md) | — | Locked decision: one-time VACUUM migration is a docs note, not code |

## Standard Stack

**No new packages.** This phase adds zero runtime or test dependencies (REQ-NFR-02).

### Core (existing, verified installed in `.venv`)

| Library | Version (installed) | Purpose | Why Standard |
|---------|--------------------|---------|--------------|
| sqlite3 (stdlib) | runtime 3.53.4 | DELETE batches, `auto_vacuum`/`incremental_vacuum`/`wal_checkpoint` pragmas, `EXPLAIN QUERY PLAN` | Already the storage engine [VERIFIED: analytics/db.py:7]; behavior probed on this exact build |
| aiosqlite | 0.22.1 | async wrapper for the above on the existing single connection | Already used [VERIFIED: analytics/db.py:43]; cursor semantics (`rowcount`, `fetchall`) verified |
| pydantic-settings | 2.13.1 | `analytics_retention_days: int = 90` + `model_validator` (`>= 0`, `0`=off) | Established pattern [VERIFIED: config.py:53-61 — `_validate_analytics_queue_size`]; validator output format verified |
| asyncio (stdlib) | Python 3.14.7 | `wait_for(queue.get(), timeout=...)` deadline wakeups, `TimeoutError`, `get_nowait` salvage | Losslessness on this interpreter verified [VERIFIED: probe R3e] |
| pytest / pytest-asyncio | 9.0.3 / 1.3.0 | deterministic purge/scheduling/endpoint tests | `asyncio_mode = auto` [VERIFIED: pytest.ini]; `@pytest.mark.asyncio` kept per AGENTS.md |
| httpx | 0.28.1 | endpoint-post-purge tests via existing `client` fixture | [VERIFIED: tests/conftest.py:36-47] |

### Supporting
None required.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Deadline `wait_for(queue.get())` tick in `_run()` | Separate purge task alongside the consumer | REJECTED: two tasks share one serial aiosqlite connection — interleaved transactions; the deadline wakeup is lossless (verified) and keeps one task |
| Startup purge inside `lifespan` (inline `await`) | First action of writer task | Inline is also viable (0.18s/100k rows measured) but blocks the `<3s` startup budget on big backlogs and needs a second call site; writer-task-first-action keeps lifespan thin and serializes with queued writes — either satisfies the lock ("before/alongside writer start") |
| `auto_vacuum=FULL` (auto-truncate every commit) | `INCREMENTAL` + post-purge vacuum | REJECTED: locked decision specifies INCREMENTAL; FULL would also shrink+regrow the file on every write commit |
| APScheduler / cron lib for the 6h tick | Writer-loop deadline wakeup | REJECTED: locked decision ("no new scheduler dependency"); NFR-02 |
| `time.sleep`-based scheduling tests | Short injected interval + bounded awaits | REJECTED: Phase 1 locked recipe — Event gates + async sleeps, never real-cadence waits |

**Installation:** none.

## Package Legitimacy Audit

This phase installs **no** external packages.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none) | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

## Architecture Patterns

### System Architecture Diagram

```
                     STARTUP (lifespan — unchanged order, +retention wiring)
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Settings() (import-time): + analytics_retention_days validated (>=0)    │
  │ lifespan: mkdir parent -> db.initialize()                               │
  │   initialize(): PRAGMA auto_vacuum=INCREMENTAL  <- BEFORE schema (P1)   │
  │                 PRAGMA journal_mode=WAL; executescript(_SCHEMA)         │
  │                 (legacy DB: auto_vacuum pragma silently no-ops -> docs) │
  │   write_probe(); writer = AnalyticsWriter(db, queue_size,               │
  │                       retention_days=settings.analytics_retention_days) │
  │   writer.start() ──> [writer task:                                      │
  │       STARTUP PURGE (first action, before first queue.get):             │
  │         retention==0? -> skip                                           │
  │         cutoff = (now(UTC) - retention_days).isoformat()                │
  │         loop: DELETE ... rowid IN (SELECT rowid ... created_at<cutoff   │
  │                 LIMIT 1000); COMMIT per batch; drain queue between      │
  │                 batches; stop when rowcount < batch                     │
  │         loop: PRAGMA incremental_vacuum; stop at freelist 0/no-decrease │
  │         PRAGMA wal_checkpoint(PASSIVE)                                  │
  │       next_purge = now + 6h                                             │
  │       loop: wait_for(queue.get(), timeout=next_purge-now)               │
  │             TimeoutError -> get_nowait() salvage                        │
  │             record -> log_request -> task_done                          │
  │             now >= next_purge? -> PURGE (same as above)                 │
  │                        next_purge = now + 6h]                           │
  └─────────────────────────────────────────────────────────────────────────┘
                       REQUEST PATH (UNCHANGED by this phase)
  client ──> _tracked_stream ──> tokens SSE; finally: writer.enqueue(record)
                                        └─ put_nowait (never blocked by purge:
                                           producers don't await the consumer)

                       PURGE-TIME CONCURRENCY (verified, probe P5)
  writer conn:  [DELETE batch 1] COMMIT [batch 2] COMMIT ... [vacuum loop]
  reader conn:  COUNT(*) x412 during purge ── all succeed (WAL snapshots)
  WAL: grows during purge (auto-checkpoint 1000 pages) -> PASSIVE ckpt after

                       SHUTDOWN (unchanged)
  writer.stop() drains queue, cancels task (mid-purge cancel safe: batch-
  atomic; worst case one batch rolls back at close, next startup resumes)
  -> db.close()
```

### Recommended Project Structure

```
analytics/
├── db.py        # initialize(): + PRAGMA auto_vacuum=INCREMENTAL (pre-schema)
│                # + purge_expired(retention_days, batch=1000) -> int
└── writer.py    # _run(): startup purge + deadline-scheduled 6h tick;
                 #   ctor: + retention_days, purge_interval_s=21600.0
config.py        # + analytics_retention_days: int = 90 (+ >=0 validator)
main.py          # lifespan: pass settings.analytics_retention_days to writer
tests/
├── conftest.py                # analytics_writer fixture: interval/retention passthrough
└── test_analytics_retention.py # NEW — purge, boundary, scheduling, reclaim, burst
README.md / .env.example / AGENTS.md  # env knob + one-time VACUUM migration note
```

### Pattern 1: `AnalyticsDB.purge_expired` — cutoff + batched rowid-delete + guarded vacuum loop

**What:** One method owning the entire retention pass: compute cutoff, batched DELETE with per-batch COMMIT, guarded `incremental_vacuum` loop, passive checkpoint. Returns rows deleted (for logging + test asserts).
**When to use:** exactly this phase (locked decision).
**Why the `rowid IN` form:** `DELETE ... LIMIT` is a syntax error on this build [VERIFIED: probe P3a]; `id` is `TEXT PRIMARY KEY` (not the rowid alias), so selecting `rowid` keeps the subquery a COVERING INDEX scan on `idx_logs_created_at` [VERIFIED: probe P3c EXPLAIN QUERY PLAN: `SEARCH request_logs USING COVERING INDEX idx_logs_created_at (created_at<?)` feeding `SEARCH request_logs USING INTEGER PRIMARY KEY (rowid=?)`].

```python
# analytics/db.py — every mechanic executed in probes P3/P5/R4b/R5 this session
from datetime import datetime, timedelta, timezone

_PURGE_BATCH = 1000  # ≈1000 rows per commit (locked) — keeps WAL checkpoints short

async def purge_expired(self, retention_days: int, batch: int = _PURGE_BATCH) -> int:
    """Delete request_logs rows older than retention_days; reclaim space.

    Strict predicate: a row exactly AT the cutoff is RETAINED. Bounded
    incremental_vacuum loop (each call moves exactly one page on SQLite
    3.53; the no-decrease guard also covers legacy auto_vacuum=0 DBs
    where the pragma silently no-ops).
    """
    if not self._db or retention_days <= 0:  # 0 = keep-forever opt-out
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    deleted = 0
    while True:
        cur = await self._db.execute(
            "DELETE FROM request_logs WHERE rowid IN "
            "(SELECT rowid FROM request_logs WHERE created_at < ? LIMIT ?)",
            (cutoff, batch),
        )
        deleted += cur.rowcount
        await self._db.commit()  # per-batch: short WAL checkpoints (locked)
        if cur.rowcount < batch:
            break
    # Guarded reclamation: exactly ONE page per call on SQLite 3.53.4
    # [VERIFIED: probes R2/R3a/R5] — loop until freelist is 0 or stalls.
    async with self._db.execute("PRAGMA freelist_count") as c:
        last_free = (await c.fetchone())[0]
    for _ in range(last_free * 2 + 16):  # hard bound: freelist size + slack
        await self._db.execute("PRAGMA incremental_vacuum")
        async with self._db.execute("PRAGMA freelist_count") as c:
            free = (await c.fetchone())[0]
        if free == 0 or free >= last_free:  # done, or legacy DB no-op
            break
        last_free = free
    await self._db.execute("PRAGMA wal_checkpoint(PASSIVE)")  # non-blocking; busy=0 verified
    if deleted:
        logger.info("Analytics retention purge: %d rows older than %dd removed", deleted, retention_days)
    return deleted
```

Probe results for this exact shape [VERIFIED: probes P3, P5, R4b, R5]: 3,500-row DB with 3,200 expired → 4 batches, 3,200 deleted, 300 remaining, `rowcount` exact per batch; 100,000 expired rows → 0.18s; vacuum loop 4,400 free pages → 0 in 4,500 calls / 0.15s; 412 concurrent WAL reads during the whole purge, zero failures.

**`initialize()` change (order matters):**

```python
# analytics/db.py initialize() — auto_vacuum MUST precede any CREATE TABLE
self._db = await aiosqlite.connect(self.db_path)
await self._db.execute("PRAGMA auto_vacuum=INCREMENTAL")  # NEW — before schema
await self._db.execute("PRAGMA journal_mode=WAL")
await self._db.executescript(_SCHEMA)
```

Set-before-schema on a fresh DB → `PRAGMA auto_vacuum` reports `2` [VERIFIED: probe P1]. On the existing populated DB the same line is silently a no-op (reported stays `0`, no error) — harmless, and the documented one-time `VACUUM` note is the sanctioned fix (locked: docs, not code) [VERIFIED: probe P1; CITED: sqlite.org/pragma.html#pragma_auto_vacuum — "Auto-vacuuming must be turned on before any tables are created"].

### Pattern 2: Deadline-scheduled purge tick inside the writer loop

**What:** The consumer's blocking `await self._queue.get()` becomes `await asyncio.wait_for(self._queue.get(), timeout=remaining_to_next_purge)`; timeout → purge; deadline recomputed after each purge (no drift).
**When to use:** riding an existing queue-consumer task with a periodic side job.
**Verified safety:** Python 3.14 `asyncio.Queue.get` is cancellation-safe — a raced item stays queued; stress with 3,000 items and ~1,850 genuine timeouts lost **0** items with and without the salvage [VERIFIED: probe R3e]. The `get_nowait()` salvage only reduces pickup latency (407 items picked up immediately).

```python
# analytics/writer.py _run() — prototype ran end-to-end in probe R3d
_PURGE_INTERVAL_S = 6 * 3600.0  # locked: 6h; constant, NOT env (no config-surface growth)

def __init__(self, db, queue_size: int = 1000,
             retention_days: int = 90, purge_interval_s: float = _PURGE_INTERVAL_S):
    ...
    self._retention_days = retention_days
    self._purge_interval_s = purge_interval_s  # tests inject 0.05
    self.purges_run = 0     # observable scheduling proof (tests assert on it)
    self.last_purged = None

async def _run(self) -> None:
    await self._purge()  # STARTUP purge: first action of the consumer task —
                         # keeps lifespan startup instant (NFR-04) and serializes
                         # with queued writes on the single connection
    loop = asyncio.get_running_loop()
    next_purge = loop.time() + self._purge_interval_s
    while True:
        timeout = max(0.0, next_purge - loop.time())
        try:
            record = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            record = None
            try:
                record = self._queue.get_nowait()  # salvage raced item (optional)
            except asyncio.QueueEmpty:
                pass
        if record is not None:
            try:
                await self._db.log_request(record)
            except Exception:
                logger.exception("Analytics write failed")
            finally:
                self._queue.task_done()
        if loop.time() >= next_purge:
            await self._purge()
            next_purge = loop.time() + self._purge_interval_s  # no drift

async def _purge(self) -> None:
    self.purges_run += 1
    self.last_purged = await self._db.purge_expired(self._retention_days)
```

**Inter-batch queue drain (recommended addition inside `purge_expired`'s batch loop, or between batches in `_purge`):** between DELETE batches, drain any records that queued during the pass (`while True: try: rec = queue.get_nowait() ... except QueueEmpty: break` → `log_request` + `task_done`). Rationale: during a huge startup purge the queue still accepts (producers `put_nowait`), but a sustained burst could fill the 1000-cap and drop records — draining between batches keeps the fire-and-forget path lossless even mid-purge. Mechanics (`get_nowait` drain + `log_request`) are the writer's own verified primitives.

**Mid-shutdown cancel safety:** `stop()` cancels the task possibly mid-purge; each DELETE batch is atomic (committed per batch), so the worst case is one uncommitted batch rolled back by `db.close()` — consistent state, next startup purge resumes. No code needed; document in a comment.

### Pattern 3: Settings knob — mirror `analytics_queue_size` exactly

```python
# config.py — validator output verified on installed pydantic-settings 2.13.1
analytics_retention_days: int = 90  # 0 = keep forever (opt-out)

@model_validator(mode="after")
def _validate_analytics_retention_days(self) -> "Settings":
    """Fail fast on negative retention — a typo must not purge fresh rows."""
    if self.analytics_retention_days < 0:
        raise ValueError(
            f"ANALYTICS_RETENTION_DAYS must be >= 0 (got {self.analytics_retention_days}); "
            "0 disables retention (keep forever)"
        )
    return self
```

Verified: default 90; `0` accepted; `ANALYTICS_RETENTION_DAYS=30` env maps; `-5` → `Value error, ANALYTICS_RETENTION_DAYS must be >= 0 (got -5); 0 disables retention (keep forever)`; `"ninety"` → not_integer [VERIFIED: probe R4a]. `extra="ignore"` [VERIFIED: config.py:35] means existing `.env` files without the var keep working. **Why validate in Settings, not lifespan:** a negative TTL would otherwise silently mean "purge everything newer than N days in the future" at runtime — an import-time abort naming the variable matches the RELI-01 convention.

### Pattern 4: Test determinism — inject interval, inject timestamps, assert on counters

- **Scheduling:** construct `AnalyticsWriter(db, retention_days=90, purge_interval_s=0.05)`; seed an expired row; `await asyncio.sleep(0.25)`; assert `writer.purges_run >= 2` and row gone. Bounded sub-second awaits only — never the real 6h cadence (locked).
- **Boundary rows without monkeypatching:** `log_request` honors an injected timestamp — `record.get("created_at", datetime.now(timezone.utc).isoformat())` [VERIFIED: analytics/db.py:97]. Seed `now - timedelta(days=90, microseconds=1)` (purged), `cutoff-string` exactly (retained under strict `<`), and fresh (retained).
- **Space reclaim asserts:** use a `tmp_path` **file** DB (not `:memory:`) and assert `PRAGMA page_count`/`freelist_count` transitions — **not** `os.path.getsize`: in WAL mode the physical shrink lags until checkpoint/close [VERIFIED: probe R5 — page_count 47 while file still 16.6MB until checkpoint; P5 — `wal_checkpoint(PASSIVE)` busy=0]. `:memory:` DBs also accept all pragmas cleanly (auto_vacuum=2; `journal_mode` returns `'memory'` — WAL silently inapplicable, existing behavior) [VERIFIED: probe R3c], so endpoint/boundary tests can keep the shared in-memory fixture.

### Anti-Patterns to Avoid

- **`DELETE ... LIMIT n`:** syntax error on this build (no `ENABLE_UPDATE_DELETE_LIMIT`) [VERIFIED: probe P3a]. Use the `rowid IN (SELECT ... LIMIT ?)` form.
- **One bare `PRAGMA incremental_vacuum` and moving on:** reclaims exactly **one** page on SQLite 3.53.4 — the freelist stays and the file never shrinks [VERIFIED: probes R2/R3a]. Loop with the no-decrease guard.
- **Unguarded vacuum loop (`while freelist > 0`):** spins forever on legacy `auto_vacuum=0` DBs where the pragma is a silent no-op — observed 200k calls / 25s [VERIFIED: probe R4b]. Always break when `freelist` stops decreasing.
- **Setting `auto_vacuum` after `executescript(_SCHEMA)`:** silently no-ops on fresh DBs too — the header flag must be set before the first table is created [CITED: sqlite.org/pragma.html#pragma_auto_vacuum; VERIFIED: probe P1 ordering].
- **Local-time or naive cutoffs:** cutoff must be `datetime.now(timezone.utc)` — every stored `created_at` is `datetime.now(timezone.utc).isoformat()` (`...+00:00` suffix) [VERIFIED: analytics/db.py:97; analytics/db.py:229-231 `get_credits_summary` same convention]. A naive-local cutoff string breaks lexicographic ordering.
- **Asserting file size shrinks immediately in WAL mode:** the truncation materializes at checkpoint/close; assert `page_count`/`freelist_count` instead [VERIFIED: probe R5].
- **Running `VACUUM` programmatically through aiosqlite with fetchone-style pragma reads:** unfinalized cursors → `sqlite3.OperationalError: cannot VACUUM - SQL statements in progress` [VERIFIED: probe R5]. The migration is docs-only (CLI `sqlite3 data/analytics.db "VACUUM;"`), so this is informational — but any test attempting programmatic VACUUM must use `fetchall()` cursor hygiene.
- **A second Settings instance to read the knob:** single `settings` singleton only [VERIFIED: PROJECT.md Constraints — "never construct a second one"]; tests use `Settings(_env_file=None, **kw)` per existing `test_config.py` convention.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Periodic 6h scheduling | Cron string parser, scheduler lib, `asyncio.Task` per tick | Deadline `wait_for` inside the existing `_run()` loop | Locked decision (no new scheduler); losslessness verified on this Python; one task = one serial connection |
| Batched deletes | Chunked `SELECT` + individual DELETEs, or `DELETE ... LIMIT` | `rowid IN (SELECT rowid ... LIMIT ?)` single statement | Atomic per batch, exact `rowcount`, covering-index plan; DELETE-LIMIT doesn't exist on this build |
| Space reclamation | Custom page accounting, periodic full `VACUUM` in-process | `auto_vacuum=INCREMENTAL` + guarded `incremental_vacuum` loop + passive checkpoint | Verified recipe; in-process VACUUM blocks and needs cursor hygiene; docs-sanctioned one-time CLI VACUUM for legacy DBs |
| TTL clock | Custom epoch math, per-row Python filtering | Cutoff string + indexed SQL predicate | Sargable (covering index verified), one comparison per row in C, not Python |

**Key insight:** everything hard here is already inside SQLite; the phase's real work is wiring (config → writer loop → purge method → docs) plus knowing the three build-specific quirks (no DELETE-LIMIT, 1-page-per-vacuum-call, silent auto_vacuum rejection on legacy files) — all three verified, all three handled by the patterns above.

## Runtime State Inventory

> Included because this phase's policy applies to existing runtime data, not just new DBs.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Real `data/analytics.db`: 24,576 B, WAL journal, **auto_vacuum=0**, `request_logs` 23 rows, `created_at` span `2026-04-17T05:18:21.234044+00:00` … `2026-04-20T05:43:07.857934+00:00` — **all 23 rows are >90 days old today** [VERIFIED: probe R3g on a byte copy of the live files] | Code edit only (purge applies automatically on first startup); **operator-visible consequence**: with the documented default 90, the first startup purge empties the current table. Not a data migration. If the operator wants those rows kept, they set `ANALYTICS_RETENTION_DAYS=0` or a larger TTL first — worth one sentence in the README row |
| Stored data (schema) | `request_logs` schema identical across old/new DBs (phase adds no columns; `credits_used` migration already idempotent) [VERIFIED: analytics/db.py:13-53] | None — policy applies with no manual SQL (ANLT-01) |
| Live service config | None — no external services store gateway config (single `.env`, single process) | — |
| OS-registered state | None — no OS registrations embed analytics state | — |
| Secrets/env vars | New key `ANALYTICS_RETENTION_DAYS` (additive; no renames; `extra="ignore"` keeps old `.env` files valid) | Add to `.env.example` + README table |
| Build artifacts | None — pure-Python repo, no compiled artifacts carrying DB config | — |

**The canonical question — after every file updates, what still has old state?** The DB *file header* (auto_vacuum=0) on existing deployments: unfixable by code (SQLite refuses the flip on populated DBs), hence the locked docs note: `sqlite3 data/analytics.db "VACUUM;"` once (with the gateway stopped) rebuilds it with auto_vacuum enabled. New DBs created after this phase get it automatically at creation.

## Common Pitfalls

### Pitfall 1: Assuming one `incremental_vacuum` call reclaims the freelist
**What goes wrong:** File never shrinks; `page_count` barely moves; ANLT-02 "purged space is reclaimable" silently unmet in spirit.
**Why it happens:** sqlite.org currently documents "N omitted → the entire freelist is cleared", but SQLite 3.53.4 (this venv's build) removes **exactly one page per call** — verified identically through raw `sqlite3` and `aiosqlite`, in WAL and rollback journal modes, with N supplied and omitted [VERIFIED: probes R2/R3a].
**How to avoid:** Bounded loop with the no-decrease guard (Pattern 1). 4,400 pages cleared in 4,500 calls / 0.15s at 100k-row scale — the loop is cheap [VERIFIED: probe R5].
**Warning signs:** a test asserting `freelist_count == 0` after a single vacuum call fails; production file size never drops.

### Pitfall 2: Legacy-DB no-op spin / silent pragma rejection
**What goes wrong:** (a) `PRAGMA auto_vacuum=INCREMENTAL` in `initialize()` appears to run but the existing DB stays `auto_vacuum=0` — no error; (b) an unguarded `while freelist > 0: incremental_vacuum` loop spins forever on such DBs.
**Why it happens:** SQLite refuses the header flip once tables exist; docs: enable "before any tables are created" or via `VACUUM` [CITED: sqlite.org/pragma.html#pragma_auto_vacuum]. Verified: populated DB → reported value stays `0`; 200k no-op calls observed [VERIFIED: probes P1/R4b].
**How to avoid:** Keep the pragma line (fresh DBs need it; legacy DBs no-op harmlessly) + no-decrease guard in the vacuum loop + the docs migration note. Optionally log once when `PRAGMA auto_vacuum` still reports 0 after initialize (informational, points operators at the note).
**Warning signs:** log line "purged N rows" but disk usage flat; CPU burn in the writer task.

### Pitfall 3: Purge-starved queue drops during a huge startup purge
**What goes wrong:** A multi-hundred-K-row backlog purge takes the consumer busy for seconds; a concurrent coding burst fills the 1000-cap queue; drop-newest kicks in — records lost despite "fire-and-forget preserved".
**Why it happens:** Producers never block (correct), but the single consumer is inside `purge_expired` and not draining.
**How to avoid:** Inter-batch queue drain (Pattern 2 addendum). Batches are 0.18s/100k-rows fast, so exposure is small; the drain closes it completely.
**Warning signs:** `writer.dropped > 0` in tests/teardown logs after a burst-during-purge test.

### Pitfall 4: Boundary semantics off by one direction
**What goes wrong:** Test (or impl) treats "exactly old enough" as the row exactly AT the cutoff and expects it purged; strict `<` retains it — assertion fails or, worse, the implementation switches to `<=` and over-purges.
**Why it happens:** Two defensible readings; the locked SQL is `created_at < cutoff`.
**How to avoid:** Encode precisely: seed three rows — `cutoff - 1µs` (purged), the cutoff string itself (retained), `now` (retained) — all through `log_request` with injected `created_at` [VERIFIED: probe P4 SQL kept `['exact', 'just-newer']`; analytics/db.py:97 honors injected timestamps]. "Exactly-old-enough" in CONTEXT.md = the 1µs-older row.
**Warning signs:** flaky boundary test using `datetime.now()` twice (two different 'now's).

### Pitfall 5: WAL growth during purge mistaken for a leak / checkpoint starvation
**What goes wrong:** During a large purge the `-wal` file grows (3.5→4.9MB observed on a 20k purge) even though auto-checkpoint (1000 pages) is on; operators see disk usage climb while purging.
**Why it happens:** Every DELETE batch writes frames; readers holding snapshots can delay checkpoint reset. Post-purge `wal_checkpoint(PASSIVE)` returned `busy=0` and checkpointed everything [VERIFIED: probe P5].
**How to avoid:** PASSIVE checkpoint after each purge pass (Pattern 1). Never TRUNCATE-checkpoint from the hot path (it blocks until it can reset the WAL).
**Warning signs:** `-wal` file growing unbounded across purge cycles.

### Pitfall 6: ISO-format drift breaking lexicographic ordering
**What goes wrong:** A cutoff or seeded row in a different format (`Z` suffix, no offset, space separator) compares wrong as a string.
**Why it happens:** String comparison is only order-correct for a single consistent layout.
**How to avoid:** Both cutoff and all writers use `datetime.now(timezone.utc).isoformat()` → `YYYY-MM-DDTHH:MM:SS.ffffff+00:00`. Verified correct even across the microsecond-omission edge (`'…23+00:00' < '…23.000001+00:00'` — `+` (0x2B) sorts before `.` (0x2E)) [VERIFIED: probe P4]. Tests seed timestamps with the same call.
**Warning signs:** boundary test failing only at whole-second timestamps.

## Code Examples

### Cutoff computation (timezone-aware, format-consistent)
```python
# Verified format: '2026-06-10T06:25:39.193612+00:00' [VERIFIED: probe P4]
from datetime import datetime, timedelta, timezone
cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
```

### Batched delete loop with exact rowcount (probe P3b: 3,200 deleted in 4 batches, 300 retained)
```python
while True:
    cur = await db.execute(
        "DELETE FROM request_logs WHERE rowid IN "
        "(SELECT rowid FROM request_logs WHERE created_at < ? LIMIT 1000)",
        (cutoff,),
    )
    await db.commit()
    if cur.rowcount < 1000:
        break
```

### Sargability proof (probe P3c verbatim EXPLAIN QUERY PLAN output)
```
SEARCH request_logs USING INTEGER PRIMARY KEY (rowid=?)
LIST SUBQUERY 1
SEARCH request_logs USING COVERING INDEX idx_logs_created_at (created_at<?)
```

### Seeding boundary rows through the real write path
```python
# log_request honors an injected created_at [VERIFIED: analytics/db.py:97 —
# `record.get("created_at", datetime.now(timezone.utc).isoformat())`]
await db.log_request({**_record(1), "created_at": (now - timedelta(days=90, microseconds=1)).isoformat()})
await db.log_request({**_record(2), "created_at": cutoff_string})
await db.log_request({**_record(3), "created_at": now.isoformat()})
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Unbounded `request_logs` growth (current repo) | TTL retention + batched purge + incremental reclamation | This phase | Long-running deployments stay disk-bounded |
| Docs' "bare incremental_vacuum clears entire freelist" | SQLite 3.53.4 removes 1 page/call (empirical) | Build-specific, verified 2026-09-08 | Loop-with-guard required; docs text not trustworthy for this build |
| Full `VACUUM` as the only reclamation | `auto_vacuum=INCREMENTAL` + `incremental_vacuum` | SQLite ≥3.1 (long-standing) | Bounded, online reclamation; VACUUM remains the one-time legacy migration |

**Deprecated/outdated:**
- `DELETE ... LIMIT`: never available on CPython-bundled SQLite (requires a non-default compile option) — do not reach for it.
- Counting on `PRAGMA auto_vacuum` flips post-creation: refused by SQLite by design.

## Assumptions Log

> All claims tagged `[ASSUMED]` in this research. Everything else was verified or cited.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Purge interval stays a module constant (`_PURGE_INTERVAL_S = 21600.0`, constructor-injectable), NOT a new env var — the locked env surface adds only `ANALYTICS_RETENTION_DAYS` | Standard Stack / Pattern 2 | Low: if operators end up wanting a purge-frequency knob it's a trivial follow-up; adding un-asked env surface now would violate the single-knob lock |
| A2 | The one-time VACUUM migration note lives in the README env-table row (footnote) + AGENTS.md analytics section; exact wording/placement is planner's latitude within the locked "docs note, not code" | Runtime State Inventory | None functional — placement choice only |
| A3 | `data/analytics.db`'s 23 legacy rows being purged on first startup (all >90d) is acceptable default behavior surfaced in the README row rather than special-cased in code | Runtime State Inventory | Low: if the operator considers those rows precious, a README sentence directs them to set `0`/larger TTL before upgrading; no code impact |

**If this table is empty:** n/a — three low-risk placement/scope recommendations flagged for planner visibility; no technical unknowns remain.

## Open Questions

1. **Purge observability surface** — log line only (`logger.info` per purge with deleted count) vs also exposing `writer.purges_run`/`last_purged` attributes.
   - What we know: tests benefit from the attributes (deterministic scheduling asserts without log parsing); Phase 4 (OBSV-01) will add Prometheus metrics later.
   - What's unclear: whether the user wants any operator-visible surface beyond logs this phase.
   - Recommendation: attributes + info log now (cheap, test-enabling); metrics deferred to Phase 4 per the Phase-1 precedent (drop-counter deferred to OBSV-01).
2. **Post-purge `wal_checkpoint(PASSIVE)` inclusion** — verified non-blocking (busy=0), keeps `-wal` bounded (Pitfall 5).
   - Recommendation: include; strictly additive to the locked "WAL intact" requirement.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv (`.venv`) | everything | ✓ | 3.14.7 | — |
| SQLite (CPython-bundled) | purge, pragmas | ✓ | 3.53.4 runtime | — |
| aiosqlite | async DB layer | ✓ | 0.22.1 | — |
| pydantic-settings | retention knob | ✓ | 2.13.1 | — |
| pytest + pytest-asyncio + httpx | verification | ✓ | 9.0.3 / 1.3.0 / 0.28.1 | — |
| sqlite3 CLI (for the documented one-time VACUUM note) | docs migration note | ✓ (macOS system) | present | Note can also show a Python one-liner | 

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = auto` [VERIFIED: pytest.ini — full contents: `[pytest]` / `asyncio_mode = auto`]) |
| Config file | `pytest.ini` |
| Quick run command | `.venv/bin/python -m pytest tests/test_analytics_retention.py -v` |
| Full suite command | `make test` (= `.venv/bin/python -m pytest tests/ -v`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ANLT-01 | Default 90 / env mapping / `0`=off accepted / negative rejected naming `ANALYTICS_RETENTION_DAYS` | unit | `.venv/bin/python -m pytest tests/test_config.py -v -k retention` | ❌ Wave 0 (extend `tests/test_config.py`) |
| ANLT-02 | Purge deletes strictly-older rows; exact-cutoff + newest retained (boundary trio) | unit (db-level, `:memory:` via shared fixture) | `.venv/bin/python -m pytest tests/test_analytics_retention.py -v -k boundary` | ❌ Wave 0 (new file) |
| ANLT-02 | `retention_days=0` purges nothing (keep-forever opt-out) | unit | `... -k "off or keep_forever"` | ❌ Wave 0 |
| ANLT-02 | Batch loop terminates via rowcount; multi-batch (>1000 expired) deletes all | unit (tmp file DB, 2,500 expired) | `... -k batch` | ❌ Wave 0 |
| ANLT-02 | Startup purge runs (writer first action) without lifespan blocking | unit | `... -k startup` | ❌ Wave 0 |
| ANLT-02 | Periodic tick: `purge_interval_s=0.05` → `purges_run >= 2` in ~0.25s, expired rows purged each pass | unit (short interval, bounded awaits) | `... -k tick` | ❌ Wave 0 |
| ANLT-02 | `/v1/analytics/{summary,models,requests,credits}` serve retained data post-purge (old+new seeded, incl. `zai-coding` rows inside 5h/7d credit windows) | integration (`client` fixture) | `... -k endpoints` | ❌ Wave 0 |
| ANLT-02 | Streaming not blocked during purge + exactly-once rows (Phase-1 burst recipe: ~20 streams, slowed writer/gated DB, tiny purge interval) | integration | `... -k "burst or during_purge"` | ❌ Wave 0 |
| ANLT-02 | Space reclaim: file DB created fresh → expired rows deleted → `freelist_count` reaches 0 and `page_count` drops (assert pragmas, not file size) | unit (tmp_path file DB) | `... -k reclaim` | ❌ Wave 0 |
| ANLT-02 | Queue drained between purge batches — no drops during a purge under enqueue pressure (`writer.dropped == 0`) | unit | `... -k interleave` | ❌ Wave 0 |
| ANLT-01 | Docs: `.env.example` row, README env-table row, AGENTS.md analytics section + VACUUM note present | manual/doc check (no automated doc tests in this repo) | — | — manual-only: doc drift is reviewed at verify-work |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_analytics_retention.py tests/test_config.py -v` (fast targeted set)
- **Per wave merge:** `make test` (full suite — guards the four baseline analytics endpoints + Phase-1 writer guarantees against regression)
- **Phase gate:** full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_analytics_retention.py` — new file: boundary trio, off-switch, batching, startup/tick scheduling, reclaim, endpoints-post-purge, burst-during-purge, inter-batch drain (covers the ANLT-02 rows above)
- [ ] `tests/test_config.py` — extend with retention validator cases (default/env/0/negative/non-int)
- [ ] `tests/conftest.py` — `analytics_writer` fixture currently hardcodes `AnalyticsWriter(analytics_db, queue_size=1000)` [VERIFIED: tests/conftest.py:29]; needs interval/retention passthrough (e.g., factory-style or kwargs) for tick tests — small change, keep the existing default shape for all current callers

*(Framework itself: no gaps — existing infrastructure covers everything; no new plugins needed.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Unchanged (`APP_API_KEY` bearer; retention adds no auth surface) |
| V3 Session Management | no | None |
| V4 Access Control | no | Purge is internal, not endpoint-reachable |
| V5 Input Validation | yes | pydantic `Settings` validator: `analytics_retention_days` must be int `>= 0` (import-time abort naming the env var — mirrors RELI-01 pattern; prevents a typo silently purging fresh rows) |
| V6 Cryptography | no | None |
| V10 Malicious Code | yes (supply chain) | Zero new dependencies (REQ-NFR-02) — nothing to audit |
| V12 Data Protection | indirect | Retention DELETE is the data-minimization control itself; parameterized SQL only (cutoff bound as `?` — verified pattern), no string interpolation into SQL |

### Known Threat Patterns for SQLite/FastAPI stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via cutoff/env values | Tampering | Parameterized `?` binding only (probe pattern); env knob validated as int by pydantic before use |
| Destructive misconfiguration (negative/typo TTL purging live data) | Tampering/Repudiation | Import-time validator + info-log per purge with row count (audit trail) |
| Data loss via purge race on shutdown | Tampering | Per-batch COMMIT atomicity; drained-then-cancelled stop; worst case one batch rolls back consistently |
| Error-detail leakage | Information Disclosure | Purge failures logged server-side via module `logger`; no client-facing surface changes |

## Sources

### Primary (HIGH confidence)
- Runtime probes R1–R5, P1–P6 (this session, repo venv: Python 3.14.7 / SQLite 3.53.4 / aiosqlite 0.22.1 / pydantic-settings 2.13.1) — auto_vacuum fresh-vs-existing, 1-page-per-vacuum-call, DELETE-LIMIT absence, rowid-subquery plan+rowcount, WAL concurrency during purge, wait_for race stress, tick prototype, 100k-row timings, real-DB inspection, pydantic knob, VACUUM cursor hygiene
- sqlite.org/pragma.html — `auto_vacuum` and `incremental_vacuum` sections (fetched this session; two empirical deviations on this build documented above)

### Secondary (MEDIUM confidence)
- sqlite.org file-format freelist documentation referenced by the pragma pages (not separately fetched)

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new deps; every existing component's relevant behavior probed on the exact runtime
- Architecture: HIGH — writer-tick prototype executed end-to-end; all integration points read this session (db.py, writer.py, config.py, main.py, conftest.py, chat.py enqueue, pytest.ini)
- Pitfalls: HIGH — each pitfall reproduced and its mitigation verified empirically

**Research date:** 2026-09-08
**Valid until:** 2026-10-08 (stable domain; re-probe only if the venv's SQLite major/minor changes — the 1-page and no-op findings are build-specific)

## RESEARCH COMPLETE

**Phase:** 2 — Analytics Retention & Storage Lifecycle
**Confidence:** HIGH

**Key findings:**
1. `DELETE ... LIMIT` is unavailable on this build — batched purge must use `DELETE ... WHERE rowid IN (SELECT rowid ... WHERE created_at < ? LIMIT 1000)` (covering-index plan verified; exact `rowcount`; 100k rows in 0.18s).
2. `incremental_vacuum` removes exactly **one page per call** on SQLite 3.53.4 (contradicting current docs) — a bounded loop-with-no-decrease-guard is mandatory; it clears 4,400 free pages in 0.15s at 100k-row scale. Unguarded loops spin forever on legacy `auto_vacuum=0` DBs.
3. `PRAGMA auto_vacuum=INCREMENTAL` must precede schema creation; on existing populated DBs it is **silently rejected** — matching the locked one-time-`VACUUM` docs note. The real `data/analytics.db` is legacy (auto_vacuum=0, 23 rows, all >90d old — first default purge will empty it).
4. WAL concurrent reads are unaffected during the entire batched purge (412 reads, zero failures) and `wait_for(queue.get(), timeout)` deadline ticks lose zero items on Python 3.14 — the locked "ride the writer loop" design is safe; startup purge as the task's first action keeps NFR-04 startup instant.
5. Everything is testable deterministically with the existing fixtures: inject `created_at` through `log_request` (boundary trio), inject `purge_interval_s=0.05` (tick asserts on `purges_run`), assert `page_count`/`freelist_count` (not file size — WAL shrink lags until checkpoint).
