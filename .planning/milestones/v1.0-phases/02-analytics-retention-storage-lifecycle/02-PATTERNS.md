# Phase 2: Analytics Retention & Storage Lifecycle - Pattern Map

**Mapped:** 2026-09-08
**Files analyzed:** 10 (2 new, 8 modified)
**Analogs found:** 10 / 10 (every file has a role-exact, git-tracked analog — most are Phase-1 artifacts)

All analog paths verified git-tracked via `git ls-files` (no gitignored mirrors). Line numbers verified against working tree this session.

> **Placement discrepancy surfaced during mapping (planner must resolve):** CONTEXT/RESEARCH name `tests/test_config.py` for the retention-knob validation tests, but the repo's established home for `Settings` validator tests is **`tests/test_startup_validation.py`** (`test_analytics_queue_size_validator_*` at lines 35-43; `test_config.py` contains only key-resolution tests). Either location works; extending `test_startup_validation.py` matches convention, extending `test_config.py` matches the CONTEXT letter. Both are mapped below.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `analytics/db.py` (modify: `purge_expired` + `initialize` pragmas) | model (storage tier) | CRUD (batched DELETE) + file-I/O (pragmas) | itself — `log_request` (analytics/db.py:77-104) + `initialize` (analytics/db.py:43-57) + `write_probe` (analytics/db.py:59-69) | exact |
| `analytics/writer.py` (modify: startup purge + 6h tick + attrs) | service (background queue consumer) | event-driven (queue) + batch (periodic purge) | itself — `_run` loop (analytics/writer.py:54-62), `__init__` (analytics/writer.py:18-29) | exact |
| `config.py` (modify: `analytics_retention_days` + validator) | config | transform (env → validated typed field) | `analytics_queue_size` field + `_validate_analytics_queue_size` (config.py:31, 53-61) | exact — byte-for-byte transferable |
| `main.py` (modify: pass retention to writer) | composition root (lifespan) | request-response (startup/shutdown) | `writer = AnalyticsWriter(db, queue_size=settings.analytics_queue_size)` (main.py:61) | exact |
| `.env.example` (modify: + knob row) | config docs | n/a | `ANALYTICS_QUEUE_SIZE` block (.env.example:26-27) | exact |
| `tests/test_analytics_retention.py` (NEW) | test (unit + integration) | unit (db/writer) + integration (client) | `tests/test_analytics_writer.py` (scheduling/determinism) + `tests/test_analytics_db.py` (db-level) + `tests/test_analytics_endpoints.py` (post-purge endpoints) | role-match per test class |
| `tests/conftest.py` (modify: writer fixture passthrough) | test fixture | n/a | `analytics_writer` fixture (tests/conftest.py:29-38) | exact |
| `tests/test_config.py` (modify: knob validation — see discrepancy note) | test | n/a | `test_analytics_queue_size_validator_rejects_{zero,negative}` (tests/test_startup_validation.py:35-43) | exact |
| `README.md` (modify: env-table row + migration note) | docs | n/a | Gateway Settings table rows (README.md:188-198) | exact |
| `AGENTS.md` (modify: analytics section) | docs | n/a | `analytics/db.py` + `.env.example` bullets in Important Files (AGENTS.md:185-192) | exact |

## Pattern Assignments

### `analytics/db.py` — `purge_expired()` + `initialize()` pragmas (model, CRUD/file-I/O)

**Analog:** this same file — Phase 1 established every convention the method needs.

**Module header** (analytics/db.py:1-13) — keep imports grouped stdlib → third-party → local, module logger:
```python
"""SQLite-backed analytics storage with async queries."""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import aiosqlite

from analytics.cost import is_peak

logger = logging.getLogger(__name__)
```
`purge_expired` needs `timedelta` (already imported at analytics/db.py:5) — no new imports required.

**Core storage-method pattern** (analytics/db.py:77-104) — parameterized `?`-bound SQL on `self._db`, per-statement `commit`, broad `except Exception` + `logger.exception` (never raise into the fire-and-forget path), guard on `self._db`:
```python
async def log_request(self, record: dict) -> None:
    """Insert a request log record. Fire-and-forget safe."""
    if not self._db:
        return
    try:
        await self._db.execute(
            """INSERT INTO request_logs
               (id, provider, model, ...)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["id"],
                ...
                record.get("created_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
        await self._db.commit()
    except Exception:
        logger.exception("Failed to log request to analytics DB")
```
The cutoff line for `purge_expired` uses the exact same clock/format call visible at analytics/db.py:97 (`datetime.now(timezone.utc).isoformat()` → `YYYY-MM-DDTHH:MM:SS.ffffff+00:00`). NOTE: unlike `log_request`, `purge_expired` should NOT blanket-`except Exception` — it returns `int` (rows deleted) for test asserts; let DB errors propagate to the writer loop's existing `except Exception` (analytics/writer.py:59-60).

**Initialize/pragma pattern** (analytics/db.py:43-57) — the new `PRAGMA auto_vacuum=INCREMENTAL` line slots **before** `executescript(_SCHEMA)` (order locked by RESEARCH P1):
```python
async def initialize(self) -> None:
    """Create tables and enable WAL mode."""
    self._db = await aiosqlite.connect(self.db_path)
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
    logger.info("Analytics DB initialized at %s", self.db_path)
```
The existing idempotent-migration try/except (lines 48-55) is the precedent for code that must be a silent no-op on legacy DBs — same posture as `auto_vacuum` on an existing populated file.

**Pragmas-with-commit pattern** (analytics/db.py:59-69) — `write_probe` is the model for execute→commit sequences outside a transaction:
```python
async def write_probe(self) -> None:
    await self._db.execute("CREATE TABLE IF NOT EXISTS _write_probe(x)")
    await self._db.execute("DROP TABLE _write_probe")
    await self._db.commit()
```

**Schema/index reference** (analytics/db.py:14-40) — `_SCHEMA` already creates the sargable index the purge predicate rides; no schema change this phase:
```sql
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON request_logs(created_at);
```

**Purge SQL shape (RESEARCH-verified, no in-repo precedent for the statement itself):** `DELETE FROM request_logs WHERE rowid IN (SELECT rowid FROM request_logs WHERE created_at < ? LIMIT ?)` with strict `<`, per-batch `commit()`, `cur.rowcount` termination, then the guarded `incremental_vacuum` loop + `wal_checkpoint(PASSIVE)` — full reference implementation in 02-RESEARCH.md Pattern 1.

---

### `analytics/writer.py` — startup purge + deadline tick + observability attrs (service, event-driven + batch)

**Analog:** this same file — the modifications land inside `_run` (analytics/writer.py:54-62) and `__init__` (analytics/writer.py:18-29).

**Constructor pattern** (analytics/writer.py:18-29) — ctor validation raising `ValueError` naming the parameter, then underscore-private state + one public observable counter (`self.dropped` — the precedent for new `purges_run` / `last_purged`):
```python
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
```
New kwargs (`retention_days: int = 90`, `purge_interval_s: float = _PURGE_INTERVAL_S` where `_PURGE_INTERVAL_S = 6 * 3600.0` sits next to `_DRAIN_TIMEOUT_S` at analytics/writer.py:8) follow this exact signature-extension shape: keyword-with-default, appended after existing params so every current caller stays source-compatible.

**The loop being modified** (analytics/writer.py:54-62):
```python
async def _run(self) -> None:
    while True:
        record = await self._queue.get()
        try:
            await self._db.log_request(record)
        except Exception:
            logger.exception("Analytics write failed")
        finally:
            self._queue.task_done()  # in finally so join() never deadlocks
```
Becomes: startup `await self._purge()` as first action → `asyncio.wait_for(self._queue.get(), timeout=remaining_to_next_purge)` with `TimeoutError → get_nowait()` salvage → post-drain purge tick when `loop.time() >= next_purge` (full verified prototype in 02-RESEARCH.md Pattern 2). Keep the `try/except Exception/logger.exception/finally task_done` shape around the record path untouched.

**Non-blocking producer contract** (analytics/writer.py:37-52) — unchanged, but the "streaming never blocked" guarantee rests on it (producers only `put_nowait`):
```python
try:
    self._queue.put_nowait(record)
except asyncio.QueueFull:
    self.dropped += 1  # drop-NEWEST: the incoming record is dropped
    if self.dropped % 50 == 1:
        ...
```

**Shutdown/drain pattern** (analytics/writer.py:67-91) — `stop()` drains via `wait_for(self._queue.join(), timeout)` then cancels; mid-purge cancel is safe because purge batches commit individually (document as a comment, no code change).

---

### `config.py` + `.env.example` — `ANALYTICS_RETENTION_DAYS` (config, transform)

**Analog:** `analytics_queue_size` — Phase 1 added this knob through the identical three surfaces.

**Field declaration** (config.py:29-31):
```python
# Analytics
analytics_db_path: str = "data/analytics.db"
analytics_queue_size: int = 1000  # Bounded analytics write queue (drop-newest when full)
```
→ add `analytics_retention_days: int = 90  # 0 = keep forever (opt-out)` in the same `# Analytics` block.

**Validator pattern** (config.py:53-61) — copy structure verbatim, swap bounds (`< 0` instead of `< 1`) and message:
```python
@model_validator(mode="after")
def _validate_analytics_queue_size(self) -> "Settings":
    """Fail fast on an unbounding queue size — asyncio.Queue treats maxsize<=0 as unbounded."""
    if self.analytics_queue_size < 1:
        raise ValueError(
            f"ANALYTICS_QUEUE_SIZE must be >= 1 (got {self.analytics_queue_size}); "
            "0 or negative would disable the queue bound"
        )
    return self
```
Key properties to preserve: `@model_validator(mode="after")` on `Settings`; message names the **env var** (not the field) because that's what the operator edits; one-line docstring states the failure being prevented. `model_config` (config.py:33-37, `extra="ignore"`) already tolerates old `.env` files lacking the new var — no change needed there. Message text for the new validator is speced in 02-RESEARCH.md Pattern 3.

**.env.example tail block** (.env.example:24-27) — one comment line + one assignment, same voice:
```bash
# Analytics database path
ANALYTICS_DB_PATH=data/analytics.db

# Analytics write queue size (drops newest + logs when full)
ANALYTICS_QUEUE_SIZE=1000
```
→ append `# Analytics log retention in days (0 = keep forever)` + `ANALYTICS_RETENTION_DAYS=90`.

---

### `main.py` — lifespan wiring (composition root)

**Analog:** the existing writer construction (main.py:61-62):
```python
writer = AnalyticsWriter(db, queue_size=settings.analytics_queue_size)
writer.start()
```
→ `AnalyticsWriter(db, queue_size=settings.analytics_queue_size, retention_days=settings.analytics_retention_days)`. One-line change; the startup purge then happens inside `writer.start()`'s task (first action), keeping lifespan thin per RESEARCH's rejected-alternative analysis. No other lifespan edits.

---

### `tests/test_analytics_retention.py` (NEW — test; four analogs by test class)

**Analog A — module scaffold + record factory:** `tests/test_analytics_writer.py:1-29`
```python
"""Unit tests for analytics.writer — queue lifecycle + concurrent burst proof."""

import asyncio
...
import pytest

from analytics.writer import AnalyticsWriter


def _record(i: int) -> dict:
    """Queue payload in the exact 12-key shape routes/chat.py enqueues."""
    return {
        "id": f"00000000-0000-0000-0000-{i:012d}",
        "provider": "manifest",
        ...
        "error_message": None,
    }
```
One-line module docstring naming scope; `_record` payload factory; reuse the shared `analytics_db` fixture (AGENTS.md explicitly prefers it over `test_analytics_db.py`'s local duplicate).

**Analog B — deterministic scheduling (tick/startup tests):** `test_gated_writer_drains_exactly_once_after_release` (tests/test_analytics_writer.py:81-107):
```python
writer = AnalyticsWriter(analytics_db, queue_size=10)
gate = asyncio.Event()
original_log = analytics_db.log_request

async def gated_log(record):
    await gate.wait()
    await original_log(record)

analytics_db.log_request = gated_log
writer.start()
...
await asyncio.sleep(0)  # brief yield: consumer takes one record, blocks at the gate
```
Conventions: construct the writer with explicit small params; control scheduling with Event gates and `asyncio.sleep(0)` yields — never real-cadence waits; assert via `wait_drained(5.0)` then `get_recent`. For the 6h-tick tests, inject `purge_interval_s=0.05` and assert on the new public `writer.purges_run` counter (bounded `await asyncio.sleep(0.25)`), per 02-RESEARCH.md Pattern 4.

**Analog C — burst / not-blocked-during-purge:** `test_concurrent_burst_full_delivery_exactly_once` (tests/test_analytics_writer.py:217-276):
```python
original_log = analytics_db.log_request

async def slowed_log(record):
    await asyncio.sleep(0.005)  # deterministic lag — never a blocking sleep
    await original_log(record)

analytics_db.log_request = slowed_log  # the fixture writer's db — slows its drain
...
with patch("routes.chat.create_provider", side_effect=[_provider_for(i) for i in range(20)]), \
     patch("routes.chat.resolve_provider", return_value=("manifest", "gpt-4o")):
    responses = await asyncio.gather(*[client.post(...) for _ in range(20)])
```
Conventions: monkeypatch **by attribute assignment** on the fixture's db instance (`analytics_db.log_request = ...`) — no `monkeypatch` fixture, no `app.dependency_overrides`; `unittest.mock.patch` only for module-level functions (`routes.chat.create_provider` / `resolve_provider`); a sampler task asserting a queue-depth ceiling; exactly-once asserts via `{row["id"] for row in recent["requests"]}`. The purge-during-burst test replays this with a tiny `purge_interval_s` so purges interleave with streams, asserting `writer.dropped == 0` + full token delivery.

**Analog D — boundary seeding + file-DB tests:** `tests/test_analytics_db.py`
- `test_recent_since_filter` (lines 113-136) — seeds a row with an explicitly injected old `created_at` through `log_request`; this is the boundary-trio mechanism (`log_request` honors injected timestamps, analytics/db.py:97).
- `test_credits_summary_windows` (lines 179-188) — multiple rows at computed offsets (`minutes_ago=60`, `8*60`, `8*24*60`); copy this `timedelta`-offset seeding style for the boundary trio (`now - timedelta(days=90, microseconds=1)` / exact cutoff string / `now`).
- `test_migration_adds_column_to_preexisting_schema` (lines 212-236) — **the tmp_path file-DB pattern** for the space-reclaim test (must be a file, not `:memory:`): `path = str(tmp_path / "old.db")` + raw `sqlite3` seeding; assert on `PRAGMA page_count`/`freelist_count`, never file size (WAL lag — RESEARCH Pitfall/R5).
- `db` fixture (lines 12-18) exists here but **use the shared `analytics_db`** (conftest) for `:memory:` tests per AGENTS.md guidance.

**Analog E — endpoints-post-purge (integration):** `tests/test_analytics_endpoints.py:41-61`:
```python
@pytest.mark.asyncio
async def test_analytics_summary_with_data(client, auth_headers, analytics_db):
    """GET /v1/analytics/summary returns aggregate stats."""
    await analytics_db.log_request({
        "id": "test-001",
        "provider": "openai",
        ...
    })
    response = await client.get("/v1/analytics/summary", headers=auth_headers)
    assert response.status_code == 200
```
Seed directly on `analytics_db`, hit endpoints through `client` + `auth_headers`, assert JSON fields. Post-purge variants: seed old + fresh rows (incl. `zai-coding` rows inside the 5h/7d credit windows — see `test_credits_endpoint_aggregates_rows`, lines 142-157, for the credit-seeding shape with `timedelta` offsets), run `purge_expired`, then assert all four endpoints report only retained data.

Keep `@pytest.mark.asyncio` on every async test despite `asyncio_mode = auto` (pytest.ini) — explicit repo convention (AGENTS.md Testing section).

---

### `tests/conftest.py` — writer fixture passthrough (test fixture)

**Analog:** the fixture being extended (tests/conftest.py:29-38):
```python
@pytest_asyncio.fixture
async def analytics_writer(analytics_db):
    """AnalyticsWriter over the test DB (lifespan never runs under ASGITransport)."""
    from main import app

    writer = AnalyticsWriter(analytics_db, queue_size=1000)
    writer.start()
    app.state.analytics_writer = writer
    yield writer
    await writer.stop()
```
Constraint (RESEARCH Wave-0 gaps): current callers take `analytics_writer` bare — keep the default shape for them; add interval/retention passthrough (e.g. a second fixture `analytics_retention_writer(analytics_db)` constructing `AnalyticsWriter(analytics_db, retention_days=..., purge_interval_s=0.05)`, or params). Fixture style to copy: `@pytest_asyncio.fixture`, function-scoped, lazy `from main import app` inside, `app.state` injection, teardown stop.

---

### `tests/test_config.py` (and/or `tests/test_startup_validation.py`) — knob validation tests (test)

**Analog:** `tests/test_startup_validation.py:35-43` — the exact validator-test block this phase replicates for retention:
```python
def test_analytics_queue_size_validator_rejects_zero():
    """ANALYTICS_QUEUE_SIZE=0 would unbound asyncio.Queue — reject at construction."""
    with pytest.raises(ValidationError, match="ANALYTICS_QUEUE_SIZE"):
        _settings(analytics_queue_size=0)


def test_analytics_queue_size_validator_rejects_negative():
    with pytest.raises(ValidationError, match="ANALYTICS_QUEUE_SIZE"):
        _settings(analytics_queue_size=-3)
```
With the helper (tests/test_startup_validation.py:3-12):
```python
import pytest
from pydantic import ValidationError

from config import Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)
```
Conventions: `Settings(_env_file=None, **kw)` (never a second live singleton — PROJECT.md constraint); `pytest.raises(ValidationError, match="<ENV_VAR_NAME>")`; plain sync tests; one-line docstring naming the hazard. Retention cases to mirror: default 90 / `0` accepted (cf. `test_settings_default_constructs_without_app_api_key`, lines 46-49, for the accepts-shape) / negative rejected / non-int rejected. `tests/test_config.py:6-7` carries the identical `_settings` helper if that file is chosen instead.

---

### `README.md` — env table row + migration note (docs)

**Analog:** Gateway Settings table (README.md:186-198):
```markdown
### Gateway Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_API_KEY` | Yes | -- | Gateway authentication token |
| ...
| `ANALYTICS_DB_PATH` | No | `data/analytics.db` | SQLite database path for analytics |
| `CORS_ORIGINS` | No | -- | Comma-separated allowed origins |
| `RATE_LIMIT` | No | `60/minute` | Rate limit per client IP |
```
→ add an `ANALYTICS_RETENTION_DAYS` | No | `90` | row next to `ANALYTICS_DB_PATH` (line 196), carrying the one-time `VACUUM` migration note + the "default purges the current 23 legacy rows" consequence (RESEARCH Runtime State Inventory / assumptions A2-A3). Note: `ANALYTICS_QUEUE_SIZE` has no README row today — out of scope, but the new row belongs beside `ANALYTICS_DB_PATH` regardless.

---

### `AGENTS.md` — analytics section update (docs)

**Analog:** the bullets this phase extends (AGENTS.md:185-192, Important Files):
```markdown
- `analytics/db.py` — `AnalyticsDB` (aiosqlite, WAL mode); `request_logs` schema
  (incl. `credits_used`) + 3 indexes (`created_at`, `model`, `provider`).
...
- `.env.example` — canonical list of required/optional env vars (mirrors
  `Settings` fields exactly): `MANIFEST_API_KEY`, `ZAI_CODING_API_KEY` (optional; ...),
  `ZAI_CREDITS_5H`/`ZAI_CREDITS_WEEK` (defaults `28000`/`140000`), `LLM_API_KEY` (fallback),
  `APP_API_KEY` (required), `CORS_ORIGINS`, `RATE_LIMIT` (default `60/minute`),
  `ANALYTICS_DB_PATH` (default `data/analytics.db`).
```
Update spots: the `analytics/db.py` bullet (mention `purge_expired` retention + `auto_vacuum=INCREMENTAL`), the `.env.example` env enumeration (append `ANALYTICS_RETENTION_DAYS`, default `90`, `0`=keep-forever + the one-time `sqlite3 data/analytics.db "VACUUM;"` legacy note), the `analytics/` Key Directories row (~line 98), and the writer description in Code Conventions (~lines 142-146) if the loop semantics text needs the 6h purge mention. Keep the doc's factual, comma-dense style.

## Shared Patterns

### Parameterized SQL + per-statement commit
**Source:** `analytics/db.py:78-99`
**Apply to:** `purge_expired` batch loop (cutoff and batch size bound as `?`, never f-interpolated — RESEARCH Security V5).
```python
await self._db.execute("... WHERE created_at < ? LIMIT ?", (cutoff, batch))
```

### Fire-and-forget error containment
**Source:** `analytics/writer.py:57-60` (`except Exception: logger.exception(...)` inside `_run`), `analytics/db.py:103-104`
**Apply to:** the purge call site in `_run`/`_purge` — purge failures must log, never crash the consumer task or leak to clients; `purge_expired` itself propagates, the loop contains.

### Fail-fast validation naming the env var
**Source:** `config.py:53-61` (validator) + `analytics/writer.py:18-24` (ctor `ValueError`)
**Apply to:** `analytics_retention_days` validator; message format `"<ENV_VAR> must be ... (got ...)"`.

### Deterministic async testing
**Source:** `tests/test_analytics_writer.py:81-107` (Event gate + `sleep(0)`), `:217-276` (slowed_log + patch + gather + exactly-once asserts), `tests/test_analytics_db.py:179-188` (timedelta-offset seeding)
**Apply to:** every retention test — injected `purge_interval_s`/`created_at`, bounded sub-second awaits, `wait_drained(5.0)` before reads, asserts on counters (`purges_run`, `dropped`) and pragma values (`page_count`/`freelist_count`), never wall-clock file sizes or real 6h cadence.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none — all files have role-exact analogs) | | | |

Sub-mechanics with no in-repo precedent (RESEARCH supplies the verified reference implementations — do not improvise alternatives): the `rowid IN (SELECT ... LIMIT ?)` batched DELETE (02-RESEARCH.md Pattern 1), the guarded `incremental_vacuum` loop, the deadline `wait_for` tick (02-RESEARCH.md Pattern 2), and the `retention_days=0` opt-out short-circuit.

## Metadata

**Analog search scope:** repo root — `analytics/`, `tests/`, `config.py`, `main.py`, `README.md`, `AGENTS.md`, `.env.example`, `pytest.ini` (full-file reads; 12 files, 1,874 + 200 lines)
**Tracked-source gate:** all named analogs verified via `git ls-files -- <path>` (non-empty for every path; no `.gsd/` or capability-mirror paths involved)
**Recency check:** Phase-1 files last touched by `5a1ff68`/`25e4557` (fix(01) polish commits) — analogs are the freshest patterns in the repo
**Pattern extraction date:** 2026-09-08
