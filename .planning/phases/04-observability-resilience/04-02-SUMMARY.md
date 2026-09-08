---
phase: 04-observability-resilience
plan: 02
subsystem: api
tags: [tenacity, retry, resilience, openai-sdk, zai-coding, backoff]

# Dependency graph
requires:
  - phase: 04-observability-resilience
    provides: "04-01's metrics.py record_request()/render() and /health/live+/health/ready split — no file overlap with this plan (providers/openai_compatible_base.py and tests/test_openai_compatible_base.py were untouched by 04-01)"
provides:
  - "Same-provider-only transient retry (APIConnectionError/APITimeoutError/InternalServerError) around the pre-stream create() call in OpenAICompatibleProvider.chat_stream(), up to 3 total attempts with exponential backoff+jitter"
  - "max_retries=0 on AsyncOpenAI construction, closing a pre-existing silent ZAI-3 gap where the SDK's own default retry (2) could retry a z.ai quota/auth failure before application code ever saw it"
  - "before_sleep retry logging (base_url/attempt-number/exception-class-name only, no message content)"
affects: [ZAICodingProvider, ManifestProvider (both inherit chat_stream unchanged — zero code), routes/chat.py error mapping (unchanged, contract preserved via reraise=True), Phase-5 docs refresh (DOCS-01/02 should note the new tenacity dependency)]

# Actuals (#2632)
actuals:
  tokens: 2695
  tasks: 2
  commits: 3
  plan_head_before: 45f2c3b

# Tech tracking
tech-stack:
  added: ["tenacity>=9.0 (floor-only pin, matches repo convention)"]
  patterns: ["AsyncRetrying constructed inline and awaited directly on the coroutine to retry (never a @retry decorator on an async-generator method) — the correct tenacity idiom for retrying one call inside a larger async generator", "Allow-list retry predicate (retry_if_exception_type over an explicit tuple) instead of a deny-list, so quota/auth exceptions are excluded by omission rather than by matching class name or status code — closes the z.ai '1113' edge case which arrives under an arbitrary status code"]

key-files:
  created: []
  modified: [providers/openai_compatible_base.py, requirements.txt, tests/test_openai_compatible_base.py]

key-decisions:
  - "TDD task 1 followed RED-GREEN discipline literally: wrote 2 failing tests (retry-succeeds-on-3rd-attempt, max_retries=0) against the unmodified source, confirmed both failed on the exact target assertions (not collection/fixture errors), committed as test(04-02), then implemented the tenacity wrap + max_retries=0 and confirmed both green, committed as feat(04-02). No REFACTOR commit needed — the GREEN implementation needed no cleanup."
  - "Task 2's exhaustion test asserts identity/type against the FINAL attempt's exception (not the first), since tenacity's reraise=True re-raises whichever exception the last failed attempt produced — this is correct semantics for 'the client sees the result of exactly one upstream attempt's worth of information' after retries are exhausted, and was caught as a test-design bug during this plan's own verification loop (see Deviations)."
  - "All retry-path tests patch asyncio.sleep (tenacity's AsyncRetrying calls it internally via _portable_async_sleep for real wall-clock backoff) so the file's 2 backoff-triggering tests don't slow the suite down — full 9-test file runs in ~0.4s instead of the ~2s it took before this patch was applied uniformly."

requirements-completed: [OBSV-03]

coverage:
  - id: D1
    description: "A transient network/5xx failure from the current provider is retried up to 2 additional times with exponential backoff+jitter before the client sees a failure"
    requirement: "OBSV-03"
    verification:
      - kind: unit
        ref: "tests/test_openai_compatible_base.py#test_retry_succeeds_on_third_attempt_after_transient_errors"
        status: pass
    human_judgment: false
  - id: D2
    description: "z.ai quota (429/1113) and auth (401/403) failures are never retried — the client sees the result of exactly one upstream attempt"
    requirement: "OBSV-03"
    verification:
      - kind: unit
        ref: "tests/test_openai_compatible_base.py#test_quota_1113_shaped_exception_is_never_retried"
        status: pass
      - kind: unit
        ref: "tests/test_openai_compatible_base.py#test_auth_failure_shaped_exception_is_never_retried"
        status: pass
    human_judgment: false
  - id: D3
    description: "The openai SDK's own internal retry is disabled (max_retries=0) so tenacity is the sole retry authority, closing a pre-existing silent ZAI-3 violation"
    requirement: "OBSV-03"
    verification:
      - kind: unit
        ref: "tests/test_openai_compatible_base.py#test_client_constructed_with_max_retries_zero"
        status: pass
    human_judgment: false
  - id: D4
    description: "After retry exhaustion, the client sees the existing provider-distinct SSE error mapping unchanged — reraise=True preserves the original exception (not a tenacity RetryError wrapper) after exactly 3 attempts"
    requirement: "OBSV-03"
    verification:
      - kind: unit
        ref: "tests/test_openai_compatible_base.py#test_exhausted_transient_failure_reraises_original_exception"
        status: pass
    human_judgment: false
  - id: D5
    description: "Retry-attempt logging never leaks request messages or prompt content — only base_url, attempt number, and exception class name"
    requirement: "OBSV-03"
    verification:
      - kind: unit
        ref: "tests/test_openai_compatible_base.py#test_before_sleep_logging_never_includes_message_content"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-09-08
status: complete
---

# Phase 4 Plan 2: Tenacity Retry (Same-Provider-Only, ZAI-3 Preserved) Summary

**`tenacity.AsyncRetrying` wraps only the pre-stream `create()` call in `OpenAICompatibleProvider.chat_stream()` (3 total attempts, exponential backoff+jitter, allow-list predicate), paired with `max_retries=0` on `AsyncOpenAI` construction that closes a pre-existing, previously undetected gap where the SDK's own default retry could silently retry a z.ai quota/auth failure before ZAI-3's never-retry rule ever saw it.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-09-08
- **Completed:** 2026-09-08
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- `requirements.txt`: `+ tenacity>=9.0` (floor-only pin, matches repo convention)
- `providers/openai_compatible_base.py`: `AsyncOpenAI` constructed with `max_retries=0`; `client.chat.completions.create(**kwargs)` wrapped in an inline `AsyncRetrying` (`stop_after_attempt(3)`, `wait_exponential_jitter(initial=0.5, max=8.0)`, `retry_if_exception_type((APIConnectionError, APITimeoutError, InternalServerError))`, `reraise=True`); a `before_sleep` closure logs only `base_url`/attempt-number/exception-class-name
- `tests/test_openai_compatible_base.py`: 6 new tests covering all 5 OBSV-03 `must_haves` — happy-path retry-succeeds-on-3rd-attempt, `max_retries=0` construction, quota/1113-shaped exclusion, auth-shaped exclusion, retry-exhaustion re-raise semantics, and the no-message-content logging prohibition
- Full suite: 126 → 132 passing (126 baseline + 6 new retry tests), all green

## Task Commits

Task 1 (TDD: RED → GREEN, no REFACTOR needed):
1. **RED: failing tests for tenacity retry + max_retries=0** - `22cd9f6` (test)
2. **GREEN: tenacity AsyncRetrying wrap + max_retries=0** - `58696a5` (feat)

Task 2:
3. **Exclusion, exhaustion, and no-message-leak coverage** - `5371579` (test)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP update)

## Files Created/Modified

- `providers/openai_compatible_base.py` — `AsyncOpenAI(..., max_retries=0)`; `_RETRYABLE` allow-list constant; `AsyncRetrying`-wrapped `create()` call with `before_sleep` logging closure over `self.base_url`
- `requirements.txt` — `+ tenacity>=9.0`
- `tests/test_openai_compatible_base.py` — 6 new tests (retry-succeeds, max_retries=0, quota exclusion, auth exclusion, exhaustion re-raise, no-leak logging), plus `asyncio.sleep` patched across every retry-path test to keep the suite fast

## Decisions Made

- Followed the task's `tdd="true"` attribute literally for Task 1: wrote the 2 target tests against the unmodified source first, confirmed genuine RED (both failed on the exact planned assertion — one on the un-retried `APIConnectionError` propagating, one on `max_retries == 2` not `0` — not on collection or fixture errors), committed, then implemented and confirmed GREEN before committing.
- Used an allow-list predicate (`retry_if_exception_type` over an explicit 3-type tuple) rather than a deny-list keyed on `RateLimitError`/`AuthenticationError`, per 04-RESEARCH.md's verified finding that the z.ai "1113" balance-exhausted signal arrives under an arbitrary status code in this codebase's existing fixtures (modeled as `status_code=402`) — a deny-list keyed on exception class name could still retry it, an allow-list structurally cannot.
- Fixed a test-design bug found during Task 2's own verification: the exhaustion test initially asserted the re-raised exception `is` the *first* attempt's exception, but `reraise=True` correctly re-raises the *last* failed attempt's exception (semantically correct — the client should see the most recent failure's details, not a stale earlier one). Corrected the test to assert identity/type against the final attempt's exception and to confirm it is not a `tenacity.RetryError` wrapper.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Exhaustion test asserted wrong exception identity**
- **Found during:** Task 2, first run of `test_exhausted_transient_failure_reraises_original_exception`
- **Issue:** Test asserted `exc_info.value is <first-attempt exception>`, but `AsyncRetrying(reraise=True)` re-raises the *last* attempt's exception, not the first — the test was wrong, not the implementation.
- **Fix:** Renamed the asserted variable to `final_exception` (the 3rd `side_effect` entry) and asserted identity/type against it, plus an explicit `not isinstance(..., tenacity.RetryError)` check and an attribute-preservation check (`.request is final_exception.request`).
- **Files modified:** `tests/test_openai_compatible_base.py`
- **Verification:** `.venv/bin/python -m pytest tests/test_openai_compatible_base.py -v` — all 9 tests pass; full suite 132/132.
- **Committed in:** `5371579` (Task 2 commit — the test was fixed before that single commit, never landed broken)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 test-correctness bug, caught before commit)
**Impact on plan:** No scope creep — same test file, same function, no new surface. The bug was in the test's understanding of tenacity's `reraise=True` semantics, not in the production code; the production wrap already behaved correctly.

## Issues Encountered

None beyond the test-design bug documented above, caught and fixed within this plan's own verification loop before any commit landed.

## User Setup Required

None — no external service configuration required. `tenacity` is a pure-Python dependency already present in `.venv` (confirmed `9.1.4` installed, matching the `>=9.0` floor pin).

## Next Phase Readiness

- OBSV-03 fully satisfied: same-provider-only transient retry with backoff, quota/auth structurally excluded, SDK's own silent retry disabled, retry exhaustion preserves the original exception for `routes/chat.py`'s unchanged error mapping, retry logging never leaks prompt content.
- `ZAICodingProvider` and `ManifestProvider` both inherit this retry behavior for free — zero code changes needed in either subclass, confirming the plan's `<reversibility>` and threat-model claims (`T-04-02-01/02/03` all mitigated).
- `routes/chat.py`'s error-mapping code was not touched, per the plan's explicit `must_haves` constraint — verified by the exhaustion test asserting `reraise=True` preserves the real exception type/attributes rather than a `RetryError` wrapper.
- Phase 4's third requirement (OBSV-02, per-key rate limiting) is a separate, disjoint plan touching `rate_limiter.py`/`routes/chat.py`/`config.py` — no file overlap with this plan's `providers/openai_compatible_base.py` change.
- `AGENTS.md`'s dependency list (`fastapi, uvicorn, pydantic-settings, openai, python-dotenv, aiosqlite, pytest, pytest-asyncio, httpx, slowapi, limits`) is now stale by one entry (missing `tenacity`) — flagged here for the Phase-5 DOCS-01/02 refresh rather than fixed now (out of this plan's `files_modified` scope).

---
*Phase: 04-observability-resilience*
*Completed: 2026-09-08*

## Self-Check: PASSED

- FOUND: providers/openai_compatible_base.py
- FOUND: requirements.txt contains `tenacity>=9.0`
- FOUND: tests/test_openai_compatible_base.py
- FOUND: commit 22cd9f6 (test RED)
- FOUND: commit 58696a5 (feat GREEN)
- FOUND: commit 5371579 (test task 2 coverage)
