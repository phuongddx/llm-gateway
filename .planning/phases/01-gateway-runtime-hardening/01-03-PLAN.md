---
phase: 01-gateway-runtime-hardening
plan: 3
type: execute
wave: 2
depends_on: ['01-PLAN-01-tracer-bounded-writer-error-frames']
files_modified:
  - tests/test_analytics_writer.py
autonomous: true
requirements:
  - RELI-02
estimate:
  tokens: 20000
  raw_tokens: 20000
  tasks: 2
  confidence: low

must_haves:
  truths:
    - 'TR1 (RELI-02a burst): 20 concurrent streams over one shared ASGI client with a deliberately slowed fake writer (per-write await asyncio.sleep(0.005), never time.sleep): every response returns 200 with its own full token stream and ends with the [DONE] frame; after wait_drained, get_recent reports total == 20 with 20 unique row ids; a sampler polling qsize() during the burst observes max(samples) <= cap (the locked bounded assertion).'
    - 'TR2 (RELI-02b drop-newest): cap-3 queue with no consumer and 57 enqueues → qsize() == 3, dropped == 54 (incoming records dropped, queued records never evicted), and exactly ONE warning logged at drop #50 (caplog).'
    - 'TR3 (RELI-02c gated drain): a writer blocked on an asyncio.Event gate, filled then released → every queued record drains exactly once to request_logs; stop() logs the drop total.'
    - 'TR4 (RELI-02d bounded stop): a writer stuck on a never-released gate: stop(timeout=0.5) returns within a bounded window and logs the timed-out drain with residue count; a healthy writer: stop() leaves qsize() == 0 with all rows persisted.'
    - 'TR5 (edge RELI-02/empty, explicit): stop() on a never-started or fully idle writer returns immediately without error; zero requests → zero rows; a single enqueued record → exactly one row.'
    - 'TR6 (edge RELI-02/adjacency, explicit): enqueue at exactly qsize() == maxsize drops only the incoming record; two records with identical payloads remain two distinct rows (uuid4 ids) — no merging, no deduplication on equal content.'
    - 'TR7 (edge RELI-02/concurrency, explicit): client disconnect mid-stream (direct generator aclose → GeneratorExit) still enqueues exactly one record — the finally-block runs exactly once per generator; concurrent producers each enqueue exactly once (20/20 unique in TR1).'
    - statement: 'Records are written FIFO by the single consumer task (asyncio.Queue get order into serial aiosqlite writes); request_logs has no monotonic sequence column (uuid4 PK, second-granularity created_at), so FIFO landing order is structurally guaranteed and deliberately not column-asserted.'
      verification: backstop
  artifacts:
    - tests/test_analytics_writer.py
  key_links:
    - 'burst test → conftest analytics_writer fixture over the shared analytics_db (ASGITransport never runs the lifespan — Plan 01 wiring)'
    - 'queue-unit tests → direct AnalyticsWriter construction with small caps over the shared analytics_db fixture (no HTTP layer, matching tests/test_analytics_db.py layering)'
    - 'disconnect test → routes.chat._tracked_stream called directly with a fake provider and the writer (module-level function — no HTTP needed)'
  prohibitions: []
---

<objective>
RELI-02 proof: deterministic pytest-asyncio verification of the bounded analytics write path that Plan 01 implemented. Implements the LOCKED CONTEXT decision "Concurrency Verification" exactly: a ~20-stream asyncio.gather burst with fake providers and an artificially slowed DB writer asserting full token delivery per client and exactly-once request_logs rows; separate unit tests for queue behavior (overfill → drop-newest + counter; unblock → drained rows + drop log); explicit qsize() <= cap sampling; dropped-writes visibility log-only this phase (Prometheus counter deferred to Phase 4 OBSV-01 — must NOT appear here).

Purpose: RELI-02 is a concurrency claim; only a deterministic test makes it verifiable per the locked decision (real-time sleeps banned — they block the event loop or flake CI; per-write await asyncio.sleep + gates are the probe-verified deterministic recipe, 01-RESEARCH.md Pitfall 12).

Output: tests/test_analytics_writer.py extended with the queue-unit suite and the burst suite; no production code changes (if a test exposes a Plan-01 defect, fix the production code in the same task — the tests are the spec).
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@.planning/phases/01-gateway-runtime-hardening/01-CONTEXT.md
@.planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md
@.planning/phases/01-gateway-runtime-hardening/01-PATTERNS.md
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Queue unit tests — drop-newest, gated drain, bounded stop, idle/single (RELI-02b/c/d)</name>
  <files>tests/test_analytics_writer.py</files>
  <read_first>
  - .planning/phases/01-gateway-runtime-hardening/01-CONTEXT.md — locked decision "Concurrency Verification" (unit/burst split) and "Bounded Analytics Write Path" (drop policy, log cadence)
  - .planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md — "Pattern 1" (probe-verified lifecycle numbers: cap 3 × 57 enqueues → qsize 3, dropped 54, exactly one warning at #50), Pitfalls 5/6/7/10/12, "Code Examples"
  - .planning/phases/01-gateway-runtime-hardening/01-PATTERNS.md — section "tests/test_analytics_writer.py" (record-builder helper, reuse of shared analytics_db fixture, no-HTTP layering)
  - analytics/writer.py (Plan-01 implementation: enqueue/qsize/wait_drained/start/stop/dropped)
  - analytics/db.py — get_recent query shape (tests/conftest.py fixture analytics_db)
  - tests/test_analytics_writer.py (Plan-01 tracer test — extend this file)
  </read_first>
  <behavior>
  - test_drop_newest_when_full_counts_and_logs_every_50: AnalyticsWriter(analytics_db, queue_size=3) NOT started; enqueue 57 records built by a _record(i) helper (the 12-key payload dict); assert qsize() == 3 and dropped == 54; caplog at WARNING contains exactly one "records dropped" record (fired at drop 50).
  - test_identical_payload_records_stay_distinct: enqueue two byte-identical record dicts (different id fields absent → same content except forced-distinct ids is NOT allowed — use truly identical dicts including id), start writer, wait_drained, assert 2 rows with 2 distinct ids (uuid4 PK proves adjacency non-merge).
  - test_gated_writer_drains_exactly_once_after_release: wrap analytics_db.log_request with an async wrapper awaiting an asyncio.Event gate then delegating; start writer; enqueue 5; assert qsize() stays 5 while gated (one brief yield); release gate; wait_drained; assert 5 unique rows via get_recent.
  - test_stop_bounded_on_stuck_writer_and_counts_residue: gated-forever writer, enqueue 2, await stop(timeout=0.5) → returns (measure elapsed < 2.0s), caplog contains the timed-out drain warning; drop total logged.
  - test_stop_drains_healthy_writer_and_persists_all: enqueue 3, stop() → qsize() == 0 and get_recent total == 3.
  - test_stop_on_idle_or_never_started_writer_returns_immediately: never-started writer stop() returns without error; started-but-idle writer stop() returns with qsize() == 0.
  - test_single_record_exactly_once: one enqueue → one row (empty/single edge).
  </behavior>
  <action>
  Add the behavior tests to tests/test_analytics_writer.py. Conventions: reuse the shared analytics_db fixture from conftest (do NOT declare a local duplicate — AGENTS.md flags that anti-pattern); construct AnalyticsWriter directly with small caps instead of the 1000-cap analytics_writer fixture where the test needs a specific cap; build records with a module-local _record(i) helper emitting the 12-key dict from 01-PATTERNS.md (routes/chat.py payload shape); gate via an asyncio.Event awaited inside a wrapper around analytics_db.log_request (instance-attribute assignment on the db object — never time.sleep); every async test carries @pytest.mark.asyncio; assertions use the db's own query API (get_recent) with total + unique id set. If any test exposes a defect in analytics/writer.py (e.g. task_done skipped on a raising log_request → stop() hangs), fix the production code in this task and state it in the commit message — the tests are the locked spec.
  </action>
  <verify>
    <automated>.venv/bin/python -m pytest tests/test_analytics_writer.py -v -k "not burst"</automated>
    <fails_when>non-zero exit code, or any test reports FAIL — drop counts must be exactly 54/3/one-warning, drain must yield exactly-once rows, stuck stop must return bounded, idle stop must be error-free</fails_when>
  </verify>
  <acceptance_criteria>
  - The seven behavior tests exist and the targeted run exits 0.
  - grep -c "time.sleep" tests/test_analytics_writer.py returns 0 (determinism discipline — event-loop-blocking sleeps banned).
  - grep -c "def db(" tests/test_analytics_writer.py returns 0 and grep -c "analytics_db" tests/test_analytics_writer.py returns >= 1 (shared fixture reused, no local duplicate).
  - Drop test asserts qsize() == 3 and dropped == 54 exactly (not >=/<= ranges).
  - Exactly-once assertions use unique id sets: len({row["id"] for row in rows}) == expected count.
  </acceptance_criteria>
  <done>Drop-newest accounting (54 drops, one warning at 50, cap never exceeded), gated drain exactly-once, bounded stop with residue counting, and idle/single edge behavior are all mechanically proven.</done>
  <reversibility rating="reversible">Test-only additions (plus any defect fix they force); revertible independently.</reversibility>
</task>

<task type="auto" tdd="true">
  <name>Task 2: 20-stream concurrent burst + disconnect exactly-once (RELI-02a, edge concurrency)</name>
  <files>tests/test_analytics_writer.py</files>
  <read_first>
  - .planning/phases/01-gateway-runtime-hardening/01-CONTEXT.md — locked decision "Concurrency Verification" (burst shape, qsize sampling) and "Bounded Analytics Write Path"
  - .planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md — "RELI-02 burst test skeleton" (probe-verified ≈0.1–0.2s runtime), Pitfalls 7 (do not conflate drop test with burst: burst uses default/large cap, slowed-but-flowing writer), 9 (GeneratorExit enqueue), 12 (determinism recipe)
  - tests/test_chat_endpoint.py lines 102-114 (inline fake provider + patch conventions)
  - tests/conftest.py (client + analytics_writer + analytics_db fixtures from Plan 01)
  - routes/chat.py — _tracked_stream signature after Plan 01 (module-level, takes analytics_writer)
  </read_first>
  <behavior>
  - test_concurrent_burst_full_delivery_exactly_once: patch routes.chat.create_provider with a side_effect factory returning a distinct inline fake provider per request (each yields its own tok{i} then a usage chunk); wrap analytics_db.log_request (the fixture writer's db) with a per-write await asyncio.sleep(0.005) wrapper; one shared client; launch a sampler task polling analytics_writer.qsize() ~50 times at ~1ms into a list; await asyncio.gather of 20 client.post calls; await the sampler; await analytics_writer.wait_drained(5.0); assert all 20 responses are 200, each body contains its own tok{i} and ends with the [DONE] frame; assert max(samples) <= the writer cap; assert get_recent(limit=100) total == 20 with 20 unique ids.
  - test_client_disconnect_midstream_still_enqueues_exactly_once: build a fake provider yielding several tokens; call routes.chat._tracked_stream directly with (provider, a ChatRequest instance, "manifest", a model id, the analytics_writer, None); iterate exactly one yielded frame; await gen.aclose() (triggers GeneratorExit → finally); await wait_drained; assert exactly 1 row.
  </behavior>
  <action>
  Add the two behavior tests. Burst conventions per the locked decision: N=20 concurrent posts over the ONE shared ASGI client via asyncio.gather (never sequential); per-request providers via patch side_effect (unittest.mock.patch of routes.chat.create_provider and routes.chat.resolve_provider — never monkeypatch for providers); the slowed writer is a wrapper with per-write await asyncio.sleep(0.005) assigned onto the fixture db's log_request attribute (deterministic lag, no real I/O); the sampler is a plain async function task appending qsize() readings; final drain via the public wait_drained before any row assertion; timing budget stays ≈0.1–0.2s so make test stays fast. Disconnect test: construct the request model the way routes/chat.py does (import ChatRequest from routes.chat), drive the module-level generator directly, close it after the first frame. Both tests carry @pytest.mark.asyncio. If the burst exposes a Plan-01 defect (lost/duplicated rows, unbounded qsize), fix production code in this task.
  </action>
  <verify>
    <automated>.venv/bin/python -m pytest tests/test_analytics_writer.py -k "burst or disconnect" -v && .venv/bin/python -m pytest tests/ -v</automated>
    <fails_when>non-zero exit code, any FAIL/ERROR in either summary, or the burst timing out via wait_drained's 5s deadline (surfaces as a test failure) — proving streams incomplete, rows != 20, duplicate ids, or qsize exceeding cap</fails_when>
  </verify>
  <acceptance_criteria>
  - The two behavior tests exist; the targeted run and the full suite both exit 0.
  - Burst asserts: all(r.status_code == 200), per-response token + [DONE] presence, max(samples) <= cap, get_recent total == 20, unique id count == 20.
  - grep -c "asyncio.gather" tests/test_analytics_writer.py returns >= 1 and grep -c "time.sleep" tests/test_analytics_writer.py returns 0.
  - Disconnect test asserts exactly 1 row after aclose (GeneratorExit path — enqueue-in-finally proven, not assumed).
  - Full-suite runtime remains fast (research probe: burst ≈0.1–0.2s; whole suite well under 60s).
  </acceptance_criteria>
  <done>RELI-02 proven deterministically: 20 concurrent clients each receive their full stream; exactly-once logging holds under a lagging writer with bounded queue occupancy; client disconnects never lose or double-count a row.</done>
  <reversibility rating="reversible">Test-only additions (plus any forced defect fix); revertible independently.</reversibility>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| concurrent streams → shared queue | many producers (one finally-block per stream) write into one bounded queue read by one consumer |
| test doubles → production contract | fake providers/writers must exercise the real AnalyticsWriter/AnalyticsDB path, not mock it away |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-01-02 | DoS | unbounded pending analytics writes under provider/DB lag | high | mitigate | This plan PROVES the Plan-01 mitigation: qsize sampled <= cap during burst; drop-newest unit tests; bounded stop |
| T-01-07 | Tampering | duplicate/lost analytics rows under concurrency or disconnect (silent accounting corruption) | medium | mitigate | Exactly-once assertions (20 unique ids; disconnect aclose → exactly 1 row) — a violation fails the suite |
| T-01-08 | DoS (test suite) | flaky time-based concurrency test erodes trust in CI | low | mitigate | Determinism discipline: no time.sleep anywhere (grep-gated), gate Event + per-write async sleep recipe (probe-verified) |

No package installs this phase — no supply-chain row.
</threat_model>

<verification>
- .venv/bin/python -m pytest tests/test_analytics_writer.py -v exits 0 (tracer + unit + burst + disconnect suites together).
- Full suite .venv/bin/python -m pytest tests/ -v exits 0 — this IS the locked "part of make test" proof for RELI-02.
- Repeat-run stability spot check: run the burst test twice; both green (determinism discipline).
</verification>

<success_criteria>
- RELI-02 closed under the locked verification design: concurrent full-stream delivery, exactly-once rows, bounded queue with sampled qsize, drop/drain/stop lifecycle all mechanically proven and permanently part of make test.
</success_criteria>

## Artifacts this phase produces

Additions from this plan (complementing 01-PLAN-01's inventory):

- tests/test_analytics_writer.py — extended with: _record(i) helper (12-key payload builder); queue-unit tests (drop-newest accounting + every-50 warning, identical-payload distinctness, gated drain exactly-once, bounded stop + residue, healthy stop, idle/never-started stop, single-record); burst test (20 concurrent streams, slowed writer, qsize sampler, exactly-once rows); disconnect test (direct _tracked_stream aclose → exactly one enqueue).
- No new production symbols, env vars, or config fields (production artifacts all landed in 01-PLAN-01/02).

<output>
Create `.planning/phases/01-gateway-runtime-hardening/01-PLAN-03-SUMMARY.md` when done.
</output>
