---
phase: 03-containerized-deployment-ci
plan: 2
subsystem: infra
tags: [github-actions, ci, ruff, pytest, docker, lint]

# Dependency graph
requires:
  - phase: 03-containerized-deployment-ci (plan 1)
    provides: Dockerfile (docker-build job target), the AsyncGenerator 3.12 import fix (the 3.12 test leg's permanent regression subject)
provides:
  - GitHub Actions CI (.github/workflows/ci.yml) gating every push/PR to main with lint + matrix tests (3.12/3.14) + a docker-build smoke, proven green end-to-end on origin main
affects: [future phases adding endpoints/dependencies (CI now gates their correctness), branch-protection setup (manual Settings->Branches step, still outstanding)]

# Actuals (#2632)
actuals:
  tokens: 3972
  tasks: 3
  commits: 6
  plan_head_before: 65c1c1f

# Tech tracking
tech-stack:
  added: [ruff==0.16.6 (CI-only, pinned; never in requirements.txt), actions/checkout@v7, actions/setup-python@v7]
  patterns: ["CI-pinned lint tool version verified in a throwaway parity venv (/tmp/ruffpin) before every push — never push a known-red pipeline", "inline # noqa: <CODE> for rule findings that are documented-intentional codebase conventions (FastAPI Depends()-in-defaults, broad streaming except-clause) rather than a lint config file (TR5 prohibits one)"]

key-files:
  created: [.github/workflows/ci.yml]
  modified: [main.py, analytics/__init__.py, providers/base.py, providers/openai_compatible_base.py, routes/analytics.py, routes/chat.py, tests/conftest.py, tests/test_providers.py, tests/test_analytics_retention.py, tests/test_chat_endpoint.py, tests/test_openai_compatible_base.py, tests/test_startup_validation.py]

key-decisions:
  - "Task 2 checkpoint (ruff SUS package-legitimacy verdict): APPROVED PINNED — ruff installed via `pip install ruff==0.16.6` in the CI lint job's install line, exact version pin, never added to requirements.txt (CI-only dependency, keeps NFR-02 slim-image discipline). Verified against pypi.org/project/ruff and github.com/astral-sh/ruff per the checkpoint's how-to-verify: maintainer Astral Software Inc., Development Status 5 - Production/Stable, first release 2022-11-04, adopted by FastAPI/pytest/pandas/scipy — the SUS signals (too-new, unknown-downloads) reflect weekly release cadence and a PyPI tooling data gap, not real risk."
  - "ruff 0.16.6's default rule surface is materially broader than the local 0.8.4 binary (I001/isort, UP035, C408, B008, BLE001, RUF015, RUF100 all enabled by default with zero config, verified empirically with --isolated). Reconciled without a lint config file (TR5 locked prohibition) using inline per-line # noqa: <CODE> suppressions for rules that flag documented-intentional codebase conventions (FastAPI Depends()-in-defaults is idiomatic DI per AGENTS.md, not a bug; the broad except Exception in the streaming handler is documented as must-never-crash-the-request)."
  - "CI test step uses `python -m pytest -q`, not bare `pytest -q` (the locked-decision skeleton's literal form) — bare pytest does not prepend the repo root to sys.path, so tests/conftest.py's `from analytics.db import AnalyticsDB` raised ModuleNotFoundError at collection in the live Actions run. Matches the Makefile's own documented invocation (`.venv/bin/python -m pytest`, AGENTS.md)."
  - "tests/conftest.py's client fixture now monkeypatches settings.app_api_key = \"changeme\" explicitly, rather than relying on a local, gitignored, non-committed .env happening to contain that exact value. 19 tests were silently dependent on ambient dev-machine state and 401'd in the clean CI checkout (no .env, no APP_API_KEY secret — none configured, by design)."

patterns-established:
  - "Pre-push ruff parity: never push a workflow pinning a lint tool version without first running that exact pinned version against the full tree in a throwaway venv — local dev tool versions drift from CI pins silently."
  - "Test fixtures must not depend on ambient, non-committed local files (.env) for correctness — pin required state explicitly via monkeypatch, matching the existing test_startup_validation.py convention."

requirements-completed: [DEPL-03]

coverage:
  - id: D1
    description: "GitHub Actions CI (.github/workflows/ci.yml) runs on push and pull_request to main with three jobs: lint (ruff==0.16.6 pinned), test (matrix 3.12/3.14, fail-fast disabled), docker-build (plain build smoke, no push/credentials)"
    requirement: "DEPL-03"
    verification:
      - kind: other
        ref: "https://github.com/phuongddx/llm-gateway/actions/runs/34214982716 (pushed run on origin main, sha 4632089)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The lint job is born green (four pre-existing ruff findings from 03-01+this plan fixed, plus 22 additional findings surfaced by the CI-pinned ruff 0.16.6's broader default rule set, reconciled without a lint config file) and its supply chain (ruff, SUS verdict) was human-verified before adoption via the Task 2 blocking checkpoint"
    requirement: "DEPL-03"
    verification:
      - kind: other
        ref: "lint job, run 34214982716 — conclusion success"
        status: pass
    human_judgment: false
  - id: D3
    description: "The 3.12 test leg is the permanent regression test for the AsyncGenerator annotation blocker (03-01) and now also proves the full suite is CI-environment-clean (no ambient .env/credential dependency)"
    requirement: "DEPL-03"
    verification:
      - kind: other
        ref: "test (3.12) job, run 34214982716 — conclusion success, 117 passed"
        status: pass
    human_judgment: false

duration: ~35min (this continuation session; Task 1 was committed in a prior session)
completed: 2026-09-08
status: complete
---

# Phase 3 Plan 2: GitHub Actions CI Summary

**GitHub Actions CI (lint + matrix tests + docker-build) proven green end-to-end on origin main, with ruff pinned to 0.16.6 per the approved checkpoint decision and three previously-invisible CI-only failure modes fixed along the way.**

## Performance

- **Duration:** ~35 min (this continuation, resuming from the Task 2 checkpoint; Task 1 was completed and committed in a prior session)
- **Started:** 2026-09-08 (resumed at Task 2 checkpoint)
- **Completed:** 2026-09-08T10:22:18Z
- **Tasks:** 3/3 (Task 1 previously committed; Task 2 decision recorded this session; Task 3 executed this session)
- **Files modified:** 13 (1 created, 12 modified) across this plan's full commit range

## Accomplishments
- `.github/workflows/ci.yml` live on origin main: lint (ruff==0.16.6 pinned) + test (matrix 3.12/3.14, fail-fast disabled) + docker-build (plain smoke, no push/credentials) — DEPL-03 satisfied
- Task 2 checkpoint resolved: ruff's SUS package-legitimacy verdict human-verified and approved, pinned to the exact current version (0.16.6) rather than floating latest
- Reconciled a real, empirically-verified gap between the plan's TR2 assumption ("ruff 0.8.4 and the CI-pinned version show the same 4 findings") and ruff 0.16.6's actual, much broader default rule set (26 findings) — fixed 16 mechanically (import sort, dead dict() call, deprecated typing import) and suppressed 10 documented-intentional-pattern findings inline, all without adding a prohibited lint config file
- Found and fixed two additional CI-only failure modes that never surfaced locally: bare `pytest -q`'s missing sys.path repo-root insertion (ModuleNotFoundError), and 19 tests silently depending on a gitignored local `.env`'s `APP_API_KEY=changeme` value that doesn't exist in a clean CI checkout
- Green run recorded: https://github.com/phuongddx/llm-gateway/actions/runs/34214982716 (sha `4632089`) — lint, test (3.12), test (3.14), docker-build all `success`

## Task Commits

Task 1 (prior session):
1. **Task 1: Lint-green dead-symbol removal** - `a4d5fa4` (fix) — unused fastapi import + dead analytics re-exports

Task 2 (this session — checkpoint decision, no code artifact):
- Human decision relayed and recorded: **"Approved pinned"** — ruff pinned to exact version 0.16.6 in the CI install line, CI-only (never in requirements.txt)

Task 3 (this session):
2. **Provider-factory test isolation fix** - `03781c0` (fix) — dispatch tests no longer depend on ambient credential env vars
3. **ruff 0.16.6 vs 0.8.4 default-rule-set reconciliation** - `d3e5a0b` (fix) — 26 findings resolved without a lint config file
4. **Author ci.yml** - `a074a87` (feat) — lint + matrix test + docker-build, ruff pinned per Task 2 decision
5. **Fix CI pytest invocation** - `d5fd328` (fix) — `python -m pytest` not bare `pytest` (sys.path)
6. **Fix client fixture auth isolation** - `4632089` (fix) — pin `settings.app_api_key` instead of relying on ambient `.env`

_Note: Task 3 required 4 additional commits beyond the initial ci.yml authoring — each is a genuine CI-environment-only bug (never reproducible on the dev workstation's ambient state) discovered by the mandatory pre-push parity check and the live Actions run itself, fixed per deviation Rule 1/3 before the pipeline could be considered provably green._

## Files Created/Modified
- `.github/workflows/ci.yml` - CI workflow: lint (ruff==0.16.6 pinned) + test (matrix 3.12/3.14) + docker-build
- `main.py` - deferred router imports reconciled for E402/RUF100 across both ruff versions (Task 1's dead-import fix already landed)
- `providers/base.py` - `AsyncGenerator` moved to `collections.abc` (UP035, matches the 03-01 precedent in openai_compatible_base.py)
- `providers/openai_compatible_base.py` - `dict(...)` call rewritten as a literal (C408)
- `routes/analytics.py`, `routes/chat.py` - inline `# noqa: B008` / `# noqa: BLE001` on documented-intentional FastAPI DI / broad-except patterns
- `tests/conftest.py` - `client` fixture now pins `settings.app_api_key = "changeme"` explicitly
- `tests/test_providers.py` - dispatch tests pass an explicit dummy `api_key` instead of relying on ambient credential resolution
- `tests/test_analytics_retention.py`, `tests/test_chat_endpoint.py`, `tests/test_openai_compatible_base.py`, `tests/test_startup_validation.py` - import-sort fixes (I001) + 2x inline `# noqa: RUF015`

## Decisions Made
- Task 2 checkpoint: ruff adopted **pinned** to `0.16.6` (RESEARCH's A5 recommendation and the default option) rather than floating latest — a future ruff release adding rules can never redden CI unexpectedly.
- Version-skew reconciliation favored the CI-pinned ruff (0.16.6, what Actions actually executes) as the authority for whether the pipeline goes green; local 0.8.4 was also kept green wherever achievable without a lint config file (TR5), including a combined `# noqa: E402,RUF100` where the two versions' own default rule sets genuinely disagree on whether E402 applies.
- `python -m pytest -q` replaces the locked skeleton's literal `pytest -q` in the test job — a CI-environment-only sys.path gap invisible on the dev workstation (which always invokes `python -m pytest`, per the Makefile).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Provider-factory dispatch tests silently depended on ambient credential env state**
- **Found during:** Task 3 pre-push suite re-verification (env-stripped parity check)
- **Issue:** `test_factory_returns_zai_coding_provider` / `test_factory_falls_back_to_manifest_for_other_names` call `create_provider(...)` with no explicit `api_key`; `openai>=1.60.0` (unpinned in requirements.txt) resolves to a fresh `openai` major (3.8.0 in this run) whose `AsyncOpenAI` construction raises eagerly on an explicit empty-string `api_key`, unlike the older SDK on this workstation. Reproduced deterministically with credential env vars stripped, matching a clean CI runner (no `.env`, no secrets).
- **Fix:** Tests now pass an explicit dummy `api_key="test-key"` to `create_provider(...)`, isolating dispatch-logic tests from credential resolution entirely.
- **Files modified:** `tests/test_providers.py`
- **Verification:** Both `.venv` (3.14) and `/tmp/gw312` (3.12) suites 117/117 with `OPENAI_API_KEY`/`OPENAI_ADMIN_KEY`/`ZAI_API_KEY` unset.
- **Committed in:** `03781c0`

**2. [Rule 1/3 - Bug/Blocking] ruff 0.16.6 (CI-pinned) default rule set differs materially from local 0.8.4**
- **Found during:** Task 3's mandated pre-push parity check (`/tmp/ruffpin` running the exact pinned version)
- **Issue:** 26 findings under `ruff==0.16.6 --isolated` that were invisible under the local 0.8.4 binary: I001 (isort, 13x), B008 (Depends-in-default, 6x — FastAPI idiom, not a bug), RUF015 (2x), RUF100 (2x), BLE001 (1x — documented-intentional per AGENTS.md), UP035 (1x), C408 (1x). Left unresolved, the pinned CI lint job would have been red on push — the opposite of DEPL-03's purpose, and explicitly disallowed by the Task 3 verify step ("never push a known-red pipeline").
- **Fix:** 16 mechanical/safe fixes applied (import sorting, dict-literal rewrite, `collections.abc` migration matching the 03-01 precedent); 10 documented-intentional-pattern findings suppressed with per-line `# noqa: <CODE>` comments (no lint config file added — TR5 prohibits one). The pre-existing `main.py` E402 suppression needed reconciling in the opposite direction simultaneously for both pinned versions (0.8.4 requires it, 0.16.6 flags it unused) — resolved with a combined `# noqa: E402,RUF100` that satisfies both.
- **Files modified:** `main.py`, `providers/base.py`, `providers/openai_compatible_base.py`, `routes/analytics.py`, `routes/chat.py`, `tests/test_analytics_retention.py`, `tests/test_chat_endpoint.py`, `tests/test_openai_compatible_base.py`, `tests/test_startup_validation.py`
- **Verification:** `ruff check .` exits 0 under both `/tmp/ruffpin` (0.16.6) and the local 0.8.4 binary; both suites 117/117 credential-env-stripped.
- **Committed in:** `d3e5a0b`

**3. [Rule 3 - Blocking] Bare `pytest -q` fails at collection in the live Actions runner**
- **Found during:** Task 3, first pushed run (`34214650746`) — `test (3.12)` and `test (3.14)` both failed with exit code 4
- **Issue:** `ModuleNotFoundError: No module named 'analytics'` loading `tests/conftest.py`. Bare `pytest -q` does not prepend the invocation CWD to `sys.path[0]`; only `python -m pytest` does. The locked ci.yml skeleton's literal `run: pytest -q` never surfaced this locally because every local verification in this plan (and the Makefile's own `make test` target) invokes `python -m pytest`.
- **Fix:** Changed the test job's step to `run: python -m pytest -q`.
- **Files modified:** `.github/workflows/ci.yml`
- **Verification:** Reproduced locally with `.venv/bin/pytest -q` (bare, fails identically) vs `.venv/bin/python -m pytest -q` (passes); re-pushed run confirmed the import error was gone.
- **Committed in:** `d5fd328`

**4. [Rule 1 - Bug] 19 tests depended on a gitignored, non-committed `.env`'s incidental `APP_API_KEY=changeme` value**
- **Found during:** Task 3, second pushed run (`34214795627`) — 19 failures, all `401 == 200` / `Invalid API key`
- **Issue:** `tests/conftest.py`'s `auth_headers` fixture hardcodes `Bearer changeme`; nothing in the test setup ever configured `settings.app_api_key` to match. It only worked on this workstation because the local, gitignored `.env` happened to contain `APP_API_KEY=changeme` (`.env.example` ships an empty placeholder). CI checks out a clean tree with no `.env` and, by design, no `APP_API_KEY` secret (build-only workflow, no secrets block) — `settings.app_api_key` defaults to `""`, so every authenticated request 401'd.
- **Fix:** `client` fixture now `monkeypatch.setattr(settings, "app_api_key", "changeme")` explicitly, using the same `settings` singleton and the same `monkeypatch.setattr` idiom already established in `tests/test_startup_validation.py`.
- **Files modified:** `tests/conftest.py`
- **Verification:** Full suite 117/117 on both `.venv` and `/tmp/gw312` with `.env` moved out of the tree entirely and a fully stripped shell environment (`env -i PATH=... HOME=...`) — the closest local approximation of the actual CI runner's state.
- **Committed in:** `4632089`

---

**Total deviations:** 4 auto-fixed (1 Rule 1 test-isolation bug, 1 Rule 1/3 lint-version-skew reconciliation, 2 Rule 3 CI-only blocking bugs)
**Impact on plan:** All four were genuine, previously-invisible gaps between "passes on the dev workstation" and "passes in a clean GitHub Actions checkout" — exactly the class of defect DEPL-03 exists to catch going forward. None were scope creep: each was strictly necessary to make the pinned-CI pipeline provably green, which is the plan's own explicit, non-negotiable acceptance bar ("never push a known-red pipeline"). No application runtime behavior changed; all fixes are test-isolation, CI-workflow, or lint-suppression only.

## Issues Encountered
See Deviations above — all four issues were CI-environment-only failure modes that could not have been caught by any local check available before Task 3's mandated pre-push parity venv and the live pushed run itself surfaced them. Each was root-caused with a targeted local reproduction (stripped env vars, bare `pytest` vs `python -m pytest`, `.env` removed) before being fixed, matching the plan's "never push a known-red pipeline" bar at every step.

## User Setup Required
None — no external service configuration required. One manual operator step remains **out of scope by the plan's own design**: requiring these checks on `main` (branch protection under Settings → Branches) has not been configured and needs a human with repo admin access.

## Next Phase Readiness
- DEPL-03 is fully satisfied and proven: https://github.com/phuongddx/llm-gateway/actions/runs/34214982716 (sha `4632089`) — lint, test (3.12), test (3.14), docker-build all `success`.
- The 3.12 test leg is now the permanent regression test for both the AsyncGenerator annotation blocker (03-01) and CI-environment cleanliness (this plan) — any future undefined-annotation regression or ambient-state test dependency will redden this leg before reaching a deployed container.
- Outstanding, flagged, out-of-scope: branch protection on `main` requiring these checks (manual Settings → Branches operator action).
- Phase 3 (both plans) is now complete: DEPL-01/02 (03-01, container + compose, operator-verified locally) and DEPL-03 (this plan, CI proven green on origin main).

---
*Phase: 03-containerized-deployment-ci*
*Completed: 2026-09-08*

## Self-Check: PASSED
All 6 plan commits (a4d5fa4, 03781c0, d3e5a0b, a074a87, d5fd328, 4632089) verified present in git log. SUMMARY.md file verified on disk.
