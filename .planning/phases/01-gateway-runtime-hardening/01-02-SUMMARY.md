---
phase: 01-gateway-runtime-hardening
plan: 2
subsystem: infra
tags: [pydantic-settings, startup-validation, lifespan, fail-fast, limits, slowapi]

requires:
  - phase: 01-gateway-runtime-hardening (plan 1)
    provides: lifespan-owned AnalyticsWriter start/stop wiring that the new abort/notice checks precede
provides:
  - RATE_LIMIT model_validator on Settings (limits.parse_many — slowapi's own parser)
  - Lifespan no-abort notices for missing effective zai/manifest keys
  - ANALYTICS_DB_PATH parent-writable abort before AnalyticsDB construction
  - Secret-free startup output guarantee (hide_input_in_errors + sentinel tests)
affects: [02-observability (OBSV-02 per-key limits), 04-retry (key semantics), deployment-guide env surface]

actuals:
  tokens: 2040   # chars/4 over the realized diff (config.py, main.py, tests/test_startup_validation.py)
  tasks: 2
  commits: 6     # MEASURED: git rev-list --count 171e60e..HEAD (docs commit follows separately)

tech-stack:
  added: []      # limits is slowapi's transitive dep, imported directly — no new dependency
  patterns:
    - "Validation split: pure parse checks in Settings model_validator; I/O + abort checks in lifespan"
    - "Abort/notice ordering contract: aborts precede db.initialize()/writer.start(); notices precede the writable check"

key-files:
  created:
    - tests/test_startup_validation.py
  modified:
    - config.py
    - main.py

key-decisions:
  - "RATE_LIMIT validated via limits.parse_many (the exact parser slowapi enforces with) so validation and enforcement cannot drift; fires at import of config, before every Limiter import"
  - "Validation split kept: APP_API_KEY/ANALYTICS_DB_PATH aborts stay in lifespan — model_validator would break every Settings(_env_file=None) test and zero-key runs"
  - "hide_input_in_errors=True on Settings — pydantic's truncated input_value echo leaked ~8 chars of API keys into the RATE_LIMIT abort traceback (Rule 2 fix)"

patterns-established:
  - "Pattern: fail-fast config validation naming the env VARIABLE, showing the offending value, and a valid example — never key values"
  - "Pattern: missing optional provider keys degrade with logger.warning notices naming the env vars and routing consequence — never abort"

requirements-completed: [RELI-01]

coverage:
  - id: D1
    description: "Malformed RATE_LIMIT fails at Settings construction with an actionable ValidationError naming the variable (RELI-01a)"
    requirement: RELI-01
    verification:
      - kind: unit
        ref: "tests/test_startup_validation.py#test_rate_limit_validator_rejects_garbage"
        status: pass
      - kind: unit
        ref: "tests/test_startup_validation.py#test_rate_limit_validator_rejects_wrong_granularity"
        status: pass
      - kind: unit
        ref: "tests/test_startup_validation.py#test_rate_limit_validator_rejects_bare_number"
        status: pass
      - kind: unit
        ref: "tests/test_startup_validation.py#test_rate_limit_validator_accepts_multi_limit"
        status: pass
      - kind: unit
        ref: "tests/test_startup_validation.py#test_settings_default_constructs_without_app_api_key"
        status: pass
    human_judgment: false
  - id: D2
    description: "Missing APP_API_KEY aborts startup naming the variable before db.initialize()/writer.start(); deterministic and side-effect-free on re-invocation (RELI-01b)"
    requirement: RELI-01
    verification:
      - kind: unit
        ref: "tests/test_startup_validation.py#test_missing_app_api_key_aborts_naming_variable"
        status: pass
      - kind: unit
        ref: "tests/test_startup_validation.py#test_startup_abort_is_deterministic_and_side_effect_free"
        status: pass
    human_judgment: false
  - id: D3
    description: "No effective z.ai/manifest key logs a warning naming env vars + routing consequence and startup completes — never aborts (RELI-01c)"
    requirement: RELI-01
    verification:
      - kind: unit
        ref: "tests/test_startup_validation.py#test_no_effective_zai_key_logs_notice_no_abort"
        status: pass
      - kind: unit
        ref: "tests/test_startup_validation.py#test_no_effective_manifest_key_logs_notice_no_abort"
        status: pass
    human_judgment: false
  - id: D4
    description: "Unwritable ANALYTICS_DB_PATH parent raises RuntimeError naming the variable before AnalyticsDB construction (RELI-01d)"
    requirement: RELI-01
    verification:
      - kind: unit
        ref: "tests/test_startup_validation.py#test_unwritable_analytics_db_path_aborts"
        status: pass
    human_judgment: false
  - id: D5
    description: "Startup logs and raised abort messages never contain secret values — not even partial/masked key contents (prohibition P-RELI-01)"
    requirement: RELI-01
    verification:
      - kind: unit
        ref: "tests/test_startup_validation.py#test_startup_logs_never_contain_secret_values"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-09-08
status: complete
commits: 6
plan_head_before: 171e60e08eca8c5003b9987c5e913697f17a8029
---

# Phase 1 Plan 2: Startup Validation Summary

**Fail-fast startup validation: RATE_LIMIT model_validator via slowapi's own parser, lifespan APP_API_KEY/ANALYTICS_DB_PATH aborts naming the variable, zai/manifest no-key warnings that never abort, and provably secret-free startup output**

## Performance

- **Duration:** 6 min
- **Started:** 2026-09-08T04:58:52Z
- **Completed:** 2026-09-08T05:04:53Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 3

## TDD Cycle Record

### Task 1: RATE_LIMIT model_validator (RELI-01a)

- **RED** (`a429ed6`): 5 validator tests; 3 rejection tests failed with `DID NOT RAISE ValidationError` (validator absent); accept/default tests passed (behavior pre-existed).
- **GREEN** (`fd9f3e2`): `@model_validator(mode="after") _validate_rate_limit` in `config.py` — `limits.parse_many` in try/except ValueError, message names RATE_LIMIT, shows the bad value, gives `'60/minute'` example; zero-limits guard for empty parses. Imports: `limits.parse_many`, `pydantic.model_validator` (both third-party, no new dependency). 5/5 + tests/test_config.py 5/5 green.
- **REFACTOR:** none — minimal implementation, matches verified Pattern 2.

### Task 2: Lifespan checks (RELI-01b/c/d)

- **RED** (`74584b0`): 6 lifespan tests appended; notices/writable tests failed (no warning records; unwritable path surfaced raw `sqlite3.OperationalError` — exactly the cryptic failure this feature prevents); 3 regression pins passed.
- **GREEN** (`3df1c80`): `main.py` lifespan extended exactly per Pattern 5 — APP_API_KEY abort line byte-unchanged; two `logger.warning` notices via `settings.get_api_key("zai-coding"/"manifest")` naming env vars + routing consequence; `parent = Path(db_path).parent` refactor + `os.access(parent, os.W_OK)` → `RuntimeError("ANALYTICS_DB_PATH parent directory is not writable: {parent}")` before `AnalyticsDB(...)`. 11/11 targeted, 84/84 full suite.
- **REFACTOR:** none.

## Task Commits

1. **Task 1 RED** — `a429ed6` (test)
2. **Task 1 GREEN** — `fd9f3e2` (feat)
3. **Task 2 RED** — `74584b0` (test)
4. **Task 2 GREEN** — `3df1c80` (feat)
5. **Deviation RED** — `2fc8083` (test)
6. **Deviation GREEN** — `f23fa29` (fix)

**Plan metadata:** (docs commit follows)

## Accomplishments

- Malformed `RATE_LIMIT` now aborts at Settings construction (import of config) with an actionable message — probe-verified failure mode (slowapi accepting garbage at construction AND decoration, exploding at request time) eliminated.
- Missing `APP_API_KEY` and unwritable `ANALYTICS_DB_PATH` abort at lifespan naming the variable, before any DB/writer state is created; re-invocation is deterministic and side-effect-free.
- Missing effective zai/manifest keys degrade with explicit warnings (env vars + routing consequence), preserving zero-key dev/test runs and rollback-by-unset.
- Startup output proven secret-free: sentinel test guards caplog AND the raised ValidationError, including 8-char partial-prefix leaks.

## Files Created/Modified

- `config.py` — `@model_validator(mode="after") _validate_rate_limit` (limits.parse_many); `hide_input_in_errors: True` in model_config.
- `main.py` — lifespan: zai/manifest no-key notices, `os.access` writable guard before AnalyticsDB construction, `import os`; APP_API_KEY abort and shutdown ordering (writer.stop before db.close) untouched.
- `tests/test_startup_validation.py` — NEW: 11 tests (5 validator + 6 lifespan) covering RELI-01a–d, determinism, and the secret prohibition.

## Decisions Made

- Validator uses `limits.parse_many` (slowapi's own parser) — validation and enforcement cannot drift.
- Validation split honored: APP_API_KEY/ANALYTICS_DB_PATH aborts in lifespan (model_validator would break zero-key test runs).
- `hide_input_in_errors=True` added (see Deviations) rather than reformulating the raised error — keeps pydantic's standard surface while eliminating the echo.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Information Disclosure] pydantic ValidationError echoed API-key prefixes into the abort traceback**
- **Found during:** Task 2 verification (optional spot-check `APP_API_KEY= RATE_LIMIT=bogus/zzz .venv/bin/python -c "import config"`)
- **Issue:** pydantic 2.13.1 renders `input_value={...}` (truncated) on model-validator errors — the real `.env` key prefixes leaked into the operator-visible abort traceback. Prohibition P-RELI-01 covers partial/masked leaks; the plan's sentinel test only exercised a successful startup, so this surface was unguarded.
- **Fix:** `model_config` gains `"hide_input_in_errors": True`; sentinel test extended to assert 8-char prefixes of all four key sentinels are absent from caplog AND `str(ValidationError)` on the RATE_LIMIT path.
- **Files modified:** config.py, tests/test_startup_validation.py
- **Verification:** RED (`2fc8083`) reproduced `'sk-llm-S'` leak; GREEN (`f23fa29`) — 11/11 + 84/84; abort output now contains only the actionable message.
- **Committed in:** 2fc8083, f23fa29

**2. [Minor] SUMMARY filename**
- Plan `<output>` line says `01-PLAN-02-SUMMARY.md`; every artifact in this phase uses `NN-NN` naming (`01-01-SUMMARY.md`, `01-02-PLAN.md`) and the orchestrator/tooling expect `01-02-SUMMARY.md` — treated as a planner typo and followed the convention.

---

**Total deviations:** 1 auto-fixed (Rule 2 — information disclosure), 1 naming note.
**Impact on plan:** The Rule 2 fix tightens the plan's own prohibition (T-01-04 mitigate disposition); no scope creep.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- RELI-01 complete; suite at 84 passing (73 pre-existing + 11 new).
- Ready for 01-03 (RELI-02 concurrency proof) — sibling plan, independent of this surface.

---
*Phase: 01-gateway-runtime-hardening*
*Completed: 2026-09-08*

## Self-Check: PASSED

All key-files exist on disk; all 6 task commits present in git log; all acceptance criteria re-verified green (targeted 11/11, full suite 84/84).
