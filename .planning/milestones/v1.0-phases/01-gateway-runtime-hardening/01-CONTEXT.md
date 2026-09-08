# Phase 1: Gateway Runtime Hardening - Context

**Gathered:** 2026-09-08
**Status:** Ready for planning

<domain>
## Phase Boundary

The live gateway fails fast on bad configuration and keeps every stream intact under concurrent load, with client-compatible error frames — the foundation for "no quota-exhaustion surprises across a full coding day". Delivers RELI-01 (startup validation), RELI-02 (bounded analytics writes + exactly-once logging under concurrent streams), RELI-03 (OpenAI-style SSE error frames). No observability stack, no retention, no deployment work — those are Phases 2/4.

</domain>

<decisions>
## Implementation Decisions

### Startup Validation Surface
- Only `APP_API_KEY` missing aborts startup (already exists in lifespan — extend, don't redesign)
- Validation lives in pydantic `Settings` model_validator + lifespan checks — structured and testable without booting the app
- Also validate cheaply at startup: `RATE_LIMIT` string parses, `ANALYTICS_DB_PATH` parent dir writable — fail fast naming the variable
- Missing Manifest key (no `MANIFEST_API_KEY` and no `LLM_API_KEY`) → startup **notice** (log), never abort — matches z.ai-key semantics; keeps zero-key dev/test runs working

### Bounded Analytics Write Path
- Bounded `asyncio.Queue` + single dedicated writer task started in lifespan; producers `put_nowait`, one consumer serially drains to SQLite (aiosqlite is serial; WAL already set)
- Queue-full policy: drop newest + increment dropped-counter; log summary every 50 drops — client streams never block on analytics
- Queue size default 1000, env knob `ANALYTICS_QUEUE_SIZE` (documented in `.env.example`)
- Shutdown: stop accepting, drain queue with bounded wait (~5s), log dropped-total — no lost tail on restart

### OpenAI-Style SSE Error Frames
- Frame shape: `data: {"error": {"message": "...", "type": "...", "code": "..."}}` (nested object per OpenAI convention)
- Mapping: quota → `type: "rate_limit_error"`, `code: "zai_quota_exhausted"`; zai auth → `type: "authentication_error"`, `code: "zai_auth_failed"`; other → `type: "server_error"`, no code. Human message strings stay exactly the current locked ones (ZAI-3 preserved)
- Playground error rendering updated to read `error.message` (it would otherwise show `[object Object]`)
- No pre-flight provider ping — upstream failures before first token surface as SSE error frames (first upstream call is inside the stream); gateway-auth failures stay plain 401 JSON

### Concurrency Verification
- RELI-02 proof = pytest asyncio burst: ~20 concurrent streams × fake providers + artificially slowed DB writer; assert full token delivery per client and exactly-once `request_logs` rows — deterministic, part of `make test`
- Separate unit test for queue behavior: overfill → drop-newest + counter; unblock writer → drained rows + drop log
- Dropped-writes visibility: log-only this phase (warning every 50 drops + total at shutdown); Prometheus counter deferred to Phase 4 (OBSV-01)
- Explicit bounded assertion: `queue.qsize() <= cap` sampled during the burst test

### Claude's Discretion
None — all areas resolved in smart discuss.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `main.py` lifespan already aborts when `APP_API_KEY` unset — extend this pattern
- `analytics/db.py` `AnalyticsDB` (aiosqlite, WAL) with `log_request()` — the writer task wraps it unchanged
- `routes/chat.py` `_tracked_stream()` currently fire-and-forgets `create_task(log_request(...))` with held refs + `_on_log_task_done` callback — replaced by queue put
- Existing zai-coding error mapping (quota 429/1113, auth 401/403) in `_tracked_stream` — messages reused verbatim

### Established Patterns
- pydantic-settings `Settings` singleton; env knobs documented in `.env.example` (mirrors Settings fields)
- Tests: pytest + pytest-asyncio, `httpx.AsyncClient` over ASGITransport, `unittest.mock.patch` of `create_provider`; async tests carry `@pytest.mark.asyncio`

### Integration Points
- Lifespan startup/shutdown (queue + writer task lifecycle)
- `_tracked_stream` finally-block → queue producer
- SSE error yield sites in `_tracked_stream`
- `static/playground/` JS error rendering (untracked dir, present in working tree)

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Prometheus drop-counter explicitly deferred to Phase 4 OBSV-01.)

</deferred>
