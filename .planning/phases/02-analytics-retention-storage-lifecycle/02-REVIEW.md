---
phase: 02-analytics-retention-storage-lifecycle
reviewed: 2026-09-08T08:16:20Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - config.py
  - analytics/db.py
  - analytics/writer.py
  - main.py
  - tests/conftest.py
  - tests/test_analytics_retention.py
  - tests/test_analytics_writer.py
  - tests/test_startup_validation.py
  - .env.example
  - README.md
  - AGENTS.md
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: findings
fixed: []
---

# Phase 02: Code Review Report

**Reviewed:** 2026-09-08T08:16:20Z
**Depth:** deep (per-file + cross-file call-chain tracing: lifespan → writer loop → purge loop → aiosqlite; config → writer; tests → fixtures)
**Diff base:** `225a301` (commit before `9577430`) .. `ce0a6a7` (HEAD)
**Files Reviewed:** 11
**Status:** findings

## Summary

The retention lifecycle is implemented well and matches every locked decision in
`02-CONTEXT.md`: the `ANALYTICS_RETENTION_DAYS` knob (default 90, `0` = keep-forever
opt-out, negative rejected at import naming the env var), startup purge as the writer
task's first action plus a 6h `_PURGE_INTERVAL_S` tick in the same consumer task (no new
scheduler), batched `DELETE` via rowid-subquery `LIMIT` with per-batch commits, a guarded
`incremental_vacuum` loop, `auto_vacuum=INCREMENTAL` at initialize (legacy no-op logged,
one-time `VACUUM` migration documented in README/AGENTS), and docs updated accurately.

Focus areas verified against the dispatch asks:

- **Batched DELETE loop termination** — terminates for every `batch >= 1`: each iteration
  deletes up to `batch` expired rows; `between_batches` only persists *fresh* rows
  (`created_at=now`), so expired rows monotonically deplete and `cur.rowcount < batch`
  eventually breaks. Multi-batch (2500 rows → 3 batches) and idempotency (second pass
  deletes 0) are pinned by tests. **One latent exception: `batch < 1` never terminates
  (WR-01, repro-confirmed) — unreachable from production wiring today.**
- **Guarded `incremental_vacuum` loop** — correctly bounded: `range(last_free * 2 + 16)`
  hard cap plus the `free == 0 or free >= last_free` break, so both a drained freelist and
  a stalled legacy `auto_vacuum=0` file terminate. Pinned by the legacy-DB test (bounded
  `wait_for`, 10s).
- **Cutoff/boundary timezone math** — cutoff and all stored `created_at` values come from
  the same producer format (`datetime.now(timezone.utc).isoformat()`, always `+00:00`;
  verified identical in the pre-phase code at the diff base), so lexicographic comparison
  is order-correct including the microsecond-presence edge (`…T12:00:00+00:00` sorts
  before `…T12:00:00.000001+00:00`). Strict `<` semantics (exact-cutoff row retained) are
  documented in the docstring and pinned by the boundary-trio test (1µs-older purged /
  exact retained / fresh retained). A suspected naive-`now` hazard was **disproved by
  repro** (naive cutoff still purges correctly — no finding).
- **Writer-loop tick losing queue items** — the `wait_for(queue.get(), timeout)` race is
  sound on this interpreter: `Queue.get` removes the item only in the synchronous
  `get_nowait()` tail after the awaited getter resolves (no cancellation point between),
  and `wait_for` returns a completed result rather than dropping it; the salvage
  `get_nowait()` after `TimeoutError` is belt-and-braces. Deadline wakeup
  (`timeout=max(0.0, …)`) cannot busy-spin — the overdue branch always runs a purge before
  re-arming. Exercises confirmed by 4 clean runs of the timing-heavy tests.
- **Concurrency: purge during active streaming** — writes and purges share the single
  aiosqlite connection only through the one consumer task (aiosqlite serializes statements
  in its worker thread; reads via the endpoints see committed batches). The 20-stream
  burst test proves streams complete with full token sequences + `[DONE]`, exactly-once
  rows, zero drops, `purges_run >= 2` interleaved; the gated-purge lifespan test proves
  request readiness never awaits a purge (NFR-04).
- **Security** — parameterized SQL only (cutoff/batch bound, never interpolated); pragma
  names are constants; no new endpoints or secrets; purge logging is count-only (pinned by
  the log-privacy test); `.env.example` addition mirrors the `Settings` field exactly.
- **Test quality** — the 13 new retention tests defend the real contract (boundary
  semantics, opt-out, multi-batch + idempotency, space reclamation via
  `page_count`/`freelist_count`, legacy-guard termination, log privacy, periodicity,
  readiness non-blocking, mid-purge queue drain, hook-per-batch count, endpoint
  correctness post-purge, burst non-blocking), not implementation plumbing. Two
  robustness nits on the tests themselves (IN-01, IN-02).

**Scope note:** `tests/test_analytics_endpoints.py` was listed in the dispatch but is
unchanged in `225a301..HEAD`; it was read for cross-reference only.

## Critical Issues

None.

## Warnings

### WR-01: `purge_expired` never terminates when `batch < 1` — consumer task spins forever

**File:** `analytics/db.py:126,144-159`
**Issue:** The DELETE loop's only exit is `if cur.rowcount < batch: break` (line 158).
With `batch=0`, `DELETE … LIMIT 0` deletes 0 rows and `0 < 0` is false → infinite loop.
With a negative `batch`, SQLite treats `LIMIT -1` as *unlimited* (first pass deletes
everything, then `0 < -1` is false) → same infinite loop. Repro-confirmed: with 5 expired
rows, `await asyncio.wait_for(db.purge_expired(90, batch=0), timeout=2.0)` times out —
the loop never exits. Because purges run inside the single `AnalyticsWriter` consumer
task, a hung purge silently stops *all* analytics writes while the loop spins on the one
shared connection — precisely the failure mode this phase exists to prevent.
Not Critical only because no production caller passes `batch` (the writer uses the
`_PURGE_BATCH=1000` default; the parameter exists for test injection), so it is
unreachable in the shipped wiring today. The codebase already guards the identical hazard
class on `AnalyticsWriter.__init__`'s `queue_size < 1` — this parameter deserves the same
treatment.
**Fix:**
```python
# analytics/db.py — alongside the existing retention guard (line 140)
if not self._db or retention_days <= 0:  # 0 = keep-forever opt-out
    return 0
if batch < 1:
    raise ValueError(
        f"batch must be >= 1 (got {batch}); 0/negative never terminates the DELETE loop"
    )
```

## Info

### IN-01: Interleave test asserts after a fixed 0.3s sleep instead of a bounded wait

**File:** `tests/test_analytics_retention.py:347`
**Issue:** `test_interleave_queue_drained_between_purge_batches` sleeps a fixed 0.3s then
asserts `recent["total"] == 30`. On a loaded CI runner the 3-batch (2500-row) startup
purge could still be mid-flight, and since `get_recent` reads the same connection it
would see partial state → intermittent failure. The file's own convention elsewhere is a
5s bounded wait on `writer.last_purged` (used in this very test's siblings).
**Fix:** Replace the sleep with the bounded wait, then assert:
```python
deadline = time.monotonic() + 5.0
while writer.last_purged != 2500:
    if time.monotonic() >= deadline:
        pytest.fail("startup purge did not complete within 5s")
    await asyncio.sleep(0.01)
assert writer.dropped == 0
```

### IN-02: Burst test's `responses` is referenced after try/finally — a failed gather surfaces as `NameError`

**File:** `tests/test_analytics_retention.py:527,551`
**Issue:** `responses = await asyncio.gather(...)` is bound inside the `try` block; if any
request raises, the `finally` restores state and then line 551's
`assert all(r.status_code == 200 for r in responses)` raises `NameError: responses`,
masking the actual failure cause.
**Fix:** Initialize `responses = []` before the `try`, or move the gather's exception
path into an explicit `except` that `pytest.fail`s with the underlying error; simplest:
```python
responses = []
try:
    ...
    responses = await asyncio.gather(...)
finally:
    ...
```

## Verification (evidence)

- `.venv/bin/python -m pytest tests/test_analytics_retention.py tests/test_analytics_writer.py tests/test_startup_validation.py -q` → **43 passed** (2.02s)
- `tests/test_analytics_retention.py` re-run 3× (timing-heavy suite) → **13 passed each run** — no flakes observed
- WR-01 repro (scoped, timeout-guarded): `purge_expired(90, batch=0)` under `asyncio.wait_for(..., 2.0)` → `TimeoutError` — loop confirmed non-terminating
- Naive-`now` hypothesis repro: `purge_expired(90, now=naive_utc)` deleted 5/5 expired rows → suspected silent no-op **disproved**, no finding raised
- Legacy `created_at` format at diff base (`225a301`) verified identical (`datetime.now(timezone.utc).isoformat()`) → lexicographic cutoff comparison is format-consistent for pre-existing databases
- Review is read-only; no source files modified

## Requirements Coverage

| Requirement | Status | Evidence |
|---|---|---|
| ANLT-01 (bounded `request_logs` growth via TTL purge) | Met | `purge_expired` + startup/6h writer tick; boundary/opt-out/multi-batch/idempotency/reclaim tests; e2e test seeds a real pre-existing file DB (no manual SQL) |
| ANLT-02 (analytics stay accurate, fast, disk-bounded) | Met | Endpoints serve only retained data post-purge (all four); 20-stream burst unblocked during purge with exactly-once rows; readiness never awaits a purge; incremental-vacuum reclamation with `page_count` drop pinned |

---

_Reviewed: 2026-09-08T08:16:20Z_
_Reviewer: Claude (gsd-code-reviewer, Review-P2)_
_Depth: deep_
