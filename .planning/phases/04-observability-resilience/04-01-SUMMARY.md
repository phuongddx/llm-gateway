---
phase: 04-observability-resilience
plan: 01
subsystem: api
tags: [prometheus, metrics, health-check, observability, fastapi]

# Dependency graph
requires:
  - phase: 03-containerized-deployment-ci
    provides: Dockerfile HEALTHCHECK + docker-compose.yml (healthcheck repoint target), CI pytest gate this plan's tests now run under
provides:
  - GET /metrics — hand-rolled Prometheus v0.0.4 text exposition (gateway_requests_total counter, gateway_request_duration_seconds histogram), no prometheus_client dependency
  - GET /health/live + GET /health/ready — liveness/readiness split replacing the single GET /health (breaking rename, no back-compat alias)
  - Dockerfile HEALTHCHECK and Makefile health target repointed to /health/ready
affects: [future Phase-4 plans (per-key rate limiting, transient retry — same files main.py/routes/chat.py), optional Compose "prometheus" scrape profile, docs refresh (DOCS-01/02) that must drop the stale /health example]

# Actuals (#2632)
actuals:
  tokens: 3845
  tasks: 2
  commits: 3
  plan_head_before: d6c0781

# Tech tracking
tech-stack:
  added: []
  patterns: ["Hand-rolled Prometheus text-exposition module (metrics.py) with module-level dict/defaultdict counters, no locks — safe because uvicorn main:app runs single-process/single-event-loop", "Liveness/readiness split reading lifespan-owned app.state presence as the readiness signal, same getattr(request.app.state, ..., None) idiom already used in routes/chat.py"]

key-files:
  created: [metrics.py, tests/test_metrics.py]
  modified: [main.py, routes/chat.py, Dockerfile, Makefile, tests/test_chat_endpoint.py]

key-decisions:
  - "Task 1 followed RED-GREEN TDD discipline literally: wrote tests/test_metrics.py against a docstring-only metrics.py stub first (confirmed 6/6 target-assertion failures, not collection errors), committed as test(04-01), then restored the full implementation and confirmed 6/6 passes, committed as feat(04-01). No REFACTOR commit — the GREEN implementation needed no cleanup."
  - "Fixed a real correctness bug found via Task 2's boundary test: record_request() already stores a cumulative-per-bucket count (every bucket whose upper bound the duration satisfies gets incremented), but render() was re-summing those values into a running total across buckets — double-accumulating. A single 0.02s request rendered le=10.0 as 12 instead of 1, while +Inf/_count correctly showed 1. Fixed by emitting the already-cumulative buckets[i] value directly in render(), no running sum."
  - "GET /metrics and GET /health/live intentionally carry zero auth dependency (standard Prometheus scrape convention + Docker HEALTHCHECK convention, matching how the old GET /health was also unauthenticated) — same trust boundary the plan's threat_model already accepted (T-04-01-01/02/03, all low severity, mitigated/accepted)."

patterns-established:
  - "Test isolation for module-level global state: tests/test_metrics.py uses an autouse fixture that clears metrics.py's internal counter/histogram dicts before every test via getattr(..., None) + .clear(), defensive against the dicts not existing yet (kept the RED phase's fixture from crashing before GREEN)."
  - "Testing absence-of-lifespan-state without a second client fixture: monkeypatch.delattr(app.state, \"analytics_db\"/\"analytics_writer\", raising=False) inside a test that also uses the existing `client` fixture, rather than building a second bare-state client fixture — the next test's client fixture reassigns both attributes fresh, so there is no cross-test leakage."

requirements-completed: [OBSV-01]

coverage:
  - id: D1
    description: "GET /metrics returns valid Prometheus v0.0.4 text exposition (gateway_requests_total counter + gateway_request_duration_seconds histogram with mandatory +Inf bucket) reflecting real chat traffic"
    requirement: "OBSV-01"
    verification:
      - kind: unit
        ref: "tests/test_metrics.py#test_render_empty_state_has_only_help_type_lines"
        status: pass
      - kind: unit
        ref: "tests/test_metrics.py#test_render_after_record_request_includes_counter_and_histogram_samples"
        status: pass
      - kind: integration
        ref: "tests/test_metrics.py#test_metrics_endpoint_returns_prometheus_text"
        status: pass
      - kind: integration
        ref: "tests/test_metrics.py#test_chat_request_is_recorded_in_metrics"
        status: pass
    human_judgment: false
  - id: D2
    description: "GET /health/live always returns 200 with zero dependency on analytics/DB state; GET /health/ready returns 503 until analytics_db + analytics_writer are both present, 200 once they are; old GET /health no longer exists"
    requirement: "OBSV-01"
    verification:
      - kind: integration
        ref: "tests/test_metrics.py#test_health_live_returns_ok"
        status: pass
      - kind: integration
        ref: "tests/test_metrics.py#test_health_ready_returns_ready_when_state_present"
        status: pass
      - kind: integration
        ref: "tests/test_metrics.py#test_health_ready_returns_503_when_state_absent"
        status: pass
    human_judgment: false
  - id: D3
    description: "Histogram bucket boundary semantics correct (le=upper inclusive, one step above excluded from that bucket but present in the next) and concurrent record_request calls under asyncio.gather never lose increments"
    requirement: "OBSV-01"
    verification:
      - kind: unit
        ref: "tests/test_metrics.py#test_bucket_boundary_inclusive_at_upper_exclusive_one_step_above"
        status: pass
      - kind: unit
        ref: "tests/test_metrics.py#test_record_request_concurrent_calls_lose_no_increments"
        status: pass
    human_judgment: false
  - id: D4
    description: "Metrics labels never leak prompt/message content, API keys, or per-user identifiers — only provider/model/status labels and counts/latencies (T-04-01-01 mitigation)"
    requirement: "OBSV-01"
    verification:
      - kind: integration
        ref: "tests/test_metrics.py#test_metrics_never_leaks_error_message_content"
        status: pass
    human_judgment: false
  - id: D5
    description: "Dockerfile HEALTHCHECK and Makefile health target repointed to /health/ready"
    requirement: "OBSV-01"
    verification:
      - kind: other
        ref: "Dockerfile line 30, Makefile line 30 — both curl/urlopen '/health/ready'"
        status: pass
    human_judgment: false

duration: ~40min
completed: 2026-09-08
status: complete
---

# Phase 4 Plan 1: Prometheus Metrics + Health Split Summary

**Hand-rolled `/metrics` Prometheus v0.0.4 exposition (request counter + latency histogram) and a `/health/live`+`/health/ready` split replacing the old single `/health` route, with a real double-cumulative histogram bug caught and fixed by the plan's own boundary test.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-09-08
- **Completed:** 2026-09-08
- **Tasks:** 2/2
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments
- `metrics.py` (new): module-level counters/histogram, no locks, no I/O — `record_request()` + `render()` producing valid Prometheus text-exposition v0.0.4
- `main.py`: `GET /health` replaced by `GET /metrics`, `GET /health/live`, `GET /health/ready` in the same pre-router-mount block
- `routes/chat.py`'s `_tracked_stream` now calls `metrics.record_request()` alongside the existing analytics-writer enqueue, reusing the same latency/status values (no new measurement point)
- `Dockerfile` HEALTHCHECK and `Makefile`'s `health` target repointed to `/health/ready`
- `tests/test_metrics.py` (new, 10 tests): metric shape, health-live, health-ready (both states), bucket boundary (both sides), concurrency, no-content-leak prohibition
- `tests/test_chat_endpoint.py`: stale `test_health_endpoint` removed (asserted the now-404 `/health` route)
- Found and fixed a real double-cumulative histogram bug in `render()` via the boundary test (see Deviations)

## Task Commits

Task 1 (TDD: RED → GREEN, no REFACTOR needed):
1. **RED: failing test for /metrics + health split** - `775cef9` (test)
2. **GREEN: wire /metrics + /health/live + /health/ready end-to-end** - `f0eeb79` (feat)

Task 2:
3. **Remove stale /health test; add boundary/concurrency/no-leak coverage (incl. histogram bug fix)** - `6ec9b07` (test)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP update)

## Files Created/Modified
- `metrics.py` - in-process Prometheus text-exposition metrics module (counters, histogram, `render()`)
- `main.py` - `GET /metrics`, `GET /health/live`, `GET /health/ready` (replaces `GET /health`); adds `Request`/`Response` to the FastAPI import, `import metrics as gateway_metrics`
- `routes/chat.py` - `import metrics`; `_tracked_stream`'s `finally` block computes `status` once and calls `metrics.record_request(provider_name, model_id, status, latency_ms / 1000.0)`, reusing `status` for the analytics enqueue too (was previously duplicated inline)
- `Dockerfile` - `HEALTHCHECK CMD` URL: `/health` → `/health/ready`
- `Makefile` - `health:` target `curl` URL: `/health` → `/health/ready`
- `tests/test_metrics.py` - 10 tests covering OBSV-01's must_haves, edge cases, and prohibition
- `tests/test_chat_endpoint.py` - `test_health_endpoint` removed

## Decisions Made
- Followed the task's `tdd="true"` attribute literally: wrote the test file against a docstring-only `metrics.py` stub, confirmed genuine RED (6 target-assertion failures, zero collection errors), committed, then restored the implementation and confirmed GREEN before committing — see `key-decisions` in frontmatter for the exact mechanics.
- Reused the `status` variable computed for `metrics.record_request()` in the analytics-writer's enqueue dict too, removing a duplicated inline `"error" if error_msg else "success"` expression — small DRY cleanup, no behavior change.
- No `rate_limit_per_key`/retry/tenacity work in this plan — that is Phase 4's other two requirements (OBSV-02/03), out of scope for 04-01 per its own frontmatter (`files_modified` lists only the metrics+health surface).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Histogram render() double-accumulated bucket counts**
- **Found during:** Task 2's boundary test (`test_bucket_boundary_inclusive_at_upper_exclusive_one_step_above`), while implementing the boundary edge-case coverage the plan's own `must_haves.edge_cases` required
- **Issue:** `record_request()` already increments every bucket whose upper bound the duration satisfies (i.e. `buckets[i]` is already the correct cumulative `le=upper` count per Prometheus semantics), but `render()` additionally ran a second cumulative sum across buckets when emitting them — double-counting. Reproduced manually: a single `record_request(..., 0.02)` call rendered `le="10.0"` as `12` while `+Inf`/`_count` correctly showed `1` — a self-contradictory histogram that would have broken any real Prometheus query (`histogram_quantile`, rate-of-buckets) reading this endpoint.
- **Fix:** `render()` now emits `buckets[i]` directly for each `le=` line instead of re-summing it into a running `cumulative` variable.
- **Files modified:** `metrics.py`
- **Verification:** Manual repro (`.venv/bin/python -c "..."`) before/after showing the corrected output (every bucket ≥ the recorded duration now shows the true count, matching `+Inf`); `tests/test_metrics.py::test_bucket_boundary_inclusive_at_upper_exclusive_one_step_above` and `test_render_after_record_request_includes_counter_and_histogram_samples` both pass; full suite 126/126.
- **Committed in:** `6ec9b07` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 correctness bug)
**Impact on plan:** The fix was strictly necessary — the plan's own must_haves/edge_cases explicitly required correct histogram bucket semantics, and the bug would have shipped a Prometheus endpoint whose bucket values were provably wrong under multi-bucket traversal. Caught before merge by the plan's own mandated boundary test, not discovered later. No scope creep — same file, same function, no new surface.

## Issues Encountered
None beyond the histogram bug documented above, which was found and fixed within the plan's own verification loop.

## User Setup Required
None — no external service configuration required. `/metrics` requires no new environment variables; the optional Compose "prometheus" scrape profile mentioned in RESEARCH.md was not part of this plan's scope (not in `files_modified`) and remains available for a future plan to add.

## Next Phase Readiness
- OBSV-01 fully satisfied: `/metrics`, `/health/live`, `/health/ready` all live, tested, and wired into the same measurement point analytics already uses.
- Dockerfile/Makefile/Compose healthcheck chain now points end-to-end at `/health/ready` — Phase 3's container healthcheck will correctly gate on analytics-DB readiness, not just process-up.
- Phase 4's remaining plans (OBSV-02 per-key rate limiting, OBSV-03 same-provider retry) touch the same `routes/chat.py`/`providers/openai_compatible_base.py` files — no conflicts expected since this plan didn't touch the rate-limiter or provider retry paths at all.
- `AGENTS.md` still documents the old `GET /health` example (`make health` section, single test-file example) — stale after this plan; flagged here for the Phase-5 DOCS-01/02 refresh rather than fixed now (out of `files_modified` scope for 04-01).

---
*Phase: 04-observability-resilience*
*Completed: 2026-09-08*
