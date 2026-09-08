---
phase: 01-gateway-runtime-hardening
verified: 2026-09-08T05:48:07Z
status: human_needed
score: 4/6 must-haves verified
covered_files: [".env.example", ".planning/REQUIREMENTS.md", ".planning/phases/01-gateway-runtime-hardening/01-01-PLAN.md", ".planning/phases/01-gateway-runtime-hardening/01-01-SUMMARY.md", ".planning/phases/01-gateway-runtime-hardening/01-02-PLAN.md", ".planning/phases/01-gateway-runtime-hardening/01-02-SUMMARY.md", ".planning/phases/01-gateway-runtime-hardening/01-03-PLAN.md", ".planning/phases/01-gateway-runtime-hardening/01-03-SUMMARY.md", ".planning/phases/01-gateway-runtime-hardening/01-REVIEW.md", "AGENTS.md", "analytics/db.py", "analytics/writer.py", "config.py", "main.py", "requirements.txt", "routes/chat.py", "static/playground/playground.js", "tests/conftest.py", "tests/test_analytics_writer.py", "tests/test_chat_endpoint.py", "tests/test_startup_validation.py"]
covered_digest: "v1:sha256:207ee64ffa4f50067c6cefe316eaf05e862df9efa60f12cb5374dd1383c5798d"
behavior_unverified: 2
behavior_unverified_items:
  - truth: "Playground SSE error bubble shows the human message (never '[object Object]') — 01-01-TR6 / RELI-03d"
    test: "make dev, open http://localhost:8000/playground, send a request against a failing/fake provider"
    expected: "Chat bubble renders the curated human message (e.g. the quota string), not '[object Object]' and not a truncated silent stream"
    why_human: "Zero-build vanilla-JS playground (locked PROJECT.md decision — no JS harness exists); source-level assertions pass (both parse sites read parsed.error?.message with 'Unknown gateway error' fallback, exception-type discrimination), but the rendered bubble is visual behavior no automated test can exercise. Tracked open in .planning/WINDOWS.md item #1 as end-of-phase UAT."
  - truth: "Records are written FIFO by the single consumer task — 01-03-TR7 (tagged verification: backstop)"
    test: "Observe drain order under load (or accept the structural argument)"
    expected: "Queue-get order equals serial log_request landing order"
    why_human: "request_logs has no monotonic sequence column (uuid4 PK, second-granularity created_at), so landing order is not column-observable; the plan itself marks this truth backstop and 'deliberately not column-asserted'. Structural evidence is source-level only: one consumer task, `await self._db.log_request(record)` serially in AnalyticsWriter._run (analytics/writer.py:52-60)."
coincidental_reliance_items: []
human_verification:
  - test: "Manual playground error-bubble check (WINDOWS.md #1, status open)"
    expected: "Error bubble shows the human message (e.g. 'zai-coding quota exhausted — resets within the 5-hour window'), never '[object Object]'"
    why_human: "Visual browser behavior; no JS test harness exists for the vanilla-JS playground (locked decision)"
  - test: "Accept or harden FIFO-landing guarantee (01-03-TR7, backstop)"
    expected: "Either accept the structural single-consumer guarantee or request an order-probe test"
    why_human: "No observable column expresses landing order; truth was deliberately marked non-inferable at plan time"
  - test: "Prohibition P-RELI-02 enforcement-tier decision: request content must never be queued/persisted in the analytics path (test-tier prohibition with structural-only enforcement)"
    expected: "Confirm today's structural enforcement is acceptable (production record literal carries exactly the 12 count/timing/status/credit keys — routes/chat.py:110-127; INSERT is column-explicit with content-free columns — analytics/db.py:77-100) or add a shape-pinning regression test that fails if a messages/content field is ever added to the enqueue dict"
    why_human: "unverified-prohibition — human review recommended. No wired negative test would fail if a content field were added (writer tests build their own _record(i) dicts; DB rows are asserted by count/id, not key shape). Fail-closed per the test-tier prohibition rule: never silently green."
---

# Phase 1: Gateway Runtime Hardening Verification Report

**Phase Goal:** The live gateway fails fast on bad configuration and keeps every stream intact under concurrent load, with client-compatible error frames — the "no quota-exhaustion surprises across a full coding day" foundation
**Verified:** 2026-09-08T05:48:07Z
**Status:** human_needed
**Re-verification:** No — initial verification (no previous VERIFICATION.md, Step 0)

## Goal Achievement

Verification basis: direct source reads of all 9 implementation artifacts through HEAD `82f0d65` (including the full review-fix wave `83ee32c..25e4557`, all 12 finding commits confirmed in git log), plus one full-suite run: **`.venv/bin/python -m pytest tests/ -q` → 99 passed, 1 warning, 3.12s** — matching the post-fix state reported in 01-REVIEW.md (93 + 6 regression tests).

### Observable Truths

Merged must-haves: 4 ROADMAP Success Criteria (non-negotiable contract) + 2 plan truths that are not SC restatements (playground renderer, FIFO backstop). Plan truths TR1-11 (01-01), TR1-6 (01-02), TR1-6 (01-03) were checked as refinements of the SCs — all their specific claims appear in the Evidence column; none failed.

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1/RELI-01: Startup aborts fast on bad config naming the variable; no-key z.ai/Manifest degrade with notices, no abort | ✓ VERIFIED | `config.py` `_validate_rate_limit` (limits.parse_many — slowapi's own parser) + `_validate_analytics_queue_size`; `main.py:29` `RuntimeError("APP_API_KEY env var is required but not set")` before any DB/writer state; zai/manifest `logger.warning` notices naming env vars + routing consequence, no abort; mkdir-wrapped + `os.access` + `write_probe()` writable guards. Behaviorally proven by 13 tests in tests/test_startup_validation.py (abort names variable, notices complete startup, determinism asserts `not db_path.exists()`, secret sentinels incl. 8-char prefixes) — all in the 99-passing suite |
| 2 | SC2/RELI-02: Concurrent multi-stream burst — every client gets its full stream; exactly-once request_logs rows; bounded pending writes | ✓ VERIFIED | `tests/test_analytics_writer.py::test_concurrent_burst_full_delivery_exactly_once` — 20 concurrent posts over one ASGI client, per-write `await asyncio.sleep(0.005)` slowed writer: all 200s, per-response tokens + `data: [DONE]`, `max(samples) <= 20` (real observed ceiling, MN-04 fix), 20 unique row ids after `wait_drained`. `::test_client_disconnect_midstream_still_enqueues_exactly_once` — direct generator `aclose()` (GeneratorExit) → exactly 1 row. Queue units: cap-3 × 57 enqueues → `qsize()==3, dropped==54`, exactly one warning at drop #50; gated drain exactly-once; bounded stop with residue; idle/never-started stop; post-stop enqueue counted+logged (MN-01 fix). Producer is `analytics_writer.enqueue` in the generator finally (routes/chat.py:107-127) — `create_task`/`add_done_callback` fully deleted |
| 3 | SC3/RELI-03: SSE error frames carry the nested OpenAI-style object (message/type[, code]); quota vs auth distinct; internal exception text never reaches clients | ✓ VERIFIED | routes/chat.py:89-104 yields `{"error": {message, type[, code]}}` from a curated constant table (zai 429/1113 → `rate_limit_error`/`zai_quota_exhausted`; 401/403 → `authentication_error`/`zai_auth_failed`; else `server_error`, no code key), terminated by `[DONE]`. Exact parsed-object equality asserted for all four variants + empty-str(e) edge (tests/test_chat_endpoint.py:131-136, 180-184, 203-207, 226-229, 248-251); `"Provider failed" not in response.text` (line 228); em-dash quota string byte-identical in source and parsed-level assertions (TR9). `verify_auth` untouched — plain 401 JSON (TR10). All passing |
| 4 | SC4/ZAI-3: A z.ai quota event (429 or code 1113) surfaces within the single round-trip as the dedicated quota message — no hang, no retry loop, no Manifest reroute | ✓ VERIFIED | No retry/backoff machinery exists in routes/chat.py (grep: zero hits); `resolve_provider` called exactly once (route line 46, before streaming); the except path yields the quota frame inline in the same SSE response and terminates. Tests prove the frame arrives in the response body for both 429 and 1113 paths (test_zai_coding_quota_error_frame, test_zai_coding_1113_code_maps_to_quota, endswith `[DONE]`) |
| 5 | 01-01-TR6/RELI-03d: Playground renders the nested error.message in the chat bubble — never "[object Object]" | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Source-level verified: both SSE parse sites (main loop + [DONE] tail buffer) discriminate by exception type — malformed JSON `continue`s, gateway-error throw lives outside the parse try (IM-04 fix applied, `24a67bd`), reading `parsed.error?.message \|\| 'Unknown gateway error'`; dead `pendingToken` state removed (MN-06). The rendered bubble itself is visual — no JS harness exists (locked decision); open UAT item in WINDOWS.md #1. See Human Verification |
| 6 | 01-03-TR7 (backstop): Records land FIFO via the single consumer task | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Structural source evidence: one consumer task, serial `await self._db.log_request(record)` in `_run` (analytics/writer.py:52-60); gated-drain test observes serial exactly-once draining. Landing order itself is not observable (uuid4 PK, 1s-granularity created_at) and was deliberately not column-asserted at plan time. See Human Verification |

**Score:** 4/6 truths verified (2 present, behavior-unverified)

### Prohibitions (must-NOT checks)

| Prohibition | Tier | Wired enforcement | Verdict |
|---|---|---|---|
| P-RELI-03: no user request content in SSE error frames / client payloads | test | Exact parsed-object equality (`assert err == {...}`) on all frame variants — any content echo or extra key fails the suite | ✓ VERIFIED (no violation, enforcement wired) |
| P-RELI-01: no secret values (even partial/masked) in startup notices/aborts/logs | test | Sentinel test asserts full values AND 8-char prefixes absent from caplog and `str(ValidationError)`; `hide_input_in_errors: True` in config.py | ✓ VERIFIED (no violation, enforcement wired) |
| P-RELI-02: no request CONTENT queued/persisted in the analytics path | test | **Structural only** — production record literal carries exactly the 12 count/timing/status/credit keys (routes/chat.py:110-127) and the INSERT is column-explicit over content-free columns (analytics/db.py:77-100); no wired negative test pins the record shape | ⚠️ unverified-prohibition — human review recommended (no violation found; enforcement tier below declared — see Human Verification #3) |

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Dropped-writes visibility beyond logs (counter) | Phase 4 | Plan 03 objective: "dropped-writes visibility log-only this phase (Prometheus counter deferred to Phase 4 OBSV-01 — must NOT appear here)"; ROADMAP Phase 4 SC1 = Prometheus metrics endpoint |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| analytics/writer.py | Bounded AnalyticsWriter (enqueue/qsize/wait_drained/start/stop/dropped, drop-newest, constructor guard) | ✓ VERIFIED | 78 lines, substantive; constructed by main.py lifespan and conftest fixture — WIRED |
| config.py | `analytics_queue_size`, RATE_LIMIT + queue-size validators, secret-hiding model_config | ✓ VERIFIED | Read in full; validator fires at `settings = Settings()` import — WIRED |
| main.py | Lifespan: aborts → notices → writable guards → writer after db.initialize; shutdown writer.stop() BEFORE db.close() | ✓ VERIFIED | Ordering confirmed by line position (72 < 74) — WIRED |
| routes/chat.py | Producer swap to enqueue-in-finally; nested error object; dead fire-and-forget code deleted | ✓ VERIFIED | 12-key record unchanged in shape; `_on_log_task_done`/`create_task` absent (ast + grep clean per plan acceptance) — WIRED |
| tests/conftest.py | analytics_writer fixture; client depends on it; both app.state injections; dead mock_provider fixtures removed (MN-07) | ✓ VERIFIED | Read in full — WIRED |
| tests/test_analytics_writer.py | Queue-unit + burst + disconnect suites | ✓ VERIFIED | 12 tests, exact-count assertions (54/3/one-warning) — passing |
| tests/test_startup_validation.py | RELI-01a-d + determinism + sentinel coverage + IM-01/MN-02 regressions | ✓ VERIFIED | 13 tests — passing |
| tests/test_chat_endpoint.py | Exact frame-object equality ×4 + empty-message + moved integration test (MN-05) + deterministic drain | ✓ VERIFIED | Assertions read at lines 131-251 — passing |
| static/playground/playground.js | Both parse sites unwrap nested error; exception-type discrimination; git-tracked | ✓ VERIFIED (source) | `git ls-files` shows tracked; visual behavior → Human Verification |
| .env.example | ANALYTICS_QUEUE_SIZE=1000 documented | ✓ VERIFIED | Present with comment |
| requirements.txt | `limits>=3.5` declared (IM-03) | ✓ VERIFIED | Line 11 |
| AGENTS.md | Post-cutover instructions true | ✓ VERIFIED | `analytics_writer` ×6, `add_done_callback` ×0 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| main.py lifespan | analytics/writer.py | AnalyticsWriter(db, queue_size=settings.analytics_queue_size).start() after db.initialize(); stop() before close() | ✓ WIRED | Read directly; ordering is the locked contract |
| routes/chat.py finally-block | AnalyticsWriter.enqueue | single guarded call, exactly once per generator incl. GeneratorExit | ✓ WIRED | Disconnect test proves exactly-once under aclose() |
| SSE error yield | playground parse sites | nested `{"error": {...}}` ↔ `parsed.error?.message` | ✓ WIRED | Both sides read; served via /playground + /static mount (test_playground.py passes) |
| tests/conftest.py | app.state.analytics_writer | manual injection because ASGITransport never runs lifespan | ✓ WIRED | Read directly |
| config validator | limits.parse_many | fires at import of config, before any Limiter import | ✓ WIRED | `settings = Settings()` at config.py module scope |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| routes/chat.py error frames | error_obj | live exception attributes (`status_code`, error text) → curated constant table | ✓ exception-driven, constants curated | ✓ FLOWING |
| routes/chat.py → request_logs | 12-key record | live per-request counters/usage/credits | ✓ real AnalyticsDB via AnalyticsWriter (in-memory sqlite in tests is the real AnalyticsDB class) | ✓ FLOWING |
| startup notices/aborts | settings.get_api_key / app_api_key | effective-key semantics read at startup | ✓ | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite (single run, evidence for all behavior-dependent truths) | `.venv/bin/python -m pytest tests/ -q` | 99 passed, 1 warning, 3.12s | ✓ PASS |
| Review-fix wave actually on main | `git log --oneline -25` | all 12 fix commits present (83ee32c, 1761c0b, e9ceb1b, 24a67bd, fea9f19, 51fb57f, 490be8f, 2e8f214, e6ba082, 5a1ff68, 25e4557, 82f0d65) | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` exist and no phase PLAN/SUMMARY declares probes (verification is the pytest suite, run above).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| RELI-01 | 01-02-PLAN | Fail-fast startup validation; notices for missing optional keys | ✓ SATISFIED | config.py validators + main.py lifespan; 13 passing tests (Truth 1) |
| RELI-02 | 01-01-PLAN, 01-03-PLAN | Bounded write path; full streams + exactly-once rows under concurrency | ✓ SATISFIED | writer + burst/queue-unit/disconnect suites passing (Truth 2) |
| RELI-03 | 01-01-PLAN | OpenAI-style SSE error frames; distinct quota/auth; no internal leakage | ✓ SATISFIED (server-side fully; visual bubble = open human UAT) | Exact-object frame tests passing (Truth 3); playground source verified (Truth 5) |

Orphaned requirements: none — REQUIREMENTS.md maps exactly RELI-01/02/03 to Phase 1; all three are claimed by plan frontmatter (01-01: RELI-02, RELI-03; 01-02: RELI-01; 01-03: RELI-02) and all three are checked Complete in the traceability table.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | Zero TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers across all 9 phase-modified source files | — | Debt-marker gate clean |

ℹ️ Info (non-blocking): ROADMAP.md still lists three unchecked duplicate plan entries (`01-PLAN-01-tracer…`, `01-PLAN-02-startup-validation…`, `01-PLAN-03-concurrency-proof…`) — stale naming artifacts of the executed `01-0{1,2,3}-PLAN.md` (same content, all checked 3/3). Bookkeeping only; no codebase impact. Pre-existing `verify_auth` non-constant-time compare noted out-of-scope by 01-REVIEW.md — unchanged by this phase, no later phase explicitly covers it.

### Human Verification Required

1. **Playground error bubble (WINDOWS.md #1 — open)**
   **Test:** `make dev`, open http://localhost:8000/playground, send a request against a failing/fake provider
   **Expected:** The chat bubble shows the curated human message (e.g. the quota string) — never "[object Object]", never a silently truncated stream
   **Why human:** Visual browser behavior; the vanilla-JS playground has no test harness (locked PROJECT.md decision)

2. **FIFO landing guarantee (01-03-TR7, backstop-tagged)**
   **Test:** Accept the structural guarantee or observe drain order under load
   **Expected:** Queue-get order equals serial landing order (single consumer task, serial awaits — analytics/writer.py:52-60)
   **Why human:** No DB column expresses order (uuid4 PK, 1s created_at); the plan deliberately marked this truth non-inferable ("deliberately not column-asserted")

3. **Prohibition P-RELI-02 enforcement tier (unverified-prohibition — human review recommended)**
   **Test:** Review the analytics write path for content exclusion
   **Expected:** Confirm today's structural enforcement is acceptable (12-key count/timing/status/credit literal at routes/chat.py:110-127; column-explicit content-free INSERT at analytics/db.py:77-100) or request a shape-pinning regression test that fails if a messages/content field is ever added to the enqueue dict
   **Why human:** Declared `verification: test` but no wired negative test exists (writer tests build their own `_record(i)` dicts; DB rows asserted by count/id only). Fail-closed rule: never silently green.

### Gaps Summary

No gaps. All four ROADMAP Success Criteria are verified with passing behavioral evidence in the codebase; all artifacts exist, are substantive, wired, and data-flowing; all three requirements are satisfied; the review-fix wave (12/12 findings) is confirmed on main with the suite at 99 passed. Three items route to a human: the playground visual check (already tracked as the phase's end-of-phase UAT in WINDOWS.md), an accept-or-harden decision on the backstop-tagged FIFO truth, and an enforcement-tier decision on the P-RELI-02 prohibition (structurally enforced, no wired negative test).

---

_Verified: 2026-09-08T05:48:07Z_
_Verifier: Verify-P1 (gsd-verifier)_
