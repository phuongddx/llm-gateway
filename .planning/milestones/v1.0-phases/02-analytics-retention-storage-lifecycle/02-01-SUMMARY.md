---
phase: 02-analytics-retention-storage-lifecycle
plan: 1
subsystem: database
tags: [sqlite, aiosqlite, retention, ttl, purge, incremental-vacuum, auto_vacuum, pydantic-settings, fastapi-lifespan, pytest-asyncio]

# Dependency graph
requires:
  - phase: 01-gateway-runtime-hardening
    provides: "01-01's bounded AnalyticsWriter consumer loop + lifespan wiring, and Phase-0's AnalyticsDB schema with idx_logs_created_at — the surfaces this plan extends"
provides:
  - Settings.analytics_retention_days knob (default 90, 0 = keep-forever opt-out, >=0 import-time validator naming ANALYTICS_RETENTION_DAYS)
  - AnalyticsDB.purge_expired — strict-cutoff batched rowid-subquery DELETE (per-batch commit, _PURGE_BATCH=1000), guarded incremental_vacuum loop, wal_checkpoint(PASSIVE), count-only log
  - initialize() sets PRAGMA auto_vacuum=INCREMENTAL strictly before schema creation + informational legacy-DB notice
  - AnalyticsWriter retention_days kwarg + purges_run/last_purged public observables + contained _purge() as the consumer task's first action (startup purge)
  - main.py lifespan passes retention_days=settings.analytics_retention_days
  - tests/test_analytics_retention.py — tracer + six storage-tier proofs (boundary trio, opt-out, multi-batch, reclaim, legacy guard, log privacy)
affects: [02-02 (6h tick + inter-batch drain rides these surfaces), 02-03 (documents the knob + VACUUM note), verify-work UAT Phase 2]

# Actuals (#2632) — same estimateTokens scale (chars/4 over the realized diff), never a harness count.
actuals:
  tokens: 5383    # git diff 21530 chars / 4 (estimate was 30000 — plan over-estimated ~5.6x)
  tasks: 3
  commits: 3      # MEASURED: git rev-list --count 225a301..HEAD (ledger gsd-plan-head-before-02-01)

# Tech tracking
tech-stack:
  added: []       # zero new deps (REQ-NFR-02 honored)
  patterns:
    - "Batched purge via DELETE ... WHERE rowid IN (SELECT rowid ... WHERE created_at < ? LIMIT ?) — no DELETE...LIMIT on this SQLite build; covering-index plan, exact rowcount, per-batch commit"
    - "Guarded incremental_vacuum loop (break at freelist 0 / no-decrease; hard bound freelist*2+16) — this build moves exactly one page per call; unguarded loops spin forever on legacy auto_vacuum=0 files"
    - "PRAGMA auto_vacuum=INCREMENTAL strictly before executescript(_SCHEMA) — silently rejected after tables exist; read-only files raise, contained so write_probe keeps owning the curated abort"
    - "Startup purge as the consumer task's first action — lifespan stays instant (NFR-04); purges_run incremented at entry so bounded waits survive a raising purge"
    - "Count-only purge logging (%d rows + TTL) — row ids/models never logged (privacy prohibition, caplog-asserted)"

key-files:
  created:
    - tests/test_analytics_retention.py
  modified:
    - config.py
    - analytics/db.py
    - analytics/writer.py
    - main.py
    - tests/test_startup_validation.py
    - tests/test_analytics_writer.py

key-decisions:
  - "Read-only DB files reject the auto_vacuum header write with OperationalError — contained in initialize() (try/except sqlite3.OperationalError, mirroring the credits migration posture) so write_probe() keeps owning the curated ANALYTICS_DB_PATH abort (Phase-1 contract)"
  - "Gated-writer scheduling test waits out the startup purge (bounded loop on last_purged) before enqueueing — the consumer's first action changed from queue.get() to _purge(), so the pre/post-yield qsize states are observed from a parked consumer; gate/exactly-once invariants unchanged"
  - "Log-privacy test uses caplog.at_level (repo convention) — caplog.set_level as context manager was removed in pytest 9"
  - "Retention validator tests live in tests/test_startup_validation.py beside the queue-size pair — resolves the 02-PATTERNS placement discrepancy in favor of repo convention (tests/test_config.py holds only key-resolution tests)"
  - "requirements-completed left empty and REQUIREMENTS.md not touched: ANLT-01's 'documented default' lands in 02-03 and ANLT-02's periodic purge + endpoint proofs land in 02-02 — 02-03-PLAN.md carries [ANLT-01, ANLT-02] in its frontmatter and owns the final mark-complete"

patterns-established:
  - "Pattern: probe-verified SQL mechanics (02-RESEARCH Patterns 1/3) implemented verbatim — rowid-IN batching, guarded vacuum loop, pragma-before-schema, boundary-seeding recipe"

requirements-completed: []  # deliberately deferred — see key-decisions; 02-03 carries [ANLT-01, ANLT-02] to completion

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "ANALYTICS_RETENTION_DAYS knob: Settings field (default 90), 0 = keep-forever opt-out, negative rejected at construction naming the env var, non-integer rejected by pydantic, env-var mapping"
    requirement: ANLT-01
    verification:
      - kind: unit
        ref: tests/test_startup_validation.py#test_analytics_retention_days_default_is_90 (+3 siblings; 4 passed via -k retention)
        status: pass
  - id: D2
    description: "AnalyticsDB.purge_expired: strict-cutoff boundary semantics (at-cutoff retained, 1µs-older purged), 0-opt-out, multi-batch termination + idempotence, space reclamation (freelist→0, page_count drops on fresh INCREMENTAL file), legacy auto_vacuum=0 bounded termination, count-only logging"
    requirement: ANLT-02
    verification:
      - kind: unit
        ref: tests/test_analytics_retention.py#test_purge_expired_boundary_trio_exact_cutoff_retained (+5 siblings; 7 passed)
        status: pass
  - id: D3
    description: "End-to-end tracer: one real lifespan startup with retention 90 purges a pre-seeded expired row from an existing DB file, retains the fresh row, reports last_purged == 1"
    requirement: ANLT-02
    verification:
      - kind: integration
        ref: tests/test_analytics_retention.py#test_lifespan_startup_purge_removes_expired_rows_end_to_end
        status: pass

# Metrics
duration: 18min
completed: 2026-09-08
status: complete
---

# Phase 02 Plan 1: Retention Tracer Summary

**TTL retention knob (Settings → lifespan → writer-first-action startup purge) with batched rowid-subquery DELETE, guarded incremental_vacuum reclamation, and pragma-before-schema auto_vacuum — proven end-to-end through one real lifespan startup**

## Performance

- **Duration:** 18 min (07:22:01Z → 07:40:26Z)
- **Started:** 2026-09-08T07:22:01Z
- **Completed:** 2026-09-08T07:40:26Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- Operator TTL flows end-to-end: `Settings.analytics_retention_days` validated at import (>=0, 0 = keep-forever opt-out, env-var-named ValidationError) → `main.py` passes it to `AnalyticsWriter` → the consumer task's **first action** runs the startup purge → `AnalyticsDB.purge_expired` deletes strictly-older rows from existing DB files with no manual SQL
- Purge mechanics exactly per the probe-verified research: batched `rowid IN (SELECT ... LIMIT ?)` DELETE with per-batch commit (`_PURGE_BATCH=1000`), guarded `incremental_vacuum` loop, `wal_checkpoint(PASSIVE)`, count-only info log
- Space reclamation wired: `PRAGMA auto_vacuum=INCREMENTAL` strictly before `executescript(_SCHEMA)` (fresh files report 2), informational notice on legacy files, README one-time-VACUUM note deferred to 02-03 as planned
- Phase-1 write path byte-identical (record path untouched); full suite 110 passed (99 baseline + 11 new), zero new dependencies

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end retention tracer** - `9577430` (feat)
2. **Task 2: ANLT-01 validator coverage** - `904d926` (test)
3. **Task 3: Purge-correctness unit proofs** - `234e247` (test)

## Files Created/Modified
- `config.py` - `analytics_retention_days: int = 90` field + `_validate_analytics_retention_days` model_validator (message names ANALYTICS_RETENTION_DAYS)
- `analytics/db.py` - `_PURGE_BATCH=1000`; `initialize()` pragma ordering + readonly containment + legacy notice; `purge_expired(retention_days, batch=_PURGE_BATCH, *, now=None) -> int`
- `analytics/writer.py` - `retention_days` kwarg; `purges_run`/`last_purged` observables; contained `_purge()`; `_run()` starts with the startup purge
- `main.py` - lifespan passes `retention_days=settings.analytics_retention_days`
- `tests/test_analytics_retention.py` - NEW: tracer + 6 storage-tier proofs (7 tests)
- `tests/test_startup_validation.py` - 4 retention validator tests
- `tests/test_analytics_writer.py` - gated test waits out the startup purge (deviation 2)

## Decisions Made
- Read-only DB containment, gated-test wait-out, caplog.at_level, validator-test placement, requirements deferral — all in frontmatter key-decisions; otherwise followed plan as written (02-RESEARCH Patterns 1/3 implemented verbatim)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] auto_vacuum pragma breaks the read-only-DB abort contract**
- **Found during:** Task 1 (full-suite verification)
- **Issue:** `PRAGMA auto_vacuum=INCREMENTAL` attempts a header write on a chmod-444 pre-seeded DB file → raw `OperationalError` escaped `initialize()` instead of the curated `write_probe()` RuntimeError (broke `test_readonly_analytics_db_file_aborts_at_write_probe`); the escaped connection also leaked an aiosqlite thread that hung the first suite run at interpreter exit (300s timeout, "attempt to write a readonly database")
- **Fix:** wrap the pragma in `try/except sqlite3.OperationalError: pass` (mirrors the existing credits-migration posture); write_probe() again owns the curated abort
- **Files modified:** analytics/db.py
- **Verification:** readonly test passes; full suite exits cleanly in <5s (110 passed)
- **Committed in:** 9577430 (Task 1 commit)

**2. [Rule 1 - Bug] startup purge shifts gated-writer test's scheduling assumption**
- **Found during:** Task 1 (full-suite verification)
- **Issue:** the plan makes `_purge()` the consumer's first action, so after one `sleep(0)` yield the consumer is still purging — `test_gated_writer_drains_exactly_once_after_release` asserted `qsize()==4` and got 5 (the test pinned "first yield = one record taken")
- **Fix:** the test waits out the startup purge (bounded 5s loop on the new `last_purged` observable — the exact purpose the plan gave it) before enqueueing; gate-blocks-drain and exactly-once-after-release invariants unchanged
- **Files modified:** tests/test_analytics_writer.py
- **Verification:** test passes; whole writer suite green
- **Committed in:** 9577430 (Task 1 commit)

**3. [Rule 1 - test tooling] caplog.set_level context-manager form removed in pytest 9**
- **Found during:** Task 3 (log-privacy test)
- **Issue:** `with caplog.set_level(...)` raises TypeError on pytest 9.0.3 (removed API)
- **Fix:** switched to the repo-convention `with caplog.at_level(logging.INFO, logger="analytics.db")` (same shape as tests/test_analytics_writer.py)
- **Files modified:** tests/test_analytics_retention.py
- **Verification:** test passes; privacy asserts (ids/model absent from caplog.text) green
- **Committed in:** 234e247 (Task 3 commit)

### Plan-criterion corrections

**4. [Task 1 AC defect] unsatisfiable source probe corrected to its intent**
- **Found during:** Task 1 acceptance-criteria run
- **Issue:** the criterion `assert 'DELETE FROM request_logs WHERE' not in src` cannot hold — the plan's own mandated SQL (action 2c / 02-RESEARCH Pattern 1: `DELETE FROM request_logs WHERE rowid IN (SELECT ...)`) necessarily contains that substring
- **Fix:** ran the corrected probe `assert 'DELETE FROM request_logs WHERE created_at' not in src` (asserts the intent: only the rowid-subquery delete exists, no direct-predicate delete); the paired `src.count('rowid IN') == 1` passed as written
- **Files modified:** none (verification-side correction only)
- **Verification:** both probes exit 0 against the implementation

---

**Total deviations:** 4 (2 Rule 1 production/test fixes, 1 Rule 1 test-tooling fix, 1 criterion correction)
**Impact on plan:** All fixes preserve locked semantics and Phase-1 contracts; no scope creep.

## Issues Encountered
- First full-suite run reported "2 failed, 98 passed" then hung 300s at exit — root cause was deviation 1's leaked aiosqlite connection (its thread blocks interpreter exit when the owning event loop is gone); fixed with deviation 1, suite now exits in <5s
- RED→GREEN discipline held: the tracer test failed pre-implementation with the planned `AttributeError: ... analytics_retention_days` wiring failure

## User Setup Required
None - no external service configuration required. (Operator-facing consequence — with the default 90, the first startup purges pre-existing rows older than 90 days — is documented by 02-03, per the plan.)

## Next Phase Readiness
- 02-02 ready: `purge_expired`, `_purge()`, `last_purged`/`purges_run`, and the test module are in place for the 6h deadline tick, inter-batch drain, and burst-during-purge proofs; `_run()` currently has the plain `await get()` loop (tick lands there)
- 02-03 ready: knob semantics frozen (default 90, 0 = off, env var name pinned in validator + tests) for `.env.example`/README/AGENTS.md docs
- REQUIREMENTS.md intentionally untouched: ANLT-01 needs its documented default (02-03) and ANLT-02 its periodic purge + endpoint proofs (02-02); 02-03 carries [ANLT-01, ANLT-02] and owns mark-complete

## Self-Check: PASSED

- All 7 created/modified files exist on disk (checked with `[ -f ]`)
- All 3 task commits found in history (9577430, 904d926, 234e247)
- Full suite: 110 passed; test_analytics_retention.py 7/7; test_startup_validation.py 19/19 (4 retention)
- Source-level gates re-verified: pragma-before-schema, rowid-subquery-only delete, keyword-only now, main.py wiring count 1, purge-log count-only

---
*Phase: 02-analytics-retention-storage-lifecycle*
*Completed: 2026-09-08*
