# Phase 1: Gateway Runtime Hardening - Pattern Map

**Mapped:** 2026-09-08
**Files analyzed:** 10 (3 new, 7 modified)
**Analogs found:** 10 / 10 (every file has an analog; 2 new-behavior *mechanics* have none — see "No Analog Found")

**Tracked-source gate (GSD #3645):** every analog path below verified git-tracked via `git ls-files`
(`config.py`, `main.py`, `routes/chat.py`, `analytics/db.py`, `tests/conftest.py`,
`tests/test_config.py`, `tests/test_chat_endpoint.py`, `tests/test_analytics_db.py`, `.env.example`).
One modification target — `static/playground/playground.js` — is **untracked but present in the working
tree and NOT gitignored** (`git check-ignore` only flags `data/`); it is a file to edit, not an analog,
so no mirror-path propagation risk. Executor note: it must be `git add`-ed with the phase's commit.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `analytics/writer.py` (NEW) | service | queue producer-consumer (async drain to SQLite) | `analytics/db.py` | role-match (same package, async-lifecycle class; the queue mechanic itself is new) |
| `config.py` (MOD) | config | declarative settings / import-time validation | itself — `rate_limit` field + `model_config` + `get_api_key` | exact (self-modification) |
| `main.py` (MOD) | app entrypoint | startup/shutdown lifecycle | itself — existing `lifespan` abort pattern | exact (self-modification) |
| `routes/chat.py` (MOD) | route (controller) | SSE streaming + analytics produce | itself — `_tracked_stream` error mapping + finally-block | exact (self-modification) |
| `tests/conftest.py` (MOD) | test infra | fixture lifecycle (setup/teardown) | itself — `analytics_db` + `client` fixtures | exact (self-modification) |
| `tests/test_startup_validation.py` (NEW) | test | config validation + lifespan lifecycle | `tests/test_config.py` (+ `tests/test_chat_endpoint.py` for async conventions) | role-match |
| `tests/test_analytics_writer.py` (NEW) | test | queue unit + concurrent burst | `tests/test_analytics_db.py` (+ `tests/test_chat_endpoint.py` for the burst test) | role-match |
| `tests/test_chat_endpoint.py` (MOD) | test | SSE request-response | itself — the four zai/generic error-frame tests | exact (self-modification) |
| `static/playground/playground.js` (MOD) | frontend component | SSE stream consumption | itself — both parse sites + `sendMessage` catch | exact (self-modification) |
| `.env.example` (MOD) | config docs | declarative env knobs | itself — `RATE_LIMIT` / `ANALYTICS_DB_PATH` entries | exact (self-modification) |

---

## Pattern Assignments

### `analytics/writer.py` (NEW — service, queue producer-consumer)

**Analog:** `analytics/db.py` — same package, class encapsulating async I/O with an explicit
initialize/close lifecycle, per-module logger, one-line module docstring. The writer's
`start()`/`stop()` mirror `AnalyticsDB.initialize()`/`close()`; its consumer calls
`AnalyticsDB.log_request()` **unchanged** (locked decision).

**Module header pattern** (`analytics/db.py:1-12`):
```python
"""SQLite-backed analytics storage with async queries."""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import aiosqlite

from analytics.cost import is_peak

logger = logging.getLogger(__name__)
```
Copy for `writer.py`: one-line docstring stating purpose/why, stdlib → third-party → local import
groups, `logger = logging.getLogger(__name__)`. Only stdlib (`asyncio`, `logging`) is needed — no new imports.

**Async lifecycle-method pattern** (`analytics/db.py:41-46` and `57-60`):
```python
    async def initialize(self) -> None:
        """Create tables and enable WAL mode."""
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        ...
    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
```
`AnalyticsWriter.start()` / `stop(timeout)` follow the same shape: short methods, state guarded by
`None` checks (`if self._task is None: return` in `stop`, mirroring `if self._db:`).

**The wrapped contract — `log_request` is defensive; writer must NOT depend on it** (`analytics/db.py:62-67`):
```python
    async def log_request(self, record: dict) -> None:
        """Insert a request log record. Fire-and-forget safe."""
        if not self._db:
            return
```
This no-op-on-closed-DB behavior is why shutdown ordering matters (writer stops BEFORE `db.close()`)
and why the writer still needs its own `try/except` + `task_done()` in a `finally` around the write.

**The queue payload — record dict shape** (`routes/chat.py:117-130`, built in `_tracked_stream`'s finally):
```python
                task = asyncio.create_task(analytics_db.log_request({
                    "id": request_id,
                    "provider": provider_name,
                    "model": model_id,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": latency_ms,
                    "ttft_ms": ttft_ms,
                    "cost_usd": cost_usd,
                    "credits_used": credits_used,
                    "status": "error" if error_msg else "success",
                    "error_message": error_msg,
                }))
```
The producer swap keeps this dict byte-identical; only the dispatch changes (`writer.enqueue(record)`
instead of `create_task`). Constructor: `AnalyticsWriter(db, queue_size=settings.analytics_queue_size)`;
expose small public surface for tests — `qsize()` and a `wait_drained(timeout)` helper — rather than
test-reaching into `_queue` (research Code Examples note).

**Implementation body:** use the probe-verified `AnalyticsWriter` from
`01-RESEARCH.md` → "Pattern 1" verbatim (bounded `put_nowait`/drop-newest with `dropped` counter +
warn every 50; `_run` consumer with `task_done()` in `finally`; `stop()` = `wait_for(queue.join(), timeout)`
then cancel + log dropped-total). No codebase analog exists for the queue mechanic — see
"No Analog Found". Anti-patterns: no `asyncio.Queue.shutdown()` (Python 3.13-only; floor is 3.12),
no `await queue.put(...)` from the stream's finally (would block token streaming).

---

### `config.py` (MOD — config, import-time validation)

**Analog:** itself. Add `analytics_queue_size: int = 1000` field + `@model_validator(mode="after")`
for `RATE_LIMIT` (via `limits.parse_many`, already installed transitively via slowapi — no new dep).

**Field-declaration pattern with env-var comment** (`config.py:24-30`):
```python
    # Rate limiting
    rate_limit: str = "60/minute"  # Max requests per window per client

    # Analytics
    analytics_db_path: str = "data/analytics.db"

    model_config = {"env_file": ".env", "extra": "ignore"}
```
Add the new field in the Analytics block: `analytics_queue_size: int = 1000  # Bounded analytics write queue (drop-newest when full)`.
Do NOT add `validate_assignment` to `model_config` — tests monkeypatch the singleton's attributes
(RESEARCH Pitfall 10).

**Effective-key semantics for the startup notices** (`config.py:32-38`):
```python
    def get_api_key(self, provider: str) -> str:
        """Return API key for provider. Dedicated key with llm_api_key fallback."""
        if provider == "manifest":
            return self.manifest_api_key or self.llm_api_key
        if provider == "zai-coding":
            return self.zai_coding_api_key or self.llm_api_key
        return self.llm_api_key
```
Lifespan notices call `settings.get_api_key("zai-coding")` / `settings.get_api_key("manifest")` — exactly
the "no `MANIFEST_API_KEY` and no `LLM_API_KEY`" semantics from CONTEXT.

**Import-time singleton** (`config.py:41`): `settings = Settings()` — a validator failure surfaces as an
import-time `ValidationError` traceback; keep the message actionable (name `RATE_LIMIT`, show the bad
value, show a valid example). Use the validator body from `01-RESEARCH.md` → "Pattern 2" (verified
error format on installed pydantic-settings 2.13.1).

---

### `main.py` (MOD — app entrypoint, startup/shutdown lifecycle)

**Analog:** itself — extend the existing lifespan; do not redesign (locked decision).

**The pattern being extended, verbatim** (`main.py:19-35`):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize analytics DB on startup, close on shutdown."""
    # Validate required config
    if not settings.app_api_key:
        raise RuntimeError("APP_API_KEY env var is required but not set")

    # Startup
    db_path = settings.analytics_db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = AnalyticsDB(db_path)
    await db.initialize()
    app.state.analytics_db = db
    logger.info("LLM Gateway started — analytics DB at %s", db_path)
    yield
    # Shutdown
    await db.close()
```
Insertion points (from `01-RESEARCH.md` → "Pattern 5", which extends this exact block):
1. After the `APP_API_KEY` abort: two `logger.warning` notices when `get_api_key("zai-coding")` /
   `get_api_key("manifest")` are empty (log, never abort — locked); name the env vars and the routing
   consequence in each message.
2. After `mkdir`, before `AnalyticsDB(...)`: `os.access(parent, os.W_OK)` check →
   `raise RuntimeError(f"ANALYTICS_DB_PATH parent directory is not writable: {parent}")`.
3. After `await db.initialize()`: `writer = AnalyticsWriter(db, queue_size=settings.analytics_queue_size)`;
   `writer.start()`; `app.state.analytics_writer = writer` (keep `app.state.analytics_db` — read endpoints
   use it directly).
4. Shutdown ordering is the contract: `await writer.stop()` THEN `await db.close()` (reversed order
   silently drops the drained tail because `log_request` no-ops on a closed connection).
Add `from analytics.writer import AnalyticsWriter` to the local-import group (`analytics.db` import at
`main.py:13` shows the placement).

**Route-wiring style to preserve** (`main.py:58-63`): deferred router imports with `# noqa: E402` —
unchanged this phase.

---

### `routes/chat.py` (MOD — route/controller, SSE streaming + queue produce)

**Analog:** itself — two surgical edits inside `_tracked_stream`, plus deletion of the dead callback.

**SSE error mapping to convert** (`routes/chat.py:89-99`, verbatim — message strings are LOCKED byte-identical):
```python
    except Exception as e:
        error_msg = str(e)
        logger.error("Provider stream error: %s", error_msg)
        client_msg = "Internal error processing request"
        if provider_name == "zai-coding":
            status = getattr(e, "status_code", None)
            if status == 429 or "1113" in error_msg:
                client_msg = "zai-coding quota exhausted — resets within the 5-hour window"
            elif status in (401, 403):
                client_msg = "zai-coding authentication failed"
        yield f"data: {json.dumps({'error': client_msg})}\n\n"
```
Replace ONLY the final yield with the nested OpenAI error object; keep the classification conditions and
message strings untouched. Locked mapping (CONTEXT + RESEARCH Pattern 3):

| Trigger | message (unchanged) | type | code |
|---|---|---|---|
| zai 429 or `"1113" in error_msg` | `zai-coding quota exhausted — resets within the 5-hour window` | `rate_limit_error` | `zai_quota_exhausted` |
| zai 401/403 | `zai-coding authentication failed` | `authentication_error` | `zai_auth_failed` |
| anything else | `Internal error processing request` | `server_error` | *(key omitted)* |

```python
        error_obj = {"message": client_msg, "type": err_type}
        if err_code:
            error_obj["code"] = err_code
        yield f"data: {json.dumps({'error': error_obj})}\n\n"
```
Keep: `data: [DONE]\n\n` still follows the error frame (`routes/chat.py:135`); internal `error_msg`
still goes only to logs and the DB `error_message` column; `verify_auth` 401 stays plain JSON
(`routes/chat.py:35-41` — do not touch).

**Producer swap site** (`routes/chat.py:114-133`):
```python
        # Fire-and-forget DB log with reference held to prevent GC
        if analytics_db:
            try:
                task = asyncio.create_task(analytics_db.log_request({...}))
                task.add_done_callback(_on_log_task_done)
            except Exception:
                logger.exception("Failed to queue analytics log")
```
Replace with the queue producer, keeping the finally-block placement exactly (RESEARCH Pitfall 9:
the finally runs exactly once per generator — including client-disconnect `GeneratorExit` — which is
what makes enqueue exactly-once; moving it out would double-enqueue on error paths):
```python
        if analytics_writer:
            analytics_writer.enqueue({... same record dict, lines 118-129 ...})
```
`enqueue` is non-blocking (`put_nowait` + drop-newest inside the writer) so the stream never waits on
SQLite (locked: "client streams never block on analytics"). Fetch the writer the same way the route
already fetches the db — `getattr(request.app.state, "analytics_writer", None)` mirroring
`routes/chat.py:50` — and thread it into `_tracked_stream`'s parameter list in place of /
alongside `analytics_db` (read endpoints elsewhere are unaffected).

**Clean cutover — delete after the swap** (`routes/chat.py:138-143`):
```python
def _on_log_task_done(task: asyncio.Task):
    """Handle errors from fire-and-forget analytics log tasks."""
    if task.cancelled():
        return
    if exc := task.exception():
        logger.error("Analytics log task failed: %s", exc)
```
Dead once the producer lands (RESEARCH "Deprecated" note); the writer's own `logger.exception` in
`_run()` replaces it. AGENTS.md §"Code Conventions" documents the old held-ref+callback convention —
this phase intentionally supersedes it for the analytics path.

---

### `tests/conftest.py` (MOD — test infra, fixture lifecycle)

**Analog:** itself — add `analytics_writer` in the exact style of `analytics_db`, and make `client`
depend on it (RESEARCH Wave 0 gap: ASGITransport never runs the lifespan, so the writer must be
manually started/injected — Pitfall 1).

**Fixture style to mirror** (`tests/conftest.py:49-68`, verbatim):
```python
@pytest_asyncio.fixture
async def analytics_db(tmp_path):
    """In-memory AnalyticsDB for testing."""
    db = AnalyticsDB(":memory:")
    await db.initialize()
    yield db
    await db.close()

@pytest_asyncio.fixture
async def client(analytics_db):
    """Async test client with analytics DB injected."""
    from main import app

    # Override app.state.analytics_db with test DB
    app.state.analytics_db = analytics_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```
New fixture (same shape — construct/start/inject/yield/stop):
```python
@pytest_asyncio.fixture
async def analytics_writer(analytics_db):
    """AnalyticsWriter over the test DB (lifespan never runs under ASGITransport)."""
    from analytics.writer import AnalyticsWriter
    writer = AnalyticsWriter(analytics_db, queue_size=1000)
    writer.start()
    from main import app
    app.state.analytics_writer = writer
    yield writer
    await writer.stop()
```
Then `client` becomes `async def client(analytics_db, analytics_writer)` (keep the
`app.state.analytics_db` injection line — both states must be set since the lifespan that normally
sets them doesn't run). Import grouping: `from analytics.db import AnalyticsDB` sits in the local
group at `tests/conftest.py:11` — add `from analytics.writer import AnalyticsWriter` beside it (or
import inside the fixture like `from main import app`, matching the lazy-import style already used).

---

### `tests/test_startup_validation.py` (NEW — test, config validation + lifespan lifecycle)

**Analog A — Settings construction without env:** `tests/test_config.py:1-7` (verbatim):
```python
"""Unit tests for config.Settings — zai-coding key resolution."""

from config import Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)
```
Every config unit test uses `Settings(_env_file=None, **kw)` with NO `app_api_key` — this is precisely
why the `APP_API_KEY` abort must stay in lifespan, not the model_validator (RESEARCH Pattern 2 "why
the split matters"). The RELI-01a validator test copies this helper: expect
`pytest.raises(ValidationError, match="RATE_LIMIT")` for `rate_limit="bogus/zzz"`, plus a
valid-multi-limit acceptance case (`"60/minute, 1000/hour"`).

**Analog B — async test conventions:** `tests/test_chat_endpoint.py:1-6` imports +
`@pytest.mark.asyncio` decorator on every async test (binding per AGENTS.md even though
`asyncio_mode = auto`). The lifespan tests use `async with lifespan(app)` with
`monkeypatch.setattr(settings, ...)` — verified-mutable singleton (RESEARCH Pitfall 10) — per the
skeletons in `01-RESEARCH.md` → "RELI-01 lifespan test skeletons" (abort naming `APP_API_KEY`;
`ANALYTICS_DB_PATH` writable check against `tmp_path`; no-key notices asserted via `caplog` at
`logging.WARNING` with startup completing). No existing test drives the lifespan directly — see
"No Analog Found".

---

### `tests/test_analytics_writer.py` (NEW — test, queue unit + concurrent burst)

**Analog A — module/fixture/helper style:** `tests/test_analytics_db.py:1-40` (verbatim excerpts):
```python
"""Unit tests for analytics.db — AnalyticsDB CRUD operations."""
...
@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh AnalyticsDB for each test."""
    database = AnalyticsDB(":memory:")
    await database.initialize()
    yield database
    await database.close()


async def _insert_sample(db: AnalyticsDB, count: int = 5):
    """Insert sample records for aggregation tests."""
```
Conventions to copy: one-line module docstring naming the module under test; a record-builder helper
(`_insert_sample` analog → `_record(i)` producing the queue payload dict from `routes/chat.py:118-129`);
row assertions via the db's own query API (`get_recent`, `get_summary`) — e.g.
`(await db.get_recent(limit=100))["total"] == 20` and unique `id` set for exactly-once.
Prefer reusing the shared `analytics_db` fixture over re-declaring a local duplicate (AGENTS.md
explicitly flags `test_analytics_db.py`'s own `db(tmp_path)` duplicate as a pattern NOT to copy).

**Analog B — provider-fake + patch + client for the burst test:** `tests/test_chat_endpoint.py:102-114`
(the quota-frame test shows all three conventions at once):
```python
@pytest.mark.asyncio
async def test_zai_coding_quota_error_frame(client, auth_headers):
    class QuotaProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            yield ("tok", None)
            raise ZaiQuotaError("429 too many requests")

    with patch("routes.chat.create_provider", return_value=QuotaProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        response = await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )
```
Burst-test recipe (deterministic, RESEARCH Pitfall 12 + Code Examples skeleton): 20 concurrent
`client.post` via `asyncio.gather` over the ONE shared ASGI client; per-request fake provider classes
defined inline like above; slowed writer = wrap `analytics_writer._db.log_request` with a per-write
`await asyncio.sleep(0.005)` (never real `time.sleep`); `qsize()` sampler task; final
`wait_drained`/`queue.join()` before asserting 20 unique rows + full token delivery +
`max(samples) <= cap`. Queue-unit tests (drop-newest/drain/stop) run against `AnalyticsWriter` +
`analytics_db` directly — no `client` fixture, matching `test_analytics_db.py`'s no-HTTP layering
(so they stay in the `make test-unit` `-k "not client"` selection).

---

### `tests/test_chat_endpoint.py` (MOD — test, SSE request-response)

**Analog:** itself — extend the four existing error-frame tests with shape assertions; substring
asserts keep passing (message strings unchanged).

**The tests being extended** (`tests/test_chat_endpoint.py:102-114`, `118-128`, `133-147`, `151-164`):
```python
    assert "zai-coding quota exhausted" in response.text
    assert "Internal error" not in response.text
```
Add frame-parsing + exact-equality assertions per `01-RESEARCH.md` → "RELI-03 frame assertion
upgrade": parse `data: ` lines (skipping `[DONE]`), find the frame with an `error` key, and assert the
full object equality (`{"message": ..., "type": "rate_limit_error", "code": "zai_quota_exhausted"}`;
auth variant; generic variant asserts NO `code` key and that the internal exception text is absent
from `response.text`). Also assert `data: [DONE]\n\n` still terminates after the error frame
(current behavior, `routes/chat.py:135`).

**The wait-for-log line to replace** (`tests/test_chat_endpoint.py:186`, verbatim):
```python
    await asyncio.sleep(0.1)  # fire-and-forget log task
```
With the queue, replace the timing-based wait with an explicit drain (`await analytics_writer.wait_drained(...)`
or `await analytics_writer._queue.join()` — prefer the public helper) before asserting DB rows.
`asyncio` import already present at `tests/test_chat_endpoint.py:3`.

---

### `static/playground/playground.js` (MOD — frontend component, SSE stream consumption)

**Analog:** itself — two identical one-line fixes at the two parse sites; the downstream rendering
path already exists and needs no change.

**Parse site 1 — main read loop** (`static/playground/playground.js:126-131`, verbatim):
```javascript
          const parsed = JSON.parse(data);
          if (parsed.error) throw new Error(parsed.error);
          if (parsed.token) yield parsed.token;
        } catch (e) {
          if (e.message && !e.message.includes('JSON')) throw e;
```

**Parse site 2 — tail-buffer handler for `[DONE]` split across chunks** (`static/playground/playground.js:144-148`, verbatim):
```javascript
        const parsed = JSON.parse(data);
        if (parsed.error) throw new Error(parsed.error);
        if (parsed.token) yield parsed.token;
      } catch (e) {
        if (e.message && !e.message.includes('JSON')) throw e;
```
Both sites change identically (CONTEXT: otherwise the bubble shows `[object Object]`):
```javascript
          if (parsed.error) throw new Error(parsed.error?.message || 'Unknown gateway error');
```
The rethrow guard (`!e.message.includes('JSON')`) still works — human messages don't contain "JSON".

**Downstream rendering — unchanged, proves the fix lands in the UI** (`static/playground/playground.js:257-268`):
```javascript
    for await (const token of streamChat(apiMessages, conv.model, conv.systemPrompt, conv.params)) {
      appendToken(token);
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      // User cancelled — keep partial
    } else {
      ...
        lastMsg.content = `Error: ${err.message}`;
      ...
      renderMessage('error', `Error: ${err.message}`, false);
```
`err.message` is what the fix populates. Verification is manual-only (vanilla-JS no-build playground —
locked PROJECT.md decision; no JS test harness, adding one is out of scope): `make dev` + browser,
force a provider error, read the bubble (RELI-03d).

---

### `.env.example` (MOD — config docs, declarative env knobs)

**Analog:** itself — comment + `KEY=value` pairs mirroring `Settings` fields exactly (AGENTS.md).

**The entries being extended** (`.env.example:24-29`, verbatim):
```
# Rate limiting (per client IP)
RATE_LIMIT=60/minute

# Analytics database path
ANALYTICS_DB_PATH=data/analytics.db
```
Append after the `ANALYTICS_DB_PATH` block, same two-line shape:
```
# Analytics write queue size (drops newest + logs when full)
ANALYTICS_QUEUE_SIZE=1000
```

---

## Shared Patterns

### Per-module logger + defensive async I/O (never crash the request path)
**Source:** `analytics/db.py:10-12, 66-67, 89-91` · `routes/chat.py:17, 132-133`
**Apply to:** `analytics/writer.py` (all methods), `main.py` notices
```python
logger = logging.getLogger(__name__)
...
        except Exception:
            logger.exception("Failed to log request to analytics DB")
```
Broad `except Exception` + `logger.exception` around anything that must never break streaming; the
writer's `_run()` consumer follows this exactly (plus `task_done()` in `finally` — RESEARCH Pitfall 5).

### One-line module docstring on every file
**Source:** `analytics/db.py:1`, `tests/test_analytics_db.py:1`, `tests/test_config.py:1`
**Apply to:** `analytics/writer.py`, both new test files — e.g. `"""Unit tests for analytics.writer — bounded queue, drop-newest, drain/stop."""` (AGENTS.md binding convention.)

### Test conventions (AGENTS.md, binding)
**Source:** `tests/test_chat_endpoint.py:1-6, 108-109`; `tests/conftest.py:49-68`
**Apply to:** all three test files
- `@pytest.mark.asyncio` on every async test (kept despite `asyncio_mode = auto`)
- `unittest.mock.patch("routes.chat.create_provider", ...)` + `patch("routes.chat.resolve_provider", ...)` — never `monkeypatch` for providers, never `app.dependency_overrides`
- `httpx.AsyncClient` over `ASGITransport` via the shared `client` fixture; async fixtures use `@pytest_asyncio.fixture`
- snake_case test names `test_<subject>_<behavior>`; inline fake provider classes with
  `chat_stream(self, messages, system_prompt, params=None)` signature (3-arg-tolerant, see
  `tests/test_chat_endpoint.py:171-177` comment)

### Type hints & naming
**Source:** `routes/chat.py:32,74,77` (`float | None`, `str | None`); `analytics/db.py:40` `aiosqlite.Connection | None`
**Apply to:** `analytics/writer.py` — PEP 604 unions (`asyncio.Task | None`), builtin generics, PascalCase class,
snake_case methods, `_prefixed` privates with small public test surface (`qsize()`, `wait_drained()`).

### Client-facing errors: curated text only
**Source:** `routes/chat.py:89-99` (mapping table), AGENTS.md §Architecture item 7
**Apply to:** the RELI-03 frame change and its tests — internal `str(e)` goes to logs/DB column only;
tests assert the triggering exception's text is absent from `response.text`.

## No Analog Found

File-level analogs exist for everything; two *mechanics* are genuinely new in this codebase (planner
should use the probe-verified implementations in `01-RESEARCH.md` Patterns 1/2/3 rather than search
for code to copy):

| Mechanic | Used By | Reason |
|----------|---------|--------|
| Bounded `asyncio.Queue` producer-consumer with drop-newest + drain/stop lifecycle | `analytics/writer.py`, `tests/test_analytics_writer.py` | Codebase's only background-work pattern is fire-and-forget `create_task` + `add_done_callback` (`routes/chat.py:117-131`) — the exact thing being replaced. Research Pattern 1 is probe-verified against this venv. |
| Direct lifespan invocation in tests (`async with lifespan(app)` + `monkeypatch.setattr(settings, ...)`) | `tests/test_startup_validation.py` | No existing test runs the lifespan (ASGITransport skips it — probe P5); research skeletons are the pattern source. `monkeypatch.setattr` on the singleton is verified-mutable (probe P3). |

## Metadata

**Analog search scope:** repo root (git-tracked files), `routes/`, `analytics/`, `tests/`, `static/playground/`, `.env.example`, AGENTS.md
**Files scanned:** 10 analog/target files read + AGENTS.md conventions; anchors pinned via grep (all excerpt line numbers verified this session)
**Tracked-source check:** all 9 named analog paths git-tracked; `static/playground/playground.js` untracked-but-present (edit target; flag for `git add`)
**Pattern extraction date:** 2026-09-08
