---
phase: 01-gateway-runtime-hardening
plan: 2
type: execute
wave: 2
depends_on: ['01-PLAN-01-tracer-bounded-writer-error-frames']
files_modified:
  - config.py
  - main.py
  - tests/test_startup_validation.py
autonomous: true
requirements:
  - RELI-01
estimate:
  tokens: 22000
  raw_tokens: 22000
  tasks: 2
  confidence: low

must_haves:
  truths:
    - 'TR1 (RELI-01a): Settings(_env_file=None, rate_limit="bogus/zzz") raises pydantic ValidationError whose message contains "RATE_LIMIT" and the offending value, with a valid example in the message; "60/minute, 1000/hour" and the "60/minute" default construct cleanly — validation fires at Settings construction (import of config), strictly before any slowapi Limiter can lazily accept the same bad string at request time.'
    - 'TR2 (RELI-01b): Starting with APP_API_KEY unset → lifespan raises RuntimeError containing "APP_API_KEY" before db.initialize() and before writer.start(); under uvicorn this aborts startup (<1s, exit code 3 — probe-verified) instead of a request-time SDK stack trace.'
    - 'TR3 (RELI-01c): No effective z.ai key (empty ZAI_CODING_API_KEY and empty LLM_API_KEY) → logger.warning naming ZAI_CODING_API_KEY/LLM_API_KEY and the Manifest degradation, and startup COMPLETES (no abort); same semantics for a missing effective Manifest key (MANIFEST_API_KEY/LLM_API_KEY) — zero-key dev/test runs keep working (opt-in/rollback-by-unset preserved).'
    - 'TR4 (RELI-01d): Unwritable ANALYTICS_DB_PATH parent → RuntimeError containing "ANALYTICS_DB_PATH" and the offending path, raised before AnalyticsDB construction.'
    - 'TR5 (edge RELI-01/concurrency, explicit): Startup validation is deterministic and side-effect-free on failure — re-invoking the failed startup raises the identical variable-naming error, and every abort path runs before AnalyticsDB.initialize()/AnalyticsWriter.start(), so an interrupted or parallel startup with bad config leaves no partial DB/writer state.'
    - 'TR6: Settings.model_config does NOT gain validate_assignment — tests monkeypatch the module singleton (verified-mutable pydantic v2 behavior) and would break otherwise.'
  artifacts:
    - tests/test_startup_validation.py
    - config.py
    - main.py
  key_links:
    - 'config.Settings model_validator (via limits.parse_many — the exact parser slowapi itself enforces with, so validation and enforcement cannot drift) → fires at import of config, which precedes every Limiter import in the module graph (main.py:13 vs rate_limiter.py:6)'
    - 'main.py lifespan → settings.get_api_key("zai-coding") / get_api_key("manifest") effective-key semantics (dedicated key or LLM_API_KEY fallback) for the two no-abort notices'
    - 'main.py lifespan abort ordering → all aborts precede db.initialize() and writer.start(); notices precede the writable check; writable check precedes AnalyticsDB construction'
  prohibitions:
    - requirement_id: RELI-01
      category: privacy
      status: resolved
      verification: test
      resolution: null
      reason: null
      statement: 'MUST NOT include secret VALUES (API key contents, even partially masked) in startup notices, abort messages, or any log output — messages name env VARIABLES only; a test sets sentinel key values and asserts the sentinels never appear in captured startup logs or raised messages (specless-probe kept prohibition, descriptor-less / flagged-unverified).'
---

<objective>
RELI-01: the operator-facing startup validation surface. Bad config fails fast at startup naming the variable; missing optional provider keys degrade with explicit notices, never aborts. Implements the LOCKED CONTEXT decision "Startup Validation Surface" exactly: validation split between a pure pydantic Settings model_validator (RATE_LIMIT parseability) and lifespan checks (APP_API_KEY abort [exists — extend, don't redesign], ANALYTICS_DB_PATH parent writable abort, zai/manifest no-key notices).

Purpose: eliminate the probe-verified failure mode where a typo'd RATE_LIMIT is accepted by slowapi at construction AND decoration, then explodes cryptically at request time. The split matters: every existing config unit test constructs Settings(_env_file=None, **kw) with no app_api_key — putting the APP_API_KEY abort in the model_validator would break them and zero-key runs (01-RESEARCH.md Pattern 2).

Output: config.py validator, main.py lifespan checks + notices, and tests/test_startup_validation.py proving RELI-01a–d.
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
  <name>Task 1: RATE_LIMIT model_validator in Settings (RELI-01a) — RED first</name>
  <files>config.py, tests/test_startup_validation.py</files>
  <read_first>
  - .planning/phases/01-gateway-runtime-hardening/01-CONTEXT.md — locked decision "Startup Validation Surface"
  - .planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md — "Pattern 2: Validation split" (verified ValidationError output format), Pitfalls 2/3/10, "RELI-01 lifespan test skeletons"
  - .planning/phases/01-gateway-runtime-hardening/01-PATTERNS.md — section "config.py"
  - config.py (full file — field layout, model_config, get_api_key, import-time singleton)
  - tests/test_config.py lines 1-22 (the _settings(_env_file=None, **kw) helper convention every config test uses)
  </read_first>
  <behavior>
  - test_rate_limit_validator_rejects_garbage: Settings(_env_file=None, rate_limit="bogus/zzz") raises ValidationError matching "RATE_LIMIT".
  - test_rate_limit_validator_rejects_wrong_granularity: Settings(_env_file=None, rate_limit="60/fortnight") raises ValidationError.
  - test_rate_limit_validator_rejects_bare_number: Settings(_env_file=None, rate_limit="60") raises ValidationError.
  - test_rate_limit_validator_accepts_multi_limit: Settings(_env_file=None, rate_limit="60/minute, 1000/hour") constructs.
  - test_settings_default_constructs_without_app_api_key: Settings(_env_file=None) constructs with rate_limit "60/minute" — zero-key test runs keep working (the split rationale).
  </behavior>
  <action>
  RED: create tests/test_startup_validation.py with the behavior tests (one-line module docstring "Unit tests for startup validation — Settings validator and lifespan checks."), a module-local helper mirroring tests/test_config.py:6-7 that constructs Settings(_env_file=None, **kw); run — they must fail (validator does not exist yet). GREEN: in config.py add imports limits.parse_many (third-party group; limits is already installed as slowapi's dependency — NOT a new dependency) and pydantic.model_validator; add a mode="after" model validator method on Settings (snake_case, e.g. _validate_rate_limit) that: parses list(parse_many(self.rate_limit)) inside try/except ValueError, re-raising ValueError with a message that names RATE_LIMIT, shows the bad value with repr, shows a valid example ("60/minute"), and chains from the original; additionally raises ValueError when parsing yields zero limits; returns self on success. Use the exact message shape from 01-RESEARCH.md Pattern 2 (probe-verified output on the installed pydantic-settings 2.13.1: the ValidationError text contains "RATE_LIMIT is not a valid rate string"). Do NOT move the APP_API_KEY abort into the validator (lifespan owns it — locked decision); do NOT add validate_assignment to model_config. Existing tests/test_config.py must stay green untouched.
  </action>
  <verify>
    <automated>.venv/bin/python -m pytest tests/test_startup_validation.py -v && .venv/bin/python -m pytest tests/test_config.py -v</automated>
    <fails_when>non-zero exit code, or any test reports FAIL in either summary — the three rejection cases must fail with ValidationError naming RATE_LIMIT before the implementation, and pass after</fails_when>
  </verify>
  <acceptance_criteria>
  - tests/test_startup_validation.py exists; .venv/bin/python -m pytest tests/test_startup_validation.py -v exits 0 with the five behavior tests present.
  - grep -c "model_validator" config.py returns >= 1 and grep -c "parse_many" config.py returns >= 2 (import + call).
  - The validator aborts at construction, not import-of-slowapi time: .venv/bin/python -c "from config import Settings; Settings(_env_file=None, rate_limit='bogus/zzz')" exits non-zero with a traceback containing RATE_LIMIT.
  - grep -c "validate_assignment" config.py returns 0.
  - tests/test_config.py passes unchanged (grep -c "" shows no modification: git diff --stat tests/test_config.py is empty).
  </acceptance_criteria>
  <done>Malformed RATE_LIMIT fails at Settings construction with an actionable message naming the variable; valid strings (including multi-limit) and the no-app_api_key construction keep working; existing config tests green.</done>
  <reversibility rating="reversible">One validator method + imports; git revert restores behavior.</reversibility>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Lifespan checks — writable-path abort, key notices, APP_API_KEY pin (RELI-01b/c/d)</name>
  <files>main.py, tests/test_startup_validation.py</files>
  <read_first>
  - .planning/phases/01-gateway-runtime-hardening/01-CONTEXT.md — locked decision "Startup Validation Surface" (notice-vs-abort semantics)
  - .planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md — "Pattern 5: Lifespan wiring and ordering" (extends the exact current lifespan), "RELI-01 lifespan test skeletons", Pitfall 10 (settings mutation), Open Question 2 (notice wording)
  - main.py (current lifespan — APP_API_KEY abort at lines 23-24 exists; Plan-01 wiring already landed: writer start/stop)
  - config.py (get_api_key effective-key semantics, lines 32-38)
  - tests/test_startup_validation.py (Task 1 of this plan)
  </read_first>
  <behavior>
  - test_missing_app_api_key_aborts_naming_variable: with settings.app_api_key monkeypatched empty and analytics_db_path pointed at tmp_path, async with lifespan(app) raises RuntimeError matching "APP_API_KEY" (pins the existing abort — regression guard).
  - test_no_effective_zai_key_logs_notice_no_abort: app_api_key set, zai_coding_api_key and llm_api_key monkeypatched empty, tmp_path db path; caplog at WARNING contains a record mentioning ZAI_CODING_API_KEY and the Manifest degradation; startup completes (context manager exits normally).
  - test_no_effective_manifest_key_logs_notice_no_abort: same shape with manifest_api_key and llm_api_key empty; notice mentions MANIFEST_API_KEY; no abort.
  - test_unwritable_analytics_db_path_aborts: analytics_db_path inside a directory chmod 0o500 → RuntimeError matching "ANALYTICS_DB_PATH"; teardown restores 0o700 so tmp cleanup succeeds.
  - test_startup_abort_is_deterministic_and_side_effect_free: run the APP_API_KEY-abort lifespan twice; both raise RuntimeError matching "APP_API_KEY"; and the tmp_path db file was never created (abort precedes db.initialize()).
  - test_startup_logs_never_contain_secret_values: set zai/manifest/llm keys to distinct sentinel strings; run a successful startup; assert no sentinel appears in caplog.text (prohibition P-RELI-01).
  </behavior>
  <action>
  RED: append the behavior tests to tests/test_startup_validation.py (lifespan tests import from main: from main import lifespan, app; from config import settings; use monkeypatch.setattr on the module-level settings singleton — verified-mutable; every async test carries @pytest.mark.asyncio; pass a tmp_path-based analytics_db_path so tests never touch data/). Run — notices/writable tests must fail. GREEN: extend main.py lifespan exactly per Pattern 5: (1) keep the existing APP_API_KEY RuntimeError abort first; (2) immediately after it, two no-abort notices — if not settings.get_api_key("zai-coding"): logger.warning naming ZAI_CODING_API_KEY/LLM_API_KEY and stating GLM routes degrade to Manifest; if not settings.get_api_key("manifest"): logger.warning naming MANIFEST_API_KEY/LLM_API_KEY and stating non-GLM requests will fail upstream (wording per Open Question 2: variable names + routing consequence; never the key values); (3) after the existing parent-dir mkdir, add import os and a writability guard: if not os.access(parent, os.W_OK): raise RuntimeError containing ANALYTICS_DB_PATH and the parent path — placed before AnalyticsDB construction; (4) leave the Plan-01 writer wiring (start after db.initialize; stop before db.close) exactly as-is. For the unwritable-path test, create the read-only directory under tmp_path and restore writable permissions in the test's teardown (try/finally) so pytest tmp cleanup does not warn. Notices use logger (module logger in main) — capture with caplog.at_level(logging.WARNING).
  </action>
  <verify>
    <automated>.venv/bin/python -m pytest tests/test_startup_validation.py -v && .venv/bin/python -m pytest tests/ -v</automated>
    <fails_when>non-zero exit code, or any test reports FAIL — the abort tests must see RuntimeError naming APP_API_KEY / ANALYTICS_DB_PATH, the notice tests must see the warnings AND complete startup, and the sentinel test must find no secret value in captured logs</fails_when>
  </verify>
  <acceptance_criteria>
  - tests/test_startup_validation.py contains the six behavior tests; targeted run exits 0.
  - grep -c "os.access" main.py returns 1 and the RuntimeError message contains ANALYTICS_DB_PATH (source assertion: grep -F "ANALYTICS_DB_PATH parent directory is not writable" main.py matches 1 line).
  - grep -c "get_api_key" main.py returns 2 (zai + manifest notices) and both notices log at warning level via logger.warning.
  - The APP_API_KEY abort line is unchanged from the current main.py:23-24 text (grep -F "APP_API_KEY env var is required but not set" main.py matches 1 line).
  - Shutdown ordering from Plan 01 is intact: in main.py the writer stop call still precedes the db close call.
  - Full suite exits 0.
  </acceptance_criteria>
  <done>Every bad-config path aborts at startup naming the variable; missing optional keys log actionable notices without aborting; startup logs provably contain no secret values; full suite green.</done>
  <reversibility rating="reversible">Validation additions only; no behavior removed; single revert restores the old lifespan.</reversibility>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| environment → Settings | .env values are operator-controlled input validated at construction |
| config → logs | startup notices/aborts cross into operator-visible log output (must carry variable names, never secret values) |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-01-04 | Information Disclosure | startup notices / abort messages in main.py | medium | mitigate | Notices name env VARIABLES only; Task 2 includes a sentinel test asserting key values never appear in caplog (prohibition P-RELI-01) |
| T-01-05 | Misconfiguration | silently insecure runtime from bad env (empty auth already aborts; malformed RATE_LIMIT, unwritable DB path) | high | mitigate | Fail-fast validation naming the variable: model_validator for RATE_LIMIT (Task 1), lifespan aborts for APP_API_KEY/ANALYTICS_DB_PATH (Task 2) |
| T-01-06 | Denial of Service | validator itself blocking startup | low | accept | Both checks are pure/local (parse + os.access); NFR-04's 3s budget unaffected; abort path probe-verified <1s |

Canon note (specless prohibition probe): generic input-validation/injection canon (OWASP) and error-message information-disclosure canon are covered by the curated-message tests in 01-PLAN-01 and /gsd-secure-phase tooling; not minted as prohibitions here. No package installs this phase — no supply-chain row.
</threat_model>

<verification>
- .venv/bin/python -m pytest tests/test_startup_validation.py -v exits 0 (RELI-01a–d + determinism + sentinel coverage).
- Full suite .venv/bin/python -m pytest tests/ -v exits 0 (Plan-01 tests unaffected by the lifespan/validation additions).
- Manual spot-check (optional, non-blocking): APP_API_KEY= RATE_LIMIT=bogus/zzz .venv/bin/python -c "import config" shows the actionable ValidationError before any server bind.
</verification>

<success_criteria>
- RELI-01 fully proven: aborts name APP_API_KEY and ANALYTICS_DB_PATH; RATE_LIMIT fails at construction; notices fire for missing zai/manifest keys without aborting; no secret values in startup logs; existing config tests untouched and green.
</success_criteria>

## Artifacts this phase produces

Additions from this plan (complementing 01-PLAN-01's inventory):

- config.py — @model_validator(mode="after") method _validate_rate_limit on Settings (imports: limits.parse_many, pydantic.model_validator).
- main.py — lifespan: zai-coding and manifest no-key logger.warning notices (via settings.get_api_key); os.access(parent, os.W_OK) guard raising RuntimeError naming ANALYTICS_DB_PATH; import os.
- NEW tests/test_startup_validation.py — module helper Settings(_env_file=None, **kw); validator tests (reject bogus/fortnight/bare-number, accept multi-limit, default constructs) + lifespan tests (APP_API_KEY abort pin, zai/manifest notices, unwritable-path abort, determinism/no-side-effects, secret-sentinel absence).

<output>
Create `.planning/phases/01-gateway-runtime-hardening/01-PLAN-02-SUMMARY.md` when done.
</output>
