---
phase: 04-observability-resilience
plan: 03
subsystem: api
tags: [rate-limiting, slowapi, per-key, security, fastapi]

# Dependency graph
requires:
  - phase: 04-observability-resilience
    provides: "04-01's routes/chat.py metrics.record_request() wiring — sequenced before this plan solely to avoid a same-wave routes/chat.py file conflict, no functional dependency"
provides:
  - "Per-key rate limiting stacked alongside the existing per-IP limit on POST /v1/chat/completions, keyed by the Bearer token (extract_bearer_key), falling back to remote IP when the token is missing/malformed"
  - "RATE_LIMIT_PER_KEY env var + config.py validator, fails fast at Settings construction on malformed input"
affects: [ZAICodingProvider/ManifestProvider traffic (both routed through the same chat route, both now subject to the per-key limit), Phase-5 docs refresh (DOCS-01/02 should document RATE_LIMIT_PER_KEY and the dual-limit behavior), AGENTS.md's documented request-flow list (per-IP limit step should note the new per-key limit stacked alongside it)]

# Actuals (#2632)
actuals:
  tokens: 2397
  tasks: 2
  commits: 3
  plan_head_before: 75cdecdd5ff4f0969d0ef6a3531ef71e822618c2

# Tech tracking
tech-stack:
  added: []
  patterns: ["Dynamic (callable) slowapi limit_value instead of a bare string: @limiter.limit(lambda: settings.rate_limit_per_key, key_func=extract_bearer_key) re-reads the setting on every request, unlike a plain string which slowapi parses once at decoration/import time", "Stacked @limiter.limit() decorators with different key_func on one shared Limiter instance for independent multi-dimension rate limiting, per slowapi's native StrOrCallableStr + per-call key_func support"]

key-files:
  created: [tests/test_rate_limiting.py]
  modified: [config.py, rate_limiter.py, routes/chat.py, .env.example, tests/test_startup_validation.py]

key-decisions:
  - "Task 1 followed RED-GREEN TDD discipline literally: wrote 2 failing tests against the unmodified source (missing rate_limit_per_key attribute, no validator), confirmed genuine RED (AttributeError + DID NOT RAISE, not collection/fixture errors), committed as test(04-03), then implemented config.py/rate_limiter.py/routes/chat.py/.env.example and confirmed both green, committed as feat(04-03). No REFACTOR commit needed."
  - "Deviated from 04-PATTERNS.md's/04-RESEARCH.md's literal code snippet (@limiter.limit(settings.rate_limit_per_key, key_func=extract_bearer_key), a bare string): read the installed slowapi==0.1.9 source directly and confirmed a plain-string limit_value is parsed into an immutable Limit object once, at decoration time (module import) -- monkeypatching settings.rate_limit_per_key afterward, as Task 1's own <behavior> spec requires, would have had zero effect on the already-registered static limit. Used slowapi's documented StrOrCallableStr support instead: a zero-arg lambda that re-reads settings.rate_limit_per_key on every request via LimitGroup.__iter__. Verified against slowapi/extension.py and slowapi/wrappers.py source (both read this session) that a no-'key'-parameter callable is called with no arguments and its limits are combined with the existing static per-IP limit in the same __evaluate_limits() pass -- confirmed empirically by the dual-limit independence test."
  - "Added an autouse limiter.reset() fixture (before and after each test) in tests/test_rate_limiting.py: slowapi's in-memory storage is a module-level singleton shared across the whole pytest session, and tests/conftest.py's auth_headers fixture returns the same fixed Bearer token (\"changeme\") reused across the entire suite -- without a reset, an earlier test's hit count against that token would leak into this file's low, monkeypatched-limit boundary assertions and produce flaky, order-dependent failures."

requirements-completed: [OBSV-02]

coverage:
  - id: D1
    description: "A client exceeding RATE_LIMIT_PER_KEY (same Bearer token) receives HTTP 429 before any provider is constructed or called"
    requirement: "OBSV-02"
    verification:
      - kind: integration
        ref: "tests/test_rate_limiting.py#test_per_key_limit_429s_on_third_request_same_token"
        status: pass
    human_judgment: false
  - id: D2
    description: "The existing per-IP RATE_LIMIT continues to apply independently alongside the new per-key limit -- both apply"
    requirement: "OBSV-02"
    verification:
      - kind: integration
        ref: "tests/test_rate_limiting.py#test_per_key_limit_429s_independently_of_per_ip_limit"
        status: pass
    human_judgment: false
  - id: D3
    description: "RATE_LIMIT_PER_KEY is configurable via .env and fails fast (ValidationError naming the variable) at Settings construction if malformed"
    requirement: "OBSV-02"
    verification:
      - kind: unit
        ref: "tests/test_rate_limiting.py#test_settings_rejects_malformed_rate_limit_per_key"
        status: pass
      - kind: unit
        ref: "tests/test_startup_validation.py#test_rate_limit_per_key_validator_rejects_garbage"
        status: pass
    human_judgment: false
  - id: D4
    description: "A request with a missing/malformed Bearer token still gets a per-key-scoped (IP-scoped) limit rather than being exempt from per-key limiting entirely"
    requirement: "OBSV-02"
    verification:
      - kind: unit
        ref: "rate_limiter.py extract_bearer_key() falls back to get_remote_address(request) when the stripped token is empty"
        status: pass
    human_judgment: false
  - id: D5
    description: "Exactly N requests (the configured limit) with the same Bearer token all succeed with no 429; the N+1th 429s -- both sides of the threshold"
    requirement: "OBSV-02"
    verification:
      - kind: integration
        ref: "tests/test_rate_limiting.py#test_per_key_limit_boundary_exact_n_succeed_nplus1_fails"
        status: pass
    human_judgment: false
  - id: D6
    description: "rate_limiter.py never logs the raw Bearer-token rate-limit key"
    requirement: "OBSV-02"
    verification:
      - kind: unit
        ref: "tests/test_rate_limiting.py#test_rate_limiter_source_never_logs_the_extracted_token"
        status: pass
    human_judgment: false

duration: ~35min
completed: 2026-09-08
status: complete
---

# Phase 4 Plan 3: Per-Key Rate Limiting (OBSV-02) Summary

**Per-Bearer-token rate limiting stacked alongside the existing per-IP `RATE_LIMIT` on `POST /v1/chat/completions`, using slowapi's dynamic (callable) limit-value support instead of the literal static-string pattern in 04-PATTERNS.md/04-RESEARCH.md, since a static string would have made `RATE_LIMIT_PER_KEY` frozen at import time and untestable via monkeypatch.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-09-08
- **Completed:** 2026-09-08
- **Tasks:** 2/2
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments

- `config.py`: `rate_limit_per_key: str = "60/minute"` field + `_validate_rate_limit_per_key` validator, identical shape to the existing `_validate_rate_limit`
- `rate_limiter.py`: `extract_bearer_key(request) -> str` — strips `Bearer `/`bearer ` prefix (same idiom as `routes/chat.py`'s `verify_auth`), falls back to `get_remote_address(request)` when the token is empty
- `routes/chat.py`: stacked `@limiter.limit(lambda: settings.rate_limit_per_key, key_func=extract_bearer_key)` beneath the existing `@limiter.limit(settings.rate_limit)` on the `chat` route
- `.env.example`: `RATE_LIMIT_PER_KEY=60/minute` row documenting both limits apply
- `tests/test_rate_limiting.py` (new, 6 tests): 429-before-provider-call, validator rejection, exact-boundary (N succeeds / N+1 fails), dual-limit independence, no-token-logging source scan
- `tests/test_startup_validation.py`: `test_rate_limit_per_key_validator_rejects_garbage`, mirroring the existing `RATE_LIMIT` validator trio
- Full suite: 132 → 138 passing (132 baseline + 6 new), all green

## Task Commits

Task 1 (TDD: RED → GREEN, no REFACTOR needed):
1. **RED: failing tests for per-key rate limiting** - `d241fab` (test)
2. **GREEN: wire RATE_LIMIT_PER_KEY end-to-end** - `3570bcb` (feat)

Task 2:
3. **Boundary, dual-limit, validator, and no-log-leak coverage** - `6df8ea4` (test)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP update)

## Files Created/Modified

- `config.py` — `rate_limit_per_key` field + `_validate_rate_limit_per_key` validator
- `rate_limiter.py` — `extract_bearer_key(request)` key_func with IP fallback
- `routes/chat.py` — `import extract_bearer_key`; second stacked `@limiter.limit()` decorator using a zero-arg lambda for dynamic evaluation
- `.env.example` — `RATE_LIMIT_PER_KEY=60/minute` row
- `tests/test_rate_limiting.py` (new) — 6 tests covering OBSV-02's must_haves, edge cases, and prohibition
- `tests/test_startup_validation.py` — 1 new validator test

## Decisions Made

- Followed the task's `tdd="true"` attribute literally for Task 1: wrote 2 target tests against the unmodified source first, confirmed genuine RED (`AttributeError: ... has no attribute 'rate_limit_per_key'` and `Failed: DID NOT RAISE`, not collection/fixture errors), committed, then implemented and confirmed GREEN before committing.
- Used a callable (`lambda: settings.rate_limit_per_key`) instead of the bare-string form shown in 04-PATTERNS.md/04-RESEARCH.md — see Deviations below.
- Added an autouse `limiter.reset()` fixture in `tests/test_rate_limiting.py` to prevent slowapi's shared in-memory storage from leaking hit counts across tests that reuse the same fixed `auth_headers` Bearer token.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Static-string limit_value would make RATE_LIMIT_PER_KEY untestable and effectively frozen at import time**
- **Found during:** Task 1, while implementing the exact `@limiter.limit(settings.rate_limit_per_key, key_func=extract_bearer_key)` snippet from 04-PATTERNS.md/04-RESEARCH.md
- **Issue:** Read the installed `slowapi==0.1.9` source (`extension.py:662-704`, `wrappers.py:84-97`) directly rather than assuming: when `limit_value` is a plain string, slowapi builds an immutable `Limit`/`RateLimitItem` from it once, at decoration time (i.e., at `routes/chat.py` module import) — it is never re-parsed per request. Task 1's own `<behavior>` spec requires "With `settings.rate_limit_per_key` monkeypatched to `2/minute`, two requests ... succeed; a third ... returns 429" — a static string would have locked in whatever `RATE_LIMIT_PER_KEY` value existed at first import (the `"60/minute"` default, since no `.env` exists in CI) and made the monkeypatch a no-op, causing every request in the test to succeed at 200 instead of the third one 429-ing. This would also mean any future runtime reconfiguration of `RATE_LIMIT_PER_KEY` requires a process restart, undocumented behavior not called out in 04-CONTEXT.md's locked decisions.
- **Fix:** Passed `lambda: settings.rate_limit_per_key` — slowapi's documented `StrOrCallableStr` parameter type — instead of the bare attribute. Confirmed via `LimitGroup.__iter__` (`wrappers.py:84-97`) that a callable with no `key` parameter is invoked with zero arguments on every request, and via `_check_request_limit` (`extension.py:576-630`) that the resulting per-request `Limit` is combined with the existing static per-IP limit in the same `__evaluate_limits()` pass — confirmed empirically by `test_per_key_limit_429s_independently_of_per_ip_limit`.
- **Files modified:** `routes/chat.py` (inline comment documents the reasoning at the decorator site)
- **Verification:** `test_per_key_limit_429s_on_third_request_same_token` passes (monkeypatch takes effect); full suite 138/138.
- **Committed in:** `3570bcb` (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 correctness bug relative to the plan's own literal code snippet, required to satisfy the plan's own `<behavior>` spec)
**Impact on plan:** No scope creep — same file, same decorator site, no new surface. The production behavior for a real deployment (env var read once at startup into a singleton, no runtime env-var reloading anywhere in this codebase) is functionally identical to a static string; the deviation only changes *when* the setting's current value is read (per-request vs. at-import), which is what makes the plan's own monkeypatch-based tests possible and is a strict improvement (the setting is no longer accidentally frozen at import time).

## Issues Encountered

None beyond the static-vs-dynamic limit_value deviation documented above, found and resolved within Task 1's own TDD verification loop before any GREEN commit landed.

## User Setup Required

None — no external service configuration required. `RATE_LIMIT_PER_KEY` defaults to `60/minute` (matching the existing `RATE_LIMIT` default) when unset.

## Next Phase Readiness

- OBSV-02 fully satisfied: per-key limit enforced independently alongside the existing per-IP limit, always before any provider call; `RATE_LIMIT_PER_KEY` configurable and validated at startup; missing/malformed tokens fall back to IP-scoped limiting rather than being exempt; no token values ever logged.
- Phase 4's three requirements (OBSV-01 metrics/health, OBSV-02 per-key rate limiting, OBSV-03 tenacity retry) are all now complete — no file overlap issues arose across the three plans (04-01 touched `main.py`/`metrics.py`/`routes/chat.py`'s metrics call; 04-02 touched `providers/openai_compatible_base.py`; 04-03 touched `config.py`/`rate_limiter.py`/`routes/chat.py`'s rate-limit decorator).
- `AGENTS.md`'s documented request-flow list (item 2: "`@limiter.limit(settings.rate_limit)` (slowapi, per-IP) enforces the configured rate window; over limit → `429`") is now stale by one line (doesn't mention the new stacked per-key limit) — flagged here for the Phase-5 DOCS-01/02 refresh rather than fixed now (out of this plan's `files_modified` scope).
- `.env.example`'s `RATE_LIMIT_PER_KEY` row and `AGENTS.md`'s "Important Files" `.env.example` inventory (which lists `RATE_LIMIT` but not yet `RATE_LIMIT_PER_KEY`) should both be picked up in the same Phase-5 docs pass.

---
*Phase: 04-observability-resilience*
*Completed: 2026-09-08*

## Self-Check: PASSED

- FOUND: config.py (contains rate_limit_per_key)
- FOUND: rate_limiter.py
- FOUND: routes/chat.py
- FOUND: .env.example (contains RATE_LIMIT_PER_KEY)
- FOUND: tests/test_rate_limiting.py
- FOUND: commit d241fab (test RED)
- FOUND: commit 3570bcb (feat GREEN)
- FOUND: commit 6df8ea4 (test Task 2 coverage)
