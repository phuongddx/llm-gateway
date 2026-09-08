---
phase: 02-analytics-retention-storage-lifecycle
plan: 2
subsystem: analytics
tags: [analytics-writer, retention, purge-scheduling, deadline-wakeup, asyncio-wait_for, queue-drain, fastapi-lifespan, sse-streaming, pytest-asyncio, sqlite]

# Dependency graph
requires:
  - phase: 02-analytics-retention-storage-lifecycle
    provides: "02-01's purge_expired, contained _purge() as the writer task's first action, purges_run/last_purged observables, retention_days ctor kwarg — the surfaces this plan rides"
provides:
  - Deadline-scheduled 6h purge tick inside the AnalyticsWriter consumer loop (_PURGE_INTERVAL_S = 21600.0 module constant, ctor-injectable purge_interval_s; wait_for(queue.get(), timeout=remaining) wakeup; no-drift next_purge recompute; get_nowait salvage on TimeoutError — Phase-1 record path byte-identical)
  - AnalyticsDB.purge_expired keyword-only between_batches hook — awaited after every per-batch commit including the final partial one
  - Writer _drain_queued between-batches drain — mid-purge burst records persist in the batch gaps (Pitfall 3 mitigation, dropped == 0)
  - tests/conftest.py analytics_retention_writer fixture (retention 90, 0.05s tick) — existing analytics_writer/client fixtures untouched
  - Six new proofs: periodic tick (reseeded row purged by a later pass), lifespan no-block under gated purge, interleave drain, per-batch hook, endpoints-post-purge (all four routes), burst-during-purge (20 streams, exactly-once, zero drops)
affects: [02-03 (documents ANALYTICS_RETENTION_DAYS + the purge lifecycle), verify-work UAT Phase 2]

# Actuals (#2632) — same estimateTokens scale (chars/4 over the realized diff), never a harness count.
actuals:
  tokens: 5415    # git diff 21660 chars / 4 (estimate was 26000 — plan over-estimated ~4.8x, same bias as 02-01)
  tasks: 2
  commits: 2      # MEASURED: git rev-list --count 31bda98..HEAD (ledger gsd-plan-head-before-02-02)
plan_head_before: 31bda98c3205dca3dd064512d13269cde0120d0e

# Tech tracking
tech-stack:
  added: []       # zero new deps (REQ-NFR-02 honored)
  patterns:
    - "Deadline-scheduled side job inside a queue-consumer task: wait_for(get(), timeout=remaining-to-deadline) + TimeoutError→get_nowait salvage (queue.get is cancellation-safe on Python 3.14, probe R3e) + deadline recomputed after each side job (no drift)"
    - "Between-batches hook (keyword-only callable→awaitable param) awaited after every per-batch commit incl. the final partial batch — keeps a long batch job from starving the queue it shares a task with"

key-files:
  created: []
  modified:
    - analytics/writer.py
    - analytics/db.py
    - tests/conftest.py
    - tests/test_analytics_retention.py

key-decisions:
  - "test_startup_purge_does_not_block_lifespan_readiness pins a guarantee that already holds on 02-01 code (startup purge is the task's first action, never an awaited lifespan step) — it RED'd as a pass-by-design pin whose job is surviving the _run rewrite (TR4); the other three tests RED'd exactly per plan (fixture missing / ctor TypeError / hook TypeError)"
  - "Burst test's purges_run >= 2 assert needed a bounded 2s poll INSIDE the try block before stop(): wait_drained can return mid-purge because the between-batches hook empties the queue before the pass ends, and the finally-block stop() would otherwise cancel the consumer before the first tick deadline — the tick itself fires within ~0.03s of the pass ending"
  - "The periodic-tick test waits out the startup purge (bounded loop on last_purged, 02-01's observable) before seeding the expired row — only a LATER pass can remove it, making the periodicity proof airtight instead of startup-pass-contaminated"
  - "Endpoints test seeds distinct old/fresh models (gpt-4-turbo vs gpt-4o, glm-5.3-flash vs glm-5.3) so each endpoint's exclusion is observable; off_peak_share deliberately unasserted (depends on wall-clock peak window)"
  - "requirements-completed left empty and REQUIREMENTS.md untouched, honoring 02-01's recorded decision: 02-03 carries [ANLT-01, ANLT-02] in its frontmatter and owns the final mark-complete"

patterns-established:
  - "Pattern: deadline wakeup + salvage inside a consumer loop (02-RESEARCH Pattern 2 verbatim) — scheduler surgery around a byte-identical record path"
  - "Pattern: integration proof of non-blocking under concurrency = Phase-1 burst recipe + swapped app.state writer with a tiny injected interval (deterministic levers 0.03s tick / 0.005s per-write lag, never real-cadence waits)"

requirements-completed: []  # deferred to 02-03 per the cross-plan decision recorded in 02-01's key-decisions (ANLT-02's docs land there)

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "Periodic purge tick: interval 0.05s → purges_run >= 2 in a bounded 0.25s wait; a row seeded AFTER startup is deleted by a later pass (deadline wakeup fires repeatedly, no scheduler dependency)"
    requirement: ANLT-02
    verification:
      - kind: unit
        ref: tests/test_analytics_retention.py#test_periodic_tick_purges_reseeded_expired_rows
        status: pass
  - id: D2
    description: "Lifespan request-readiness never awaits a purge: with purge_expired gated on a never-set Event the lifespan reaches its yield (entered-Event within 2s) while the purge has started (>=1) and not returned (==0); NFR-04 at startup"
    requirement: ANLT-02
    verification:
      - kind: unit
        ref: tests/test_analytics_retention.py#test_startup_purge_does_not_block_lifespan_readiness
        status: pass
  - id: D3
    description: "Mid-purge enqueue drain: 2500 expired rows in the startup purge + 30 fresh records enqueued synchronously at start → dropped == 0, exactly the 30 rows persisted, queue empties (between_batches hook fires 3x for 2500 rows at batch 1000)"
    requirement: ANLT-02
    verification:
      - kind: unit
        ref: tests/test_analytics_retention.py#test_interleave_queue_drained_between_purge_batches (+ test_purge_between_batches_hook_awaited_per_batch)
        status: pass
  - id: D4
    description: "All four analytics endpoints (summary/models/requests/credits) serve ONLY retained data after a purge — totals, model rows, request ids exclude purged rows; fresh zai row aggregates correctly inside the 5h/7d windows"
    requirement: ANLT-02
    verification:
      - kind: integration
        ref: tests/test_analytics_retention.py#test_endpoints_serve_retained_data_after_purge
        status: pass
  - id: D5
    description: "Streaming never blocked during purge: 20 concurrent streams over a 0.03s-tick writer with 1500 expired rows — full token sequences + [DONE] on every stream (sorted multiset equality), exactly-once rows, dropped == 0, purges interleaved (purges_run >= 2)"
    requirement: ANLT-02
    verification:
      - kind: integration
        ref: tests/test_analytics_retention.py#test_burst_streams_unblocked_during_purge
        status: pass

# Metrics
duration: 10min
completed: 2026-09-08
status: complete
---

# Phase 02 Plan 2: Periodic Purge Scheduling + Integration Proofs Summary

**6h deadline-scheduled purge tick riding the existing AnalyticsWriter consumer loop (wait_for wakeup + lossless get_nowait salvage, no drift), inter-batch queue drain keeping fire-and-forget lossless mid-purge, and both ANLT-02 integration contracts proven: four endpoints serve retained data post-purge, 20 concurrent streams complete unblocked with purges interleaving**

## Performance

- **Duration:** 10 min (07:46:54Z → 07:57:18Z)
- **Started:** 2026-09-08T07:46:54Z
- **Completed:** 2026-09-08T07:57:18Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- The 6-hour purge tick is scheduler surgery around a byte-identical Phase-1 record path: `_run()` now computes `timeout = max(0.0, next_purge - loop.time())`, awaits `asyncio.wait_for(self._queue.get(), timeout=timeout)`, salvages a raced item via `get_nowait()` on TimeoutError (cancellation-safe per probe R3e), and recomputes `next_purge` after each purge so ticks never drift — one task still owns both the record path and the tick (locked: no new scheduler)
- Mid-purge records are lossless by construction: `purge_expired` gained a keyword-only `between_batches` hook awaited after every per-batch commit (including the final partial batch), and the writer passes `self._drain_queued` — a burst during a long purge persists in the batch gaps instead of filling the 1000-cap and dropping (Pitfall 3 / T-02-06)
- Interval is a module constant (`_PURGE_INTERVAL_S = 21600.0`), constructor-injectable as the test seam — the locked env surface still gains only `ANALYTICS_RETENTION_DAYS` (T-02-07 no-new-knob honored)
- Six proofs landed on top of 02-01's seven: periodic tick (reseeded row removed by a later pass), lifespan no-block under a gated purge, interleave drain, per-batch hook count, endpoints-post-purge (all four routes, credits windows included), burst-during-purge (20 streams, exactly-once, zero drops, purges interleaved)
- Full suite 116 passed (110 baseline + 6 new), zero new dependencies; the retention module is 13/13 stable across repeated runs

## Task Commits

Each task was committed atomically:

1. **Task 1: 6h deadline tick + inter-batch drain + no-block proof** - `e770c59` (feat)
2. **Task 2: Integration proofs (endpoints post-purge, burst during purge)** - `84cd932` (test)

## Files Created/Modified
- `analytics/writer.py` - `_PURGE_INTERVAL_S` module constant; `purge_interval_s` ctor kwarg; `_drain_queued()`; `_purge()` passes `between_batches`; `_run()` deadline-wakeup rewrite (Phase-1 record path byte-identical)
- `analytics/db.py` - `purge_expired` keyword-only `between_batches: Callable[[], Awaitable[None]] | None = None`, awaited after each per-batch commit; everything else exactly as 02-01 landed it
- `tests/conftest.py` - new `analytics_retention_writer` fixture (queue 1000, retention 90, tick 0.05s); existing fixtures untouched (default shape preserved verbatim)
- `tests/test_analytics_retention.py` - 6 new tests (4 scheduling + 2 integration), module total 13

## Decisions Made
- RED discipline documented honestly: 3 of 4 Task-1 tests RED'd per plan (missing fixture, ctor TypeError, hook TypeError); the no-block test passed pre-implementation by design — it pins the 02-01 guarantee that must survive the rewrite
- Burst-test tick assert restructured into a bounded in-try poll (see key-decisions) — the first version asserted after `finally: stop()` cancelled the consumer and failed at `purges_run == 1`; delivery/rows/dropped asserts were green throughout
- Distinct old/fresh models in the endpoints test so each route's exclusion is independently observable; `off_peak_share` unasserted (wall-clock peak window dependency)
- REQUIREMENTS.md untouched — 02-03 owns the final mark-complete per the recorded cross-plan decision
- Otherwise followed plan as written (02-RESEARCH Pattern 2 mechanics implemented verbatim)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - test timing] burst test's purges_run assert raced the consumer's shutdown**
- **Found during:** Task 2 (first GREEN run)
- **Issue:** the test asserted `ticking.purges_run >= 2` after the `finally` block had already called `ticking.stop()` (cancelling the consumer before the first tick deadline); additionally `wait_drained` can return mid-purge because the between-batches hook empties the queue before the pass ends — so the tick legitimately had not fired yet (`purges_run == 1`)
- **Fix:** bounded 2s poll for `purges_run >= 2` moved inside the try block (before stop) — the tick fires within one 0.03s interval of the purge pass ending; still never a wall-clock-sized wait
- **Files modified:** tests/test_analytics_retention.py
- **Verification:** 2 passed (endpoints + burst); module 13/13 across 3 repeated runs; full suite 116 passed
- **Committed in:** 84cd932 (Task 2 commit)

**2. [Rule 1 - edit tooling] two edit calls duplicated replaced regions mid-implementation**
- **Found during:** Task 1 (db.py docstring block, writer.py __init__ block)
- **Issue:** range-based PUTs left the tail of the replaced bodies in place (duplicated docstring lines / duplicated ctor body), temporarily breaking parses
- **Fix:** immediately re-read each region and CUT the duplicated lines; `ast.parse` verified both files before any test run
- **Files modified:** none beyond the planned surfaces (analytics/db.py, analytics/writer.py)
- **Verification:** db.py/writer.py parse clean; all source gates pass
- **Committed in:** e770c59 (Task 1 commit)

---

**Total deviations:** 2 (both Rule 1, both test/edit-tooling level — no production semantics changed beyond the plan)
**Impact on plan:** All fixes preserve locked semantics and Phase-1 contracts; no scope creep.

## Issues Encountered
- None beyond deviation 1 — the deadline/salvage/drain mechanics worked first try against the probe-verified Pattern 2 prototype, as the plan predicted ("assembly, not invention")

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 02-03 ready: the full purge lifecycle (knob → startup purge → 6h tick → drain) is code-complete and proven; 02-03 documents the env surface (`.env.example`, README env table + first-startup-purge note, AGENTS.md analytics section + one-time VACUUM migration note) and carries [ANLT-01, ANLT-02] to REQUIREMENTS.md completion
- No stubs, no skipped tests, no unrun verifications

## Self-Check: PASSED

- All 4 modified files exist on disk (checked with `[ -f ]`)
- Both task commits found in history (e770c59, 84cd932)
- Full suite: 116 passed; test_analytics_retention.py 13/13 (4 scheduling + 2 integration new); Phase-1 regression set (writer/endpoints/chat) 32/32
- Source gates re-verified: ctor signature ['self','db','queue_size','retention_days','purge_interval_s'] + _PURGE_INTERVAL_S == 21600.0; wait_for(get()) count 1; get_nowait count 2; between_batches wiring 1 (writer) / 4 (db); task_done count 3; every log_request call inside try/except Exception (AST); analytics_retention_writer fixture present; default fixture construction unchanged (count 1); ANALYTICS_PURGE absent from writer/config (no new env knob)
- Timing-sensitive module stable across 3 repeated runs (13/13 each)

---
*Phase: 02-analytics-retention-storage-lifecycle*
*Completed: 2026-09-08*
