# Phase 1: Gateway Runtime Hardening - Research

**Researched:** 2026-09-08
**Domain:** FastAPI lifespan/runtime hardening — pydantic-settings startup validation, bounded asyncio.Queue analytics write path, OpenAI-style SSE error frames, deterministic pytest-asyncio concurrency testing
**Confidence:** HIGH (implementation mechanics verified empirically against this repo's own venv: Python 3.14.7, pydantic-settings 2.13.1, fastapi 0.135.3, slowapi 0.1.9, limits 5.8.0, pytest-asyncio 1.3.0; protocol shapes verified against OpenAI's official OpenAPI spec)

## Summary

Phase 1 hardens the running gateway in three places that are all already structurally present in the codebase: (1) startup validation — `main.py`'s lifespan already aborts on missing `APP_API_KEY` (`raise RuntimeError("APP_API_KEY env var is required but not set")` — [VERIFIED: main.py:23-24]); the phase adds a pydantic `Settings` `model_validator` for `RATE_LIMIT` parseability plus cheap lifespan checks (`ANALYTICS_DB_PATH` parent writable) and no-abort notices for missing effective provider keys. (2) Bounded analytics writes — `routes/chat.py`'s fire-and-forget `asyncio.create_task(analytics_db.log_request(...))` ([VERIFIED: routes/chat.py:117-131]) is replaced by a bounded `asyncio.Queue` + single dedicated writer task started/stopped in lifespan; `AnalyticsDB` itself is untouched. (3) SSE error frames — the flat `{"error": "<msg>"}` frame ([VERIFIED: routes/chat.py:99]) becomes the OpenAI error object `{"error": {"message", "type", "code"}}`, and the playground's `throw new Error(parsed.error)` ([VERIFIED: static/playground/playground.js:128,145]) must read `.message` or it will display `[object Object]`.

Three probe-backed findings drive the plan's shape. **First**, slowapi accepts a malformed `RATE_LIMIT` both at `Limiter(...)` construction and at `@limiter.limit(...)` decoration — the failure is deferred to request time as a cryptic error [VERIFIED: runtime probe, slowapi 0.1.9], which is precisely the RELI-01 failure mode; a `model_validator` using `limits.parse_many` (already installed transitively via slowapi — not a new dependency) fails fast at `Settings()` construction, and since `from config import settings` precedes every slowapi/Limiter import in the module graph, the validator always fires first. **Second**, `httpx.ASGITransport` does NOT execute the ASGI lifespan [VERIFIED: runtime probe], so the existing `client` fixture never runs the new writer startup — tests must either inject the writer manually (matching the fixture's existing `app.state.analytics_db` override pattern) or invoke `async with lifespan(app)` directly (FastAPI documents this exact pattern). **Third**, the complete writer lifecycle (drop-newest on `QueueFull`, every-50-drops warning log, gated drain, bounded `stop(timeout)` with cancel + lost-count, 20 concurrent streams over one `AsyncClient`/`ASGITransport` with full token delivery and exactly-once rows) was executed end-to-end in probes and behaves deterministically [VERIFIED: runtime probes T1–T4b].

**Primary recommendation:** Add `analytics_queue_size: int = 1000` to `Settings` (+ `ANALYTICS_QUEUE_SIZE` in `.env.example`); implement an `AnalyticsWriter` class in a new `analytics/writer.py` (bounded `put_nowait` producer API, single consumer task calling the existing `AnalyticsDB.log_request` unchanged, `stop(timeout=5.0)` drain); wire start/stop in `main.py` lifespan around `db.close()` (writer stops BEFORE db closes); change the three SSE error yield sites to the nested object with the locked message strings verbatim; fix both playground parse sites to read `parsed.error.message`; prove RELI-02 with a 20-stream `asyncio.gather` burst test (slowed fake `log_request`, qsize sampler, post-drain exactly-once row assert) plus queue unit tests with a gated writer.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Startup Validation Surface**
- Only `APP_API_KEY` missing aborts startup (already exists in lifespan — extend, don't redesign)
- Validation lives in pydantic `Settings` model_validator + lifespan checks — structured and testable without booting the app
- Also validate cheaply at startup: `RATE_LIMIT` string parses, `ANALYTICS_DB_PATH` parent dir writable — fail fast naming the variable
- Missing Manifest key (no `MANIFEST_API_KEY` and no `LLM_API_KEY`) → startup **notice** (log), never abort — matches z.ai-key semantics; keeps zero-key dev/test runs working

**Bounded Analytics Write Path**
- Bounded `asyncio.Queue` + single dedicated writer task started in lifespan; producers `put_nowait`, one consumer serially drains to SQLite (aiosqlite is serial; WAL already set)
- Queue-full policy: drop newest + increment dropped-counter; log summary every 50 drops — client streams never block on analytics
- Queue size default 1000, env knob `ANALYTICS_QUEUE_SIZE` (documented in `.env.example`)
- Shutdown: stop accepting, drain queue with bounded wait (~5s), log dropped-total — no lost tail on restart

**OpenAI-Style SSE Error Frames**
- Frame shape: `data: {"error": {"message": "...", "type": "...", "code": "..."}}` (nested object per OpenAI convention)
- Mapping: quota → `type: "rate_limit_error"`, `code: "zai_quota_exhausted"`; zai auth → `type: "authentication_error"`, `code: "zai_auth_failed"`; other → `type: "server_error"`, no code. Human message strings stay exactly the current locked ones (ZAI-3 preserved)
- Playground error rendering updated to read `error.message` (it would otherwise show `[object Object]`)
- No pre-flight provider ping — upstream failures before first token surface as SSE error frames (first upstream call is inside the stream); gateway-auth failures stay plain 401 JSON

**Concurrency Verification**
- RELI-02 proof = pytest asyncio burst: ~20 concurrent streams × fake providers + artificially slowed DB writer; assert full token delivery per client and exactly-once `request_logs` rows — deterministic, part of `make test`
- Separate unit test for queue behavior: overfill → drop-newest + counter; unblock writer → drained rows + drop log
- Dropped-writes visibility: log-only this phase (warning every 50 drops + total at shutdown); Prometheus counter deferred to Phase 4 (OBSV-01)
- Explicit bounded assertion: `queue.qsize() <= cap` sampled during the burst test

### Claude's Discretion
None — all areas resolved in smart discuss.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. (Prometheus drop-counter explicitly deferred to Phase 4 OBSV-01.)

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RELI-01 | Operator starting the gateway without `APP_API_KEY` gets an immediate, actionable startup abort naming the missing variable; starting with no effective z.ai key logs an explicit notice (no abort), GLM routes degrade to Manifest per the key-gate | Existing lifespan abort verified [VERIFIED: main.py:23-24] + uvicorn abort behavior verified (traceback + `Application startup failed. Exiting.` + exit code 3, <1s). `model_validator(mode="after")` error format verified on installed pydantic-settings 2.13.1. `limits.parse_many` rejection of malformed strings verified on installed limits 5.8.0. Slowapi's lazy request-time parse verified — the current cryptic-failure path. Settings instance mutation for monkeypatching verified. |
| RELI-02 | Under concurrent multi-stream load, every client receives its full token stream and every completed request appears exactly once in `request_logs`; pending writes stay bounded even when SQLite writes lag | Full writer lifecycle (drop-newest, every-50 log, gated drain, bounded stop, 20-stream `asyncio.gather` burst over one `AsyncClient`/`ASGITransport`, qsize sampling, exactly-once rows after drain) executed end-to-end in runtime probes. `AnalyticsDB.log_request` contract (closed-DB no-op, uuid4 PK) verified [VERIFIED: analytics/db.py:62-91]. |
| RELI-03 | SSE error frames carry an OpenAI-style error object (message/type) while quota/auth remain distinctly identifiable; internal exception text never reaches clients | `ErrorResponse = {error: Error}` with `message`/`type` required and `code`/`param` optional verified from OpenAI's official OpenAPI spec (`ErrorObject`, lines 38431-38437) and the installed openai 2.32.0 SDK's spec-generated `ErrorObject`. Spec example types `rate_limit_error` (429 example) and `server_error` (schema docstring) verified in-spec; `authentication_error` is NOT an OpenAI-spec string (see Assumptions/Provenance note below — decision is locked, shape is conformant). Current error-mapping code and message strings verified [VERIFIED: routes/chat.py:89-99]. Playground `[object Object]` failure mode located at both parse sites [VERIFIED: static/playground/playground.js:128,145]. |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Startup config validation (RELI-01) | Application process (pydantic Settings + lifespan) | — | Single-process gateway; validation must precede request serving; `Settings()` is the first import-time construction point |
| Analytics write serialization (RELI-02) | Application process (asyncio queue + writer task in lifespan) | Storage (aiosqlite, unchanged) | aiosqlite connection is serial by design; bounding/serializing belongs to the app's event loop, not the DB layer |
| SSE error frame shape (RELI-03) | API route layer (`_tracked_stream` yield sites) | Browser (playground renderer) | Errors originate inside the stream generator; only the client renderer must understand the object |
| Client auth error (unchanged) | API route layer (`verify_auth`) | — | Locked decision: gateway-auth failures stay plain 401 JSON [VERIFIED: routes/chat.py:35-40]; not part of SSE mapping |
| Rate-limit string parsing | Config validation (Settings model_validator) | — | Must fail before slowapi's lazy request-time parse does |

## Standard Stack

**No new packages.** This phase adds zero runtime or test dependencies (REQ-NFR-02 constraint honored). `limits` is already installed as slowapi's dependency and is imported directly for validation — that is a transitive-dep reuse, not a new dependency.

### Core (existing, verified installed in `.venv`)

| Library | Version (installed) | Purpose | Why Standard |
|---------|--------------------|---------|--------------|
| pydantic-settings | 2.13.1 | `Settings` + `@model_validator(mode="after")` for `RATE_LIMIT` parse validation | Already the config layer [VERIFIED: config.py]; `model_validator` is the documented pydantic v2 mechanism |
| asyncio (stdlib) | Python 3.14.7 (floor 3.12) | `Queue(maxsize=)`, `put_nowait`, `QueueFull`, `get`/`task_done`/`join`, `wait_for`, `create_task` | The canonical single-producer/single-consumer primitive; documented join/task_done contract [CITED: docs.python.org/3/library/asyncio-queue.html] |
| limits (via slowapi) | 5.8.0 | `parse_many` to validate `RATE_LIMIT` with the exact parser slowapi uses | Same parser = no drift between validation and enforcement; verified raising `ValueError` on malformed input |
| fastapi / starlette | 0.135.3 / 1.0.0 | lifespan context manager (writer start/stop) | Existing app pattern [VERIFIED: main.py:19-35] |
| aiosqlite | 0.22.1 | unchanged `AnalyticsDB.log_request` | Writer wraps it unchanged (locked decision) |
| pytest / pytest-asyncio | 9.0.3 / 1.3.0 | RELI-01..03 proof | Existing conventions (`asyncio_mode = auto` [VERIFIED: pytest.ini], `@pytest.mark.asyncio` kept per AGENTS.md) |
| httpx | 0.28.1 | `AsyncClient` + `ASGITransport` burst test | Existing fixture pattern [VERIFIED: tests/conftest.py:58-68] |

### Supporting
None required.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled `AnalyticsWriter` on `asyncio.Queue` | `asyncio.Queue.shutdown()` (3.13+) | REJECTED: Python 3.12 floor forbids 3.13-only APIs [VERIFIED: PROJECT.md Constraints "no 3.13-only syntax"; shutdown added in 3.13 per CPython docs] |
| Writer class in new `analytics/writer.py` | Logic inside `main.py` lifespan | New module keeps lifespan thin, matches existing `analytics/` package layout, and makes the class unit-testable without the app |
| `asgi-lifespan` package for lifespan-aware tests | Manual injection / `async with lifespan(app)` | REJECTED: new dependency (violates NFR-02); FastAPI docs show `async with lifespan(app)` works directly [CITED: fastapi.tiangolo.com/advanced/events/] |
| BackgroundTasks / arq / celery | asyncio.Queue + task | REJECTED: over-engineered for single-process; locked decision already specifies the queue design |

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
                       STARTUP (lifespan, before first request)
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Settings() import-time validation (model_validator):                 │
  │   RATE_LIMIT parses via limits.parse_many? ── no ──> ValidationError│
  │        │ yes                                                        │
  │ lifespan(app):                                                      │
  │   APP_API_KEY set? ────────────── no ──> RuntimeError (abort, exit) │
  │   ANALYTICS_DB_PATH parent writable? ─ no ──> RuntimeError (abort)  │
  │   effective zai key empty?  ─────── yes ─> logger.warning (notice)  │
  │   effective manifest key empty? ── yes ─> logger.warning (notice)   │
  │   mkdir parent; AnalyticsDB.initialize() (WAL)                      │
  │   writer = AnalyticsWriter(db, settings.analytics_queue_size)       │
  │   writer.start()  ──────────> [writer task: queue.get →             │
  │   app.state.analytics_writer = writer     log_request → task_done]  │
  └──────────────────────────────────────────────────────────────────────┘
                       REQUEST PATH (per POST /v1/chat/completions)
  client ──Bearer──> verify_auth ──401 JSON on failure (unchanged)
          ──> limiter.limit(RATE_LIMIT)
          ──> _tracked_stream generator:
                provider.chat_stream ──token──> data: {"token": ...}
                exception ──> map to (message,type,code)
                              ──> data: {"error": {message,type[,code]}}
                              ──> data: [DONE]
                finally: writer.enqueue(record)   ── put_nowait
                          └─ queue full? ──> drop incoming + dropped++,
                                             warn every 50 drops
                       SHUTDOWN (lifespan, after last request)
  ┌──────────────────────────────────────────────────────────────────────┐
  │ await writer.stop(timeout=5.0):                                     │
  │   wait_for(queue.join(), 5s) ── timeout ──> cancel task, log lost   │
  │   log dropped-total                                                 │
  │ await db.close()   (AFTER writer stops — never before)              │
  └──────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
analytics/
├── db.py        # UNCHANGED — AnalyticsDB.log_request is wrapped as-is
└── writer.py    # NEW — AnalyticsWriter (queue, drop-newest, drain/stop)
config.py        # + analytics_queue_size field, + model_validator(RATE_LIMIT)
main.py          # lifespan: + writer start/stop, + writable-dir check, + key notices
routes/chat.py   # _tracked_stream: queue producer + nested error object
tests/
├── conftest.py       # + analytics_writer fixture (manual start/inject)
├── test_startup_validation.py   # NEW — RELI-01 (validator + lifespan)
├── test_analytics_writer.py     # NEW — RELI-02 (queue unit + burst)
└── test_chat_endpoint.py        # extended — RELI-03 frame shape
static/playground/playground.js  # both SSE parse sites read error.message
.env.example     # + ANALYTICS_QUEUE_SIZE=1000
```

### Pattern 1: `AnalyticsWriter` — bounded queue, single writer, drop-newest

**What:** One `asyncio.Queue(maxsize=N)`; producers call non-blocking `enqueue()`; one task serially drains to `AnalyticsDB.log_request`. Full lifecycle: `start()` in lifespan startup, `stop(timeout)` in lifespan shutdown **before** `db.close()`.
**When to use:** exactly this phase (locked decision).
**Example** (every mechanic executed in runtime probes T1–T4b this session):

```python
# analytics/writer.py — pattern verified by /tmp probes against this venv
import asyncio
import logging

logger = logging.getLogger(__name__)

_DRAIN_TIMEOUT_S = 5.0  # bounded shutdown wait (locked ~5s)


class AnalyticsWriter:
    """Serial analytics writer — bounds fire-and-forget DB writes.

    Producers enqueue without blocking (drop-newest on full); a single
    consumer task drains to AnalyticsDB. Client streams never wait on SQLite.
    """

    def __init__(self, db, queue_size: int = 1000):
        self._db = db
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task | None = None
        self.dropped = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="analytics-writer")

    def qsize(self) -> int:  # for the burst-test bounded assertion
        return self._queue.qsize()

    def enqueue(self, record: dict) -> None:
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self.dropped += 1
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
                self._queue.task_done()

    async def stop(self, timeout: float = _DRAIN_TIMEOUT_S) -> None:
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Analytics drain timed out after %ss — %d queued records lost",
                timeout, self._queue.qsize(),
            )
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        logger.info(
            "Analytics writer stopped — %d records dropped total",
            self.dropped + self._queue.qsize(),
        )
```

Probe results for this exact shape [VERIFIED: runtime probe T1–T4b]: cap-3 queue with 57 enqueues → `qsize()==3`, `dropped==54`, exactly one "50 records dropped" warning; gate release → drained rows all unique; `stop(timeout=0.5)` with a blocked writer returned in 0.50s with residue counted; 20 concurrent streams → all full bodies + 20 exactly-once rows after drain.

### Pattern 2: Validation split — model_validator (pure) vs lifespan (I/O + aborts)

**What:** String-parseable config (`RATE_LIMIT`) validated in `Settings` via `@model_validator(mode="after")`; things requiring the filesystem or an abort (`APP_API_KEY`, `ANALYTICS_DB_PATH` writable, key notices) stay in lifespan.
**When to use:** whenever validation must be "structured and testable without booting the app" (locked decision).
**Why the split matters:** every existing config unit test constructs `Settings(_env_file=None, **kw)` with NO `app_api_key` [VERIFIED: tests/test_config.py:6-7,10-22] — putting the APP_API_KEY abort into the model_validator would break all of them and make zero-key test runs impossible. The lifespan is the only place that can both check I/O (dir writable) and abort the process (uvicorn exits with code 3 [VERIFIED: runtime probe]).

```python
# config.py — verified output format on installed pydantic-settings 2.13.1
from limits import parse_many
from pydantic import model_validator


class Settings(BaseSettings):
    ...
    rate_limit: str = "60/minute"          # [VERIFIED: config.py:25 — current default]
    analytics_queue_size: int = 1000        # NEW
    model_config = {"env_file": ".env", "extra": "ignore"}  # [VERIFIED: config.py:30]

    @model_validator(mode="after")
    def _validate_rate_limit(self):
        try:
            parsed = list(parse_many(self.rate_limit))
        except ValueError as e:
            raise ValueError(
                f"RATE_LIMIT is not a valid rate string (expected e.g. '60/minute'): "
                f"{self.rate_limit!r} ({e})"
            ) from e
        if not parsed:
            raise ValueError(f"RATE_LIMIT parsed to zero limits: {self.rate_limit!r}")
        return self
```

Verified ValidationError output for `rate_limit="bogus/zzz"` (names the env var in the message) [VERIFIED: runtime probe P1a]:

```
1 validation error for Settings
  Value error, RATE_LIMIT is not a valid rate string (expected e.g. '60/minute'): 'bogus/zzz' (ValueError: couldn't parse rate limit string 'bogus/zzz') [type=value_error, ...]
```

`limits.parse_many` verified rejections on installed limits 5.8.0 [VERIFIED: runtime probe P2]: `"bogus"` → `ValueError: couldn't parse rate limit string 'bogus'`; `"60/fortnight"` → `no granularity matched for fortnight`; `"60"` and `"abc/minute"` → parse errors. Valid multi `"60/minute, 1000/hour"` passes. Because `from config import settings` executes before `from rate_limiter import limiter` and before the router imports in `main.py`'s module graph [VERIFIED: main.py:13 vs 58-59, rate_limiter.py:6], the validator aborts before slowapi ever sees the bad string.

### Pattern 3: SSE error frame mapping (RELI-03)

**What:** Replace the flat frame with the nested OpenAI error object; keep the exact current human message strings (ZAI-3).

Current code [VERIFIED: routes/chat.py:89-99 — quoted verbatim]:

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

Target mapping (locked; message strings byte-identical to the above):

| Trigger | message | type | code |
|---|---|---|---|
| zai 429 or "1113" in error | `zai-coding quota exhausted — resets within the 5-hour window` | `rate_limit_error` | `zai_quota_exhausted` |
| zai 401/403 | `zai-coding authentication failed` | `authentication_error` | `zai_auth_failed` |
| anything else | `Internal error processing request` | `server_error` | *(omitted)* |

```python
        # classify inside the except block
        if provider_name == "zai-coding":
            status = getattr(e, "status_code", None)
            if status == 429 or "1113" in error_msg:
                err_type, err_code = "rate_limit_error", "zai_quota_exhausted"
            elif status in (401, 403):
                err_type, err_code = "authentication_error", "zai_auth_failed"
            else:
                err_type, err_code = "server_error", None
        else:
            err_type, err_code = "server_error", None
        error_obj = {"message": client_msg, "type": err_type}
        if err_code:
            error_obj["code"] = err_code
        yield f"data: {json.dumps({'error': error_obj})}\n\n"
```

Wire-shape authority: OpenAI's OpenAPI spec defines `ErrorResponse` as `{"error": <Error>}` with `error.message` and `error.type` required strings, `error.code`/`error.param` optional [VERIFIED: openai-openapi.yaml:38431-38437 + SDK `openai/types/shared/error_object.py` — `code: Optional[str] = None`, `message: str`, `param: Optional[str] = None`, `type: str`]. The spec's own 429 example uses `type: rate_limit_error, code: slow_down` [VERIFIED: openai-openapi.yaml:88676-88682], and the `Error.type` docstring cites `"invalid_request_error", "server_error"` [VERIFIED: openai-openapi.yaml:48369-48371]. `authentication_error` does not occur in OpenAI's spec — it is the wider OpenAI-compatible ecosystem's convention (Anthropic's taxonomy uses it) — the CONTEXT decision locks it; the frame shape remains fully OpenAI-conformant either way (type is a free-form string in the spec).

**Keep after the change:** the `data: [DONE]\n\n` terminator still follows the error frame (current behavior [VERIFIED: routes/chat.py:135]); gateway auth failures remain plain `401 {"detail": "Invalid API key"}` JSON [VERIFIED: routes/chat.py:40]; the internal `error_msg`/`str(e)` still goes only to logs and the DB `error_message` column, never into the client frame.

### Pattern 4: Playground renderer fix (both parse sites)

Current code [VERIFIED: static/playground/playground.js:128 and 145 — quoted verbatim]:

```javascript
          const parsed = JSON.parse(data);
          if (parsed.error) throw new Error(parsed.error);   // object → "[object Object]"
          if (parsed.token) yield parsed.token;
```

Fix (identical at both sites — main loop line 128 AND the tail-buffer handler line 145, which exists for `[DONE]` frames split across chunks):

```javascript
          const parsed = JSON.parse(data);
          if (parsed.error) throw new Error(parsed.error?.message || 'Unknown gateway error');
          if (parsed.token) yield parsed.token;
```

The downstream guard `if (e.message && !e.message.includes('JSON')) throw e;` (lines 130-132, 147-149) still works: `"[object Object]"`/real messages don't contain "JSON", so the rethrow path is preserved. How the thrown error surfaces in the UI is handled by `sendMessage()`'s try/catch (error rendering path exists at [VERIFIED: static/playground/playground.js:256-286]); verify the rendered bubble shows the human message during the manual check.

### Pattern 5: Lifespan wiring and ordering (RELI-01/02 seam)

```python
# main.py lifespan — ordering is the contract
@asynccontextmanager
async def lifespan(app: FastAPI):
    # aborts (extend the existing pattern at main.py:23-24, don't redesign)
    if not settings.app_api_key:
        raise RuntimeError("APP_API_KEY env var is required but not set")
    if not settings.get_api_key("zai-coding"):
        logger.warning("No effective z.ai key (ZAI_CODING_API_KEY/LLM_API_KEY) — GLM routes degrade to Manifest")
    if not settings.get_api_key("manifest"):
        logger.warning("No effective Manifest key (MANIFEST_API_KEY/LLM_API_KEY) — non-GLM requests will fail upstream")

    db_path = settings.analytics_db_path
    parent = Path(db_path).parent
    parent.mkdir(parents=True, exist_ok=True)
    if not os.access(parent, os.W_OK):
        raise RuntimeError(f"ANALYTICS_DB_PATH parent directory is not writable: {parent}")

    db = AnalyticsDB(db_path)
    await db.initialize()
    writer = AnalyticsWriter(db, queue_size=settings.analytics_queue_size)
    writer.start()
    app.state.analytics_db = db            # unchanged — read endpoints keep using it directly
    app.state.analytics_writer = writer    # NEW — chat route produces into it
    logger.info("LLM Gateway started — analytics DB at %s", db_path)
    yield
    # Shutdown: writer drains BEFORE db closes — reversed order silently drops
    # the tail (log_request no-ops on a closed connection: `if not self._db: return`
    # [VERIFIED: analytics/db.py:64-65])
    await writer.stop()
    await db.close()
```

`get_api_key("zai-coding")` returns `self.zai_coding_api_key or self.llm_api_key` and `"manifest"` returns `self.manifest_api_key or self.llm_api_key` [VERIFIED: config.py:32-38] — exactly the "effective key" semantics the notices and the key-gate need.

### Anti-Patterns to Avoid

- **Do NOT use `asyncio.Queue.shutdown()` / `QueueShutDown`** — added in Python 3.13 [CITED: docs.python.org/3/library/asyncio-queue.html]; the repo floor is 3.12 (PROJECT.md constraint). Use the flag-less `join()`+`cancel()` pattern above.
- **Do NOT put the APP_API_KEY abort in the model_validator** — breaks every existing `Settings(_env_file=None, ...)` unit test and zero-key dev runs; it belongs in lifespan (locked decision).
- **Do NOT `await queue.put(...)` from the stream's finally block** — a full queue would block token streaming (violates REQ-NFR-05 and the locked "client streams never block" rule). `put_nowait` + drop only.
- **Do NOT hand-roll a rate-limit-string regex** — use `limits.parse_many`, the same parser slowapi uses, or validation and enforcement drift apart.
- **Do NOT slow the writer with real `time.sleep`** in tests — it blocks the event loop and the queue never fills; use per-write `await asyncio.sleep(...)` on a fake `log_request`, or gate with `asyncio.Event` (both verified deterministic in probes).
- **Do NOT keep `await asyncio.sleep(0.1)` hoping logs landed** (current pattern [VERIFIED: tests/test_chat_endpoint.py:186]) — with the queue, replace with `await writer._queue.join()` / a public `drain()` helper, then assert rows.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate-limit string validation | Custom regex for "N/unit" | `limits.parse_many` (installed) | Same parser slowapi enforces with; handles multi-limits, all granularities; verified error behavior |
| Bounded async producer/consumer | Custom deque + locks + conditions | `asyncio.Queue(maxsize=N)` + `put_nowait`/`join`/`task_done` | stdlib primitive with documented semantics; probes verify every needed behavior |
| Graceful shutdown wait | Custom deadline loop | `asyncio.wait_for(queue.join(), timeout)` | Documented pattern for timeouts on queue ops [CITED: docs.python.org/3/library/asyncio-queue.html] |
| Error frame schema | Inventing field names | OpenAI `ErrorResponse`/`ErrorObject` (message/type/code/param) | Spec-verified shape; existing OpenAI-compatible clients parse it |
| Test lifespan execution | Patching ASGI internals / new dep | `async with lifespan(app)` or manual writer injection | FastAPI documents invoking the lifespan context manager directly [CITED: fastapi.tiangolo.com/advanced/events/] |

**Key insight:** every moving part this phase needs is either stdlib (`asyncio.Queue`), already installed (`limits`, pydantic model_validator), or already in the codebase (`AnalyticsDB`, lifespan abort pattern, error mapping) — the phase is assembly and verification, not invention.

## Runtime State Inventory

> Not a rename/refactor phase, but the shutdown-path change touches runtime state — answered explicitly for completeness.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `data/analytics.db` (dev DB; WAL) — schema unchanged, `request_logs` PK `id TEXT PRIMARY KEY` [VERIFIED: analytics/db.py:14-28] | None — no migration |
| Live service config | None — no external services; single process | None — verified by AGENTS.md architecture (no config DB, no external stores) |
| OS-registered state | None — no task scheduler/launchd registrations | None |
| Secrets/env vars | New knob `ANALYTICS_QUEUE_SIZE` (add to `.env.example` + `Settings`); existing vars unchanged | Code edit only |
| Build artifacts | None affected (no package rename, no compiled artifacts) | None |

## Common Pitfalls

### Pitfall 1: `httpx.ASGITransport` never runs the lifespan — writer missing under test
**What goes wrong:** The `client` fixture yields `AsyncClient(transport=ASGITransport(app=app))` [VERIFIED: tests/conftest.py:66-67]; probe P5 confirmed zero lifespan events fire and `app.state` from lifespan is absent. A writer only started in lifespan would be `None` in every HTTP test → no rows, silently.
**How to avoid:** Extend `conftest.py` in the fixture's own style: construct `AnalyticsWriter(analytics_db, queue_size=...)`, `writer.start()`, set `app.state.analytics_writer`, yield, then `await writer.stop()` in teardown. (Probe T4b verifies manual injection end-to-end: 20 rows after drain.) Test the lifespan's own wiring separately via `async with lifespan(app)` with monkeypatched settings (Pattern 5).
**Warning signs:** HTTP tests pass but `request_logs` stays empty.

### Pitfall 2: slowapi defers RATE_LIMIT parsing to request time
**What goes wrong:** Verified on installed slowapi 0.1.9: `Limiter(key_func=..., default_limits=["bogus/zzz"])` constructs fine AND `@limiter.limit("bogus/zzz")` decorates fine [VERIFIED: runtime probe P4] — today a typo'd `RATE_LIMIT` produces a cryptic request-time failure, exactly what RELI-01 forbids.
**How to avoid:** The `Settings` model_validator (Pattern 2) fires at import of `config`, which precedes every slowapi/Limiter import in the module graph — startup abort with the variable named.
**Warning signs:** none at boot today (that's the bug).

### Pitfall 3: model_validator at import time changes failure surface
**What goes wrong:** `settings = Settings()` runs at import [VERIFIED: config.py:41]; a validator failure surfaces as an import-time `ValidationError` traceback (which names the env var in the message — verified format in Pattern 2). Under `make dev`/`make start` (uvicorn) the operator sees the traceback before the server binds.
**How to avoid:** Keep messages actionable (name the env var, show the bad value, show a valid example). Note in plan: `RATE_LIMIT` aborts at import; `APP_API_KEY`/`ANALYTICS_DB_PATH` abort in lifespan with uvicorn's clean `Application startup failed. Exiting.` + exit code 3 (verified, <1s — comfortably within NFR-04's 3s budget for the failure path).

### Pitfall 4: shutdown ordering — writer must stop BEFORE `db.close()`
**What goes wrong:** `AnalyticsDB.log_request` silently no-ops when the connection is closed (`if not self._db: return` [VERIFIED: analytics/db.py:64-65]) — closing the DB first silently loses the drained tail with zero errors logged.
**How to avoid:** `await writer.stop(); await db.close()` in that order; a unit test asserts both the ordering contract and that a stopped-then-closed writer produced all rows.

### Pitfall 5: `queue.join()` deadlock if `task_done()` is skipped on error
**What goes wrong:** If `log_request` raises and `task_done()` isn't called, `join()` never unblocks and `stop(timeout)` always times out.
**How to avoid:** `task_done()` in a `finally` around the write (Pattern 1). Note `AnalyticsDB.log_request` itself already swallows exceptions internally [VERIFIED: analytics/db.py:90-91], but the writer must not depend on that.

### Pitfall 6: drop-newest means drops are invisible unless counted
**What goes wrong:** `put_nowait` raising `QueueFull` is easy to miss; the dropped record is the INCOMING one (locked policy), so the queue never evicts old entries.
**How to avoid:** `self.dropped += 1` inside the `except QueueFull`; warn every 50 (verified firing exactly once at drop #50 in probe T1); log total at `stop()` (dropped counter + residue qsize).

### Pitfall 7: exactly-once vs. drop-newest — don't conflate the two tests
**What goes wrong:** A burst test configured with a tiny queue would drop records and fail the exactly-once assertion — the two behaviors are intentionally separate proof targets in the CONTEXT decisions.
**How to avoid:** Burst test: default/large cap (>20), slowed-but-flowing writer (per-write `await asyncio.sleep(0.005)`), assert 20 unique rows after drain + full token delivery + `qsize() <= cap` sampled. Queue unit test: small cap (e.g. 3–10), gated or absent throughput, assert drop counts/counter/log lines.

### Pitfall 8: `[object Object]` in the playground after the frame change
**What goes wrong:** `throw new Error(parsed.error)` stringifies the new nested object [VERIFIED: static/playground/playground.js:128,145].
**How to avoid:** Pattern 4 fix at BOTH sites; manual playground check is the only verification (no JS test infra exists — adding one is out of scope/YAGNI for a vanilla-JS no-build playground).

### Pitfall 9: generator `finally` runs on client disconnect — that's correct, keep it
**What goes wrong (if "fixed" wrongly):** When a client aborts mid-stream, the response generator is closed (`GeneratorExit`) and the `finally` still executes — the record still gets enqueued exactly once. Removing the finally-enqueue on disconnect would LOSE rows; moving it out of `finally` would double-enqueue on error paths.
**How to avoid:** Keep enqueue in the existing `finally` block, replacing only the `create_task` call [VERIFIED: current finally at routes/chat.py:101-133]. Exactly-once holds because the finally runs exactly once per generator.

### Pitfall 10: mutating `settings` in tests
**What goes wrong:** Lifespan tests need to flip `app_api_key`/`analytics_db_path` on the module-level singleton.
**How to avoid:** Verified: pydantic v2 BaseSettings instances are mutable without `validate_assignment` [VERIFIED: runtime probe P3] — `monkeypatch.setattr(settings, "app_api_key", "")` works and auto-restores. (Do not add `validate_assignment` to `model_config` during this phase or these tests break.)

### Pitfall 11: slowapi + lifespan shutdown interaction
**What goes wrong:** slowapi's in-memory `Limiter` holds no resources and registers nothing at shutdown — there is no ordering hazard with the writer. The real hazards are (a) Pitfall 4 and (b) `app.state.limiter` being set at module level (line 41), unaffected by lifespan. No slowapi-related shutdown work is needed.
**How to avoid:** Leave `rate_limiter.py` untouched this phase; per-key limits are Phase 4 (OBSV-02).

### Pitfall 12: burst-test determinism
**What goes wrong:** Real-time sleeps make the concurrency test flaky on slow CI.
**How to avoid:** Verified-deterministic recipe (probe T4/T4b): fake provider async-generators (no I/O), one `asyncio.gather(*[client.post(...) for _ in range(20)])` over the shared ASGI client, a sampler task polling `writer.qsize()`, slow writer = wrapped fake `log_request` with per-write `await asyncio.sleep(0.005)`, final `await queue.join()` before row assertions. The only timing dependence is the small sleep inside the fake writer, which orders — not races — the drain.

## Code Examples

### RELI-02 burst test skeleton (verified shape, probe T4)

```python
@pytest.mark.asyncio
async def test_concurrent_burst_full_delivery_exactly_once(client, auth_headers, analytics_writer):
    """~20 concurrent streams; slowed writer; full tokens + exactly-once rows."""
    originals = analytics_writer._db.log_request
    slow_delay = 0.005

    async def slow_log(record):
        await asyncio.sleep(slow_delay)          # deterministic lag, no real I/O
        await originals(record)

    analytics_writer._db.log_request = slow_log

    async def stream(i):
        async def gen(*a, **k):
            yield (f"tok{i}", None)
            yield ("", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        return gen

    # ... N=20 providers built like existing tests: patch create_provider with
    # per-request fake [convention: tests/test_chat_endpoint.py:21,108-109]

    samples: list[int] = []

    async def sampler():
        for _ in range(50):
            samples.append(analytics_writer.qsize())
            await asyncio.sleep(0.001)

    sampler_task = asyncio.create_task(sampler())
    responses = await asyncio.gather(*[
        client.post("/v1/chat/completions", json=..., headers=auth_headers)
        for _ in range(20)
    ])
    await sampler_task
    await asyncio.wait_for(analytics_writer._queue.join(), timeout=5.0)

    assert all(r.status_code == 200 for r in responses)
    for i, r in enumerate(responses):
        assert f"tok{i}" in r.text and r.text.endswith("data: [DONE]\n\n")
    assert max(samples) <= analytics_writer._cap   # bounded while writer lagged
    recent = await analytics_writer._db.get_recent(limit=100)
    assert recent["total"] == 20                   # exactly once
    assert len({row["id"] for row in recent["requests"]}) == 20
```

(Expose `queue_size`/`_queue` access via small public attributes on `AnalyticsWriter` — e.g. `qsize()` plus a `wait_drained(timeout)` helper — rather than reaching into privates from tests; skeleton shows the probe-verified mechanics.)

### RELI-01 lifespan test skeletons

```python
@pytest.mark.asyncio
async def test_missing_app_api_key_aborts_naming_variable(monkeypatch, tmp_path):
    from main import lifespan
    from config import settings
    monkeypatch.setattr(settings, "app_api_key", "")
    monkeypatch.setattr(settings, "analytics_db_path", str(tmp_path / "a.db"))
    with pytest.raises(RuntimeError, match="APP_API_KEY"):
        async with lifespan(app):  # startup raises before yield
            pass


@pytest.mark.asyncio
async def test_no_effective_zai_key_logs_notice_no_abort(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(settings, "app_api_key", "k")
    monkeypatch.setattr(settings, "zai_coding_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "analytics_db_path", str(tmp_path / "a.db"))
    with caplog.at_level(logging.WARNING):
        async with lifespan(app):
            pass   # no abort
    assert any("z.ai" in r.message.lower() for r in caplog.records)


def test_rate_limit_validator_rejects_garbage():
    with pytest.raises(ValidationError, match="RATE_LIMIT"):
        Settings(_env_file=None, rate_limit="bogus/zzz")
```

### RELI-03 frame assertion upgrade

Existing tests assert substrings (`assert "zai-coding quota exhausted" in response.text` [VERIFIED: tests/test_chat_endpoint.py:113]) — they keep passing. Add shape assertions:

```python
frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line[6:] != "[DONE]"]
err = next(f["error"] for f in frames if "error" in f)
assert err == {"message": "zai-coding quota exhausted — resets within the 5-hour window",
               "type": "rate_limit_error", "code": "zai_quota_exhausted"}
# generic path: no "code" key, message exactly "Internal error processing request",
# and str(exception used internally) not in response.text
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat SSE error `data: {"error": "..."}` (REQ-FR-21 baseline) | OpenAI error object `data: {"error": {message, type, code}}` (RELI-03) | This phase | Structured, machine-readable error frames; message strings unchanged (ZAI-3) |
| Fire-and-forget `create_task(log_request)` per stream | Bounded queue + single writer task | This phase | Bounded memory under lag; graceful drain on shutdown; drop visibility |
| Import-time/lazy config failure | Startup validation naming variables | This phase | Immediate actionable aborts (RELI-01) |

**Deprecated/outdated within this phase's scope:** `_on_log_task_done` + held-task-ref pattern in `routes/chat.py` [VERIFIED: routes/chat.py:114-143] becomes dead once the queue producer replaces `create_task` — remove it (clean cutover), the writer's own exception logging replaces it.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `make dev` / `make start` show the same startup-abort behavior as the direct uvicorn probe (they run `uvicorn main:app` per AGENTS.md; abort verified on uvicorn directly) | RELI-01 / Pitfall 3 | Low — same binary and entrypoint; if Makefile wraps output, the traceback still reaches stderr |
| A2 | The existing test suite is green on the current tree (per AGENTS.md's documented `make test`; full-suite run deliberately deferred to the orchestrator per subagent validation policy) | Validation Architecture | Low — if red, Wave 0 gains a triage step; no design impact |
| A3 | Playground manual check: the error path from `sendMessage()`'s catch renders the thrown `Error.message` in the chat UI (rendering code exists at playground.js:256-286; exact bubble behavior needs a browser) | Pattern 4 / Validation | Low — message string is proven to flow; only visual placement unverified |
| A4 | 20-stream burst keeps `make test` fast (probe: 20 streams + 5ms/write drain finished ≈0.1–0.2s) | Validation Architecture | Low — worst case tune to 10ms total delay |

All other claims in this research carry `[VERIFIED: ...]` (runtime probe against this repo's venv, or file+line quote read this session) or `[CITED: ...]` (official docs/spec) tags.

## Open Questions

1. **Playground error-rendering verification has no automated harness**
   - What we know: the JS fix is two one-line changes at proven sites; the SSE frame shape is test-covered server-side.
   - What's unclear: nothing structural — but the browser rendering itself can only be confirmed manually.
   - Recommendation: planner adds an execution-time manual verification step (run `make dev`, force a zai quota/auth error or point the fake provider at an error, observe the human message — not `[object Object]`) in the RELI-03 task.

2. **Exact notice wording for the two no-key warnings**
   - What we know: semantics locked (log, never abort, name the keys/semantics); wording is implementation detail.
   - Recommendation: include the variable names (`ZAI_CODING_API_KEY`, `LLM_API_KEY`, `MANIFEST_API_KEY`) and the routing consequence in each message (as in Pattern 5) so operators can act without docs.

No blocking questions — all design grey areas were resolved in CONTEXT.md; the mechanics above are verified.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv (`.venv`) | everything | ✓ | 3.14.7 (floor 3.12 per PROJECT.md) | — |
| pydantic / pydantic-settings | RELI-01 validator | ✓ | 2.13.1 / 2.13.1 | — |
| limits (slowapi dep) | RELI-01 rate-limit parse | ✓ | 5.8.0 | — |
| fastapi / starlette | lifespan wiring | ✓ | 0.135.3 / 1.0.0 | — |
| aiosqlite | RELI-02 writer | ✓ | 0.22.1 | — |
| pytest / pytest-asyncio / httpx | all verification | ✓ | 9.0.3 / 1.3.0 / 0.28.1 | — |
| uvicorn | RELI-01 abort behavior | ✓ | 0.44.0 | — |
| External services | none required | — | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = auto`) |
| Config file | `pytest.ini` (`[pytest]\nasyncio_mode = auto` — complete contents) |
| Quick run command | `.venv/bin/python -m pytest tests/test_analytics_writer.py -v` (per-file) |
| Full suite command | `make test` (`.venv/bin/python -m pytest tests/ -v`) |
| Conventions (binding, from AGENTS.md) | `@pytest.mark.asyncio` on every async test even though auto mode makes it redundant; `unittest.mock.patch` of `routes.chat.create_provider` / `resolve_provider` (no monkeypatch for providers, no `app.dependency_overrides`); `httpx.AsyncClient` over `ASGITransport`; no live z.ai calls; commits after every green task |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RELI-01a | Bad `RATE_LIMIT` → `ValidationError` naming RATE_LIMIT at Settings construction | unit | `.venv/bin/python -m pytest tests/test_startup_validation.py -k rate_limit -v` | ❌ Wave 0 |
| RELI-01b | Missing `APP_API_KEY` → lifespan RuntimeError naming APP_API_KEY (uvicorn exits 3, verified) | unit (lifespan ctx) | `... -k app_api_key -v` | ❌ Wave 0 |
| RELI-01c | No effective zai key → warning logged, startup completes; same for Manifest key | unit (lifespan ctx + caplog) | `... -k notice -v` | ❌ Wave 0 |
| RELI-01d | Unwritable `ANALYTICS_DB_PATH` parent → RuntimeError naming ANALYTICS_DB_PATH | unit (lifespan ctx) | `... -k writable -v` | ❌ Wave 0 |
| RELI-02a | 20 concurrent streams: full token delivery + exactly-once rows with slowed writer + `qsize() <= cap` sampled | integration (ASGI burst) | `.venv/bin/python -m pytest tests/test_analytics_writer.py -k burst -v` | ❌ Wave 0 |
| RELI-02b | Overfill → drop-newest: dropped counter exact, qsize never exceeds cap, warning every 50 drops | unit (gated fake db) | `... -k drop -v` | ❌ Wave 0 |
| RELI-02c | Unblock writer → drained rows exactly-once + drop total logged at stop | unit | `... -k drain -v` | ❌ Wave 0 |
| RELI-02d | `stop(timeout)` bounded on stuck writer; writer stops before `db.close()` (ordering contract) | unit | `... -k stop -v` | ❌ Wave 0 |
| RELI-03a | Quota frame = `{message: "zai-coding quota exhausted — resets within the 5-hour window", type: rate_limit_error, code: zai_quota_exhausted}` (both 429 and "1113" triggers) | integration | `.venv/bin/python -m pytest tests/test_chat_endpoint.py -k quota -v` | ✅ extend |
| RELI-03b | Auth frame = `{message: "zai-coding authentication failed", type: authentication_error, code: zai_auth_failed}` | integration | `... -k auth_error -v` | ✅ extend |
| RELI-03c | Generic frame = `{message: "Internal error processing request", type: server_error}` with NO code key; internal exception text absent | integration | `... -k generic -v` | ✅ extend |
| RELI-03d | Playground renders `error.message` (not `[object Object]`) | manual-only | `make dev` + browser: force provider error via fake/zai error, read bubble | n/a — no JS harness; justified by no-build vanilla-JS constraint |

**Manual-only justification (RELI-03d):** the playground is deliberately a zero-build static SPA (locked "Playground: static HTML + vanilla JS, no build step — YAGNI" in PROJECT.md); introducing a JS test runner would violate the no-build decision. Server-side frame shape is fully automated (a/b/c).

### Sampling Rate
- **Per task commit:** targeted file(s) for the task's requirement (commands above) — all <30s (burst probe ≈0.1–0.2s)
- **Per wave merge:** `make test` (full suite)
- **Phase gate:** full suite green before `/gsd:verify-work`; plus one manual playground error-render check

### Wave 0 Gaps
- [ ] `tests/test_startup_validation.py` — RELI-01a–d (Settings validator unit + `async with lifespan(app)` with monkeypatched settings)
- [ ] `tests/test_analytics_writer.py` — RELI-02a–d (queue unit + burst; gated/slowed fake `log_request`)
- [ ] `tests/conftest.py` — add function-scoped `analytics_writer` fixture (manual `AnalyticsWriter(analytics_db, queue_size=…)` + `start()` + `app.state.analytics_writer` injection + `stop()` teardown), mirroring the existing `analytics_db`/`client` fixture style; update `client` to depend on it
- [ ] `tests/test_chat_endpoint.py` — extend the four zai/generic error tests with full frame-shape assertions (RELI-03a–c); replace the `await asyncio.sleep(0.1)` log-wait (line 186) with explicit drain
- [ ] No framework install needed — infrastructure complete

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (unchanged) | Existing bearer gate `verify_auth` [VERIFIED: routes/chat.py:35-40]; failures stay plain 401 JSON — out of SSE mapping by locked decision |
| V3 Session Management | no | Stateless single-token gateway |
| V4 Access Control | no | Unchanged route guards; rate limiting untouched this phase |
| V5 Input Validation / Error Handling | **yes** | (1) Startup env validation via pydantic model_validator (RELI-01); (2) client-facing SSE error frames carry only curated messages — internal exception text stays in logs/DB `error_message` column, never in frames (RELI-03; existing constraint "client-facing errors never leak internal exception text" preserved and test-asserted) |
| V6 Cryptography | no | No crypto surface touched |

### Known Threat Patterns for FastAPI/async streaming stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Internal exception disclosure via SSE frames | Information Disclosure | Curated message table (Pattern 3); tests assert exception text absent from responses |
| Error-triggered resource exhaustion (unbounded task/queue growth under provider lag) | DoS | Bounded queue + drop-newest (RELI-02) — the phase's core deliverable |
| Config ambiguity (missing/wrong env) causing silently insecure runtime (e.g., empty auth key) | Misconfiguration | Fail-fast startup validation naming variables (RELI-01); `APP_API_KEY` empty already aborts |

## Sources

### Primary (HIGH confidence)
- Runtime probes executed 2026-09-08 against this repo's `.venv` (`/tmp/gsd-p1-probes/probe1.py`, `probe2.py`, `abort_app.py` + uvicorn run): pydantic-settings 2.13.1 model_validator error format; limits 5.8.0 `parse_many` behavior; slowapi 0.1.9 lazy parsing; ASGITransport lifespan skip; full AnalyticsWriter lifecycle incl. 20-stream burst, drop-newest, gated drain, bounded stop; uvicorn startup-abort exit path (exit code 3)
- OpenAI OpenAPI spec (raw.githubusercontent.com/openai/openai-openapi@master, downloaded this session): `ErrorResponse` schema (l.38431-38437), `Error.type` docstring (l.48369-48371), 429 example `type: rate_limit_error, code: slow_down` (l.88676-88682), 503 example `type: service_unavailable_error` (l.88700-88708); no `authentication_error` string anywhere in spec
- Installed `openai` 2.32.0 SDK `types/shared/error_object.py` (spec-generated): `code/message/param/type` field contract
- Repo source read this session: `main.py`, `config.py`, `routes/chat.py` (full `_tracked_stream`), `analytics/db.py` (schema, initialize, log_request), `rate_limiter.py`, `tests/conftest.py`, `tests/test_chat_endpoint.py`, `tests/test_config.py`, `tests/test_playground.py`, `pytest.ini`, `requirements.txt`, `.env.example`, `static/playground/playground.js` (both SSE parse sites + sendMessage catch), AGENTS.md, `.planning/{PROJECT,REQUIREMENTS,STATE}.md`, phase CONTEXT.md

### Secondary (MEDIUM confidence)
- [CITED: docs.python.org/3/library/asyncio-queue.html] — Queue/join/task_done/put_nowait/QueueFull semantics; `shutdown()` "Added in version 3.13"; wait_for for timeouts
- [CITED: fastapi.tiangolo.com/advanced/events/] — lifespan before-first-request / after-last-request semantics; `async with lifespan(app)` direct invocation pattern; lifespan-vs-events exclusivity
- [CITED: docs.pydantic.dev/latest/concepts/validators/] — field/model validator modes; ValueError → ValidationError behavior

### Tertiary (LOW confidence)
- None — no claim in this document rests on an unverified web-only source.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new deps; every listed version read from the live venv this session
- Architecture: HIGH — writer pattern and lifespan wiring executed end-to-end in probes against the exact installed versions; all integration points read in source
- Pitfalls: HIGH — pitfalls 1, 2, 4, 5, 6, 9, 10, 12 are probe- or source-verified, not folklore
- SSE error shape: HIGH for the object contract (spec + SDK); type-string provenance honestly split (rate_limit_error/server_error in-spec; authentication_error ecosystem-convention, decision locked in CONTEXT.md)

**Research date:** 2026-09-08
**Valid until:** 2026-10-08 (stable stack, no new deps; re-check only if requirements.txt pins move)

## RESEARCH COMPLETE
