---
phase: 01-gateway-runtime-hardening
plan: 1
subsystem: infra
tags: [asyncio, fastapi, sse, sqlite, aiosqlite, pytest, analytics]

requires: []
provides:
  - "Bounded AnalyticsWriter — drop-newest queue, single serial consumer, bounded drain-on-stop"
  - "Nested OpenAI-style SSE error frames ({error: {message, type[, code]}}) with locked zai mappings"
  - "ANALYTICS_QUEUE_SIZE config knob (default 1000, documented in .env.example)"
  - "analytics_writer pytest fixture — manual writer injection for ASGITransport (lifespan never runs)"
affects: [01-gateway-runtime-hardening plans 02-03, 04-observability]

plan_head_before: a3f7c33f569f5f221d41e702454f2a606b782002

actuals:
  tokens: 187
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Bounded asyncio.Queue producer-consumer: put_nowait/drop-newest with counted drops (warn every 50), task_done() in finally, stop() = wait_for(queue.join(), timeout) then cancel"
    - "Nested OpenAI error object in SSE frames; message strings byte-identical to prior flat frames (ZAI-3 preserved)"
    - "Test-lifespan bridge: manually construct/start/inject lifespan-owned state (analytics_writer) because httpx.ASGITransport never runs the ASGI lifespan"

key-files:
  created:
    - analytics/writer.py
    - tests/test_analytics_writer.py
  modified:
    - routes/chat.py
    - main.py
    - config.py
    - .env.example
    - tests/conftest.py
    - tests/test_chat_endpoint.py
    - static/playground/playground.js
    - AGENTS.md

key-decisions:
  - "Writer's stop() logs drop total as self.dropped + residual qsize; drain bounded by _DRAIN_TIMEOUT_S = 5.0"
  - "Shutdown ordering is the contract: await writer.stop() strictly before await db.close() (reversed order silently drops the drained tail)"
  - "Import os deferred to Plan 02: Task 1's action text mentions it, but the phase artifact inventory (authoritative) assigns the os import to Plan 02's writable-check; it is unused in this plan's scope"
  - "TDD RED recorded as fixture-missing failure ('no writer exists' — the plan's own predicted RED cause); single feat commit after green per the plan's explicit commit instruction (workflow tdd_mode is off)"

patterns-established:
  - "Analytics producer pattern: enqueue(record) inside the generator's finally (exactly-once incl. GeneratorExit), never a per-stream background task"
  - "Frame-equality testing at parsed-JSON level (Unicode code points), never raw-wire substring equality of full messages"
  - "Deterministic DB-row visibility in tests: await writer.wait_drained(timeout) instead of timing sleeps"

requirements-completed: [RELI-02, RELI-03]

coverage:
  - id: D1
    description: "Bounded analytics write path — AnalyticsWriter queue, lifespan start/stop ordering, producer swap from fire-and-forget create_task"
    requirement: RELI-02
    verification:
      - kind: integration
        ref: "tests/test_analytics_writer.py#test_error_stream_delivers_nested_frame_and_logs_row"
        status: pass
    human_judgment: false
  - id: D2
    description: "Nested OpenAI-style SSE error frames — quota (429 + 1113), auth, generic (no code key), empty-message edge; internal exception text never client-side"
    requirement: RELI-03
    verification:
      - kind: integration
        ref: "tests/test_chat_endpoint.py#test_zai_coding_quota_error_frame"
        status: pass
      - kind: integration
        ref: "tests/test_chat_endpoint.py#test_zai_coding_1113_code_maps_to_quota"
        status: pass
      - kind: integration
        ref: "tests/test_chat_endpoint.py#test_zai_coding_auth_error_frame"
        status: pass
      - kind: integration
        ref: "tests/test_chat_endpoint.py#test_generic_provider_error_unaffected"
        status: pass
      - kind: integration
        ref: "tests/test_chat_endpoint.py#test_empty_message_exception_yields_generic_frame"
        status: pass
    human_judgment: false
  - id: D3
    description: "Playground renders the nested error.message in the chat bubble at both SSE parse sites (file now git-tracked)"
    requirement: RELI-03
    verification:
      - kind: other
        ref: "source assertion: parsed.error?.message count == 2, bare-object throw count == 0, 'Unknown gateway error' fallback x2"
        status: pass
    human_judgment: true
    rationale: "Zero-build vanilla-JS playground (locked PROJECT.md decision — no JS test harness); the visual error bubble can only be confirmed in a browser (make dev + /playground against a failing provider)"
  - id: D4
    description: "Deterministic analytics-row visibility in tests — analytics_writer fixture injection plus wait_drained replacing the 0.1s timing sleep"
    verification:
      - kind: integration
        ref: "tests/test_chat_endpoint.py#test_zai_coding_request_logs_credits"
        status: pass
    human_judgment: false

duration: 9 min
completed: 2026-09-08
status: complete
---

# Phase 1 Plan 1: Gateway Runtime Hardening — Tracer Summary

**Bounded AnalyticsWriter (drop-newest queue → serial SQLite drain) + nested OpenAI-style SSE error frames, proven end-to-end by a mid-stream quota failure delivering token frames, the exact quota error object, [DONE], and exactly one request_logs row**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-08T04:41:50Z
- **Completed:** 2026-09-08T04:51:05Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments
- New `analytics/writer.py`: bounded `asyncio.Queue` (default 1000, `ANALYTICS_QUEUE_SIZE`), non-blocking `enqueue` with drop-newest + counted drops (warn every 50), single consumer task serially calling `AnalyticsDB.log_request` (unchanged), `task_done()` in `finally`, bounded `stop()` drain + drop-total log — replaces the per-stream fire-and-forget `create_task` + `_on_log_task_done` pattern (deleted)
- SSE error frames upgraded from flat strings to the nested OpenAI error object `{"error": {"message", "type"[, "code"]}}` with the locked mapping (zai 429/1113 → `rate_limit_error`/`zai_quota_exhausted`; zai 401/403 → `authentication_error`/`zai_auth_failed`; else `server_error`, no code) — human message strings byte-identical (ZAI-3 preserved), `[DONE]` terminator kept, `verify_auth` 401 JSON untouched
- Lifespan wires the writer after `db.initialize()` and stops it strictly before `db.close()`; `app.state.analytics_writer` injected; read endpoints keep `app.state.analytics_db`
- Playground (now git-tracked) unwraps `parsed.error?.message` with `'Unknown gateway error'` fallback at both SSE parse sites — kills the `[object Object]` bubble
- Tests: end-to-end tracer test (nested frame + `[DONE]` + exactly one row after drain), exact parsed-object equality for all four error variants plus the empty-message-exception edge, internal exception text proven absent from responses, deterministic `wait_drained` replacing the timing sleep

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end error-path tracer — bounded writer + nested SSE error frame** - `4196aeb` (feat)
2. **Task 2: Playground renders error.message at both SSE parse sites** - `9093c78` (fix)
3. **Task 3: Full frame-shape test coverage for all four error variants** - `91b52a2` (test)

**Plan metadata:** (recorded below after state updates)

## Files Created/Modified
- `analytics/writer.py` — NEW: `AnalyticsWriter` (bounded queue, drop-newest, drain/stop lifecycle)
- `tests/test_analytics_writer.py` — NEW: end-to-end tracer test (Plan 03 extends with queue-unit + burst tests)
- `routes/chat.py` — producer swap to `analytics_writer.enqueue` (12-key record unchanged); nested error-object yield; `_on_log_task_done` + `asyncio` import deleted
- `main.py` — lifespan constructs/starts the writer, `app.state.analytics_writer`, ordered shutdown `writer.stop()` → `db.close()`
- `config.py` — `analytics_queue_size: int = 1000`
- `.env.example` — `ANALYTICS_QUEUE_SIZE=1000` documented
- `tests/conftest.py` — `analytics_writer(analytics_db)` fixture; `client(analytics_db, analytics_writer)` injects both `app.state` handles
- `tests/test_chat_endpoint.py` — `_sse_frames`/`_error_frame` helpers; exact-object assertions on all four error tests; new empty-message test; `wait_drained` replaces `asyncio.sleep(0.1)`
- `static/playground/playground.js` — both parse sites read `parsed.error?.message` (file now tracked)
- `AGENTS.md` — four prose edits: architecture step 6 (bounded-queue pattern), step 7 (nested frame + code keys), Async bullet, fixtures list

## Decisions Made
- `stop()` logs the drop total as `dropped + residual qsize()` and names the timeout on drain failure — per probe-verified RESEARCH Pattern 1
- `import os` deferred to Plan 02 (phase artifact inventory assigns it to the writable-check; unused here — avoids a dead import)
- TDD RED evidence: the tracer test failed first with `fixture 'analytics_writer' not found` — the plan's own predicted cause ("no writer exists"); committed as a single `feat` after green per the plan's explicit instruction (repo `tdd_mode` is off)

## Deviations from Plan

None - plan executed exactly as written. (The `import os` timing note and RED-evidence classification above are plan-internal clarifications, not behavior changes.)

## Issues Encountered
None — all 73 tests green on the first post-implementation run; no auto-fixes needed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Tracer proven: the phase's two riskiest seams (queue/lifecycle ordering; frame change + client compatibility) are verified on the earliest commit
- Plan 02 (startup validation) builds on the untouched lifespan abort pattern; Plan 03 (concurrency proof) extends `tests/test_analytics_writer.py` using the now-available `qsize()`/`wait_drained()`/`dropped` surface
- Manual-only item for end-of-phase UAT: browser check of the playground error bubble (`make dev` → /playground → failing provider → expect the human message, not `[object Object]`)

## Self-Check: PASSED

All 11 key files exist on disk; all 3 task commits (4196aeb, 9093c78, 91b52a2) present in git log; commits measured from the plan ledger = 3 (matches frontmatter); full suite 73 passed exit 0.

---
*Phase: 01-gateway-runtime-hardening*
*Completed: 2026-09-08*
