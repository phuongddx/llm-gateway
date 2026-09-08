---
phase: 01-gateway-runtime-hardening
plan: 3
subsystem: testing
tags: [pytest, pytest-asyncio, asyncio, concurrency, burst-testing, sqlite, fastapi]

# Dependency graph
requires:
  - phase: 01-gateway-runtime-hardening
    provides: "01-01's bounded AnalyticsWriter (analytics/writer.py) + conftest analytics_writer/analytics_db fixtures — the code under proof"
provides:
  - Deterministic RELI-02 proof suite permanently part of make test (queue-unit + 20-stream burst + disconnect exactly-once)
  - Probe-verified deterministic async-test recipe (asyncio.Event gates, per-write await asyncio.sleep, qsize sampling)
affects: [02-analytics-retention (same write path), verify-work UAT for Phase 1]

# Actuals (#2632) — same estimateTokens scale (chars/4 over the realized diff), never a harness count.
actuals:
  tokens: 2747    # git diff over tests/test_analytics_writer.py, chars/4 (estimate was 20000 — plan over-estimated ~7x)
  tasks: 2
  commits: 2      # MEASURED: git rev-list --count 75564bf..HEAD

# Tech tracking
tech-stack:
  added: []       # zero new deps (REQ-NFR-02 honored)
  patterns:
    - "Deterministic concurrency testing: asyncio.Event gates + per-write await asyncio.sleep — never time.sleep (grep-gated)"
    - "Per-request inline fake providers via unittest.mock.patch side_effect list"
    - "Instance-attribute log_request wrappers to slow/gate the writer without touching production code"

key-files:
  created: []
  modified:
    - tests/test_analytics_writer.py

key-decisions:
  - "Identical-payload test follows TR6: byte-identical payloads with per-record uuid4 ids (production shape) — same-id duplicates are impossible under the request_logs uuid4 PK contract"
  - "Gated-drain assertion reads the deterministic pre/post-yield states (5 queued before the consumer runs; 4 queued + 1 in-flight while gated) — a started consumer always holds exactly one record in flight"
  - "Burst token assertion is order-independent (sorted set equality across all 20 responses) because provider↔response assignment under asyncio.gather is scheduling-dependent"
  - "Burst cap read via analytics_writer._queue.maxsize — no public cap accessor exists and the plan forbids production changes"

patterns-established:
  - "Event-gated/gated-wrapper writer tests: wrap analytics_db.log_request on the instance, never patch the module, never sleep for real"
  - "qsize sampling during gather as the locked bounded assertion (max(samples) <= cap)"

requirements-completed: [RELI-02]

# Coverage metadata (#1602) — deterministic UAT routing for verify-work.
coverage:
  - id: D1
    description: "Queue lifecycle mechanically proven: drop-newest accounting (cap-3 × 57 enqueues → qsize 3, dropped 54, exactly one warning at drop #50), identical-payload distinctness, gated drain exactly-once, bounded stop with residue counting, healthy stop, idle/never-started stop, single-record exactly-once"
    requirement: RELI-02
    verification:
      - kind: unit
        ref: "tests/test_analytics_writer.py::test_drop_newest_when_full_counts_and_logs_every_50 (+6 siblings)"
        status: pass
    human_judgment: false
  - id: D2
    description: "RELI-02a burst + disconnect edge: 20 concurrent streams over one shared ASGI client with a 5ms-per-write slowed writer — all 200s, full per-client token delivery + [DONE], sampled qsize <= cap, 20 unique request_logs rows; direct _tracked_stream aclose (GeneratorExit) enqueues exactly once"
    requirement: RELI-02
    verification:
      - kind: integration
        ref: "tests/test_analytics_writer.py::test_concurrent_burst_full_delivery_exactly_once, ::test_client_disconnect_midstream_still_enqueues_exactly_once"
        status: pass
    human_judgment: false

# Metrics
duration: 8min
completed: 2026-09-08
status: complete
plan_head_before: 75564bf5a80ceee9e0e0bb29a16341368d07f7aa
---

# Phase 01 Plan 3: Concurrency Proof Summary

**Deterministic pytest-asyncio proof of the bounded analytics write path: 20-stream gather burst with a slowed writer proves full token delivery + exactly-once rows, plus queue-unit tests for drop-newest/gated-drain/bounded-stop and a GeneratorExit disconnect proof — RELI-02 closed.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-09-08T05:06:55Z
- **Completed:** 2026-09-08T05:16:30Z (approx)
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Seven queue-unit tests (RELI-02b/c/d + empty/single/adjacency edges) — all passing against Plan-01's writer with exact-count assertions (54 drops / 3 kept / one warning at #50)
- 20-stream concurrent burst over one shared ASGI client with a per-write `await asyncio.sleep(0.005)` slowed writer: every response 200 with its own token + `[DONE]`, sampled `qsize() <= cap`, exactly 20 unique rows after `wait_drained`
- Disconnect proof: direct `_tracked_stream` generator `aclose()` (GeneratorExit) → exactly one enqueued record — the finally-block exactly-once contract, exercised not assumed
- Full suite 93 passed in ~1.3s (84 baseline + 9 new); burst repeat-run stability verified (two consecutive green runs, ≈0.25s each)

## Task Commits

Each task was committed atomically:

1. **Task 1: Queue unit tests — drop-newest, gated drain, bounded stop, idle/single** - `b494ab0` (test)
2. **Task 2: 20-stream concurrent burst + disconnect exactly-once** - `576a7e0` (test)

**Plan metadata:** see final docs commit below.

## Files Created/Modified
- `tests/test_analytics_writer.py` - extended from 51 to 316 lines: `_record(i)` 12-key payload builder, seven queue-unit tests, `_stream_tokens` SSE parser, burst + disconnect tests; module docstring updated

## Decisions Made
- Test-only plan executed as specified: no production code changes were needed — every test passed first run against Plan-01's `AnalyticsWriter` (the tests verified existing behavior, exactly the plan's intent: "the tests are the spec"; the tdd="true" RED expectation is inapplicable when the feature under proof already landed in 01-01 — investigated per the unexpected-GREEN rule, no defect found)
- Interpreted the plan's internally-inconsistent behavior parentheticals in favor of the binding `must_haves` truths (see Deviations 1–3)
- SUMMARY filename `01-03-SUMMARY.md` (repo/`gsd-tools` convention, matching 01-01/01-02) — the plan `<output>` block's `01-PLAN-03-SUMMARY.md` is a filename typo

## Deviations from Plan

### Clarified assertions (plan-text ambiguities, truths honored exactly)

**1. [Interpretation] Identical-payload test uses distinct uuid4 ids over byte-identical payloads**
- **Found during:** Task 1
- **Issue:** The behavior spec's parenthetical ("use truly identical dicts including id") contradicts its own assertion ("assert 2 rows with 2 distinct ids") and must-have TR6 — two dicts sharing one id cannot produce two rows under the `request_logs` uuid4 PK (the second INSERT fails the UNIQUE constraint and is swallowed by `log_request`)
- **Fix:** Implemented per TR6 ("identical payloads … (uuid4 ids)"): all 11 payload fields byte-identical, each record carries its own `str(uuid4())` — exactly the shape `routes/chat.py` produces per request
- **Files modified:** tests/test_analytics_writer.py
- **Verification:** `test_identical_payload_records_stay_distinct` green — 2 rows, 2 distinct ids
- **Committed in:** b494ab0

**2. [Interpretation] Gated-drain asserts the deterministic 4+1-in-flight state, not literal "stays 5"**
- **Found during:** Task 1
- **Issue:** "assert qsize() stays 5 while gated" is unreachable with a started writer — the consumer dequeues exactly one record and blocks with it inside the gate (5 enqueued − 1 in flight = qsize 4)
- **Fix:** Asserts qsize == 5 before any yield (consumer not yet run), then after one `asyncio.sleep(0)` yield qsize == 4 with zero rows — a strictly stronger proof that nothing drains while gated; release then yields 5 unique rows
- **Files modified:** tests/test_analytics_writer.py
- **Verification:** `test_gated_writer_drains_exactly_once_after_release` green
- **Committed in:** b494ab0

**3. [Interpretation] Burst token assertion is order-independent**
- **Found during:** Task 2
- **Issue:** "each body contains its own tok{i}" indexed by gather position is racy — which request receives which per-request provider is scheduling-dependent under concurrent gather
- **Fix:** Each response asserts exactly one token frame + `[DONE]`; across responses the sorted token multiset equals {tok0..tok19} — every stream fully delivered, no client crossed
- **Files modified:** tests/test_analytics_writer.py
- **Verification:** `test_concurrent_burst_full_delivery_exactly_once` green twice (repeat-run stability)
- **Committed in:** 576a7e0

---

**Total deviations:** 3 clarifications (0 production-code auto-fixes, 0 Rule 1–3 fixes)
**Impact on plan:** None — all must_have truths (TR1–TR7) are asserted exactly as locked; no scope creep, no production changes.

## Issues Encountered
- `grep -c "time.sleep"` initially returned 1 from a code *comment* ("never real time.sleep") — reworded the comment so the literal determinism gate reads 0

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- RELI-02 fully proven: implementation (01-01) + deterministic verification (this plan) — Phase 1's three requirements (RELI-01/02/03) are now all complete; phase ready for `/gsd:verify-work`
- The deterministic async-test recipe (gates, per-write async sleeps, qsize sampling) is reusable for Phase 2's purge-under-load tests

## Self-Check: PASSED

- tests/test_analytics_writer.py FOUND
- Commits b494ab0, 576a7e0 FOUND in git log
- Targeted runs exit 0; full suite 93 passed; burst stability 2× green
- Acceptance greps: time.sleep=0, def db(=0, analytics_db≥1, asyncio.gather≥1

---
*Phase: 01-gateway-runtime-hardening*
*Completed: 2026-09-08*
