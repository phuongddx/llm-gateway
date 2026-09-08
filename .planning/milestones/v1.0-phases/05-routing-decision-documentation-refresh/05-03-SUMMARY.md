---
phase: 05-routing-decision-documentation-refresh
plan: 03
subsystem: docs
tags: [deployment, docker, compose, testing, providers, env-vars]

# Dependency graph
requires:
  - phase: 03-docker-compose-observability
    provides: real Dockerfile/docker-compose.yml/Makefile docker-* targets and /health/ready HEALTHCHECK
  - phase: 04-retry-rate-limit-observability
    provides: real /health/live + /health/ready split, RATE_LIMIT_PER_KEY
provides:
  - "docs/deployment-guide.md documenting the real 12-variable config.py Settings surface and the real Docker/Compose deployment"
  - "docs/code-standards.md documenting the real 4-file provider layout, if/else factory, nested error-frame shape, and ASGITransport-based testing"
affects: [documentation, onboarding]

# Actuals (#2632)
actuals:
  tokens: 4172
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - docs/deployment-guide.md
    - docs/code-standards.md

key-decisions:
  - "Rules bullet for provider file-name example switched from stale openai_provider.py to manifest.py (real file) -- in scope as part of the same File Organization section being corrected"
  - "Error Handling section's unknown-model/unknown-provider bullets rewritten to describe the real passthrough behavior rather than simply deleted, since resolve_provider()/create_provider() never raise and the doc should say what actually happens"
  - "Deferred (not fixed): docs/deployment-guide.md's pre-existing '401 Unauthorized' section still claims APP_API_KEY defaults to changeme; the real config.py default is empty string (tests/conftest.py monkeypatches it). Out of scope for this plan's six listed corrections -- logged to deferred-items.md"

patterns-established: []

requirements-completed: [DOCS-02]

coverage:
  - id: D1
    description: "docs/deployment-guide.md's Environment Variables Reference lists exactly the 12 real config.py Settings fields with zero stale per-provider key/base-URL tables or LLM_PROVIDER/LLM_MODEL/LLM_BASE_URL legacy vars, and documents the real Docker/Compose deployment (Makefile targets, gateway-data volume, /health/ready HEALTHCHECK, optional observability profile)"
    requirement: "DOCS-02"
    verification:
      - kind: other
        ref: "grep -c 'OPENAI_API_KEY|DEEPSEEK_API_KEY|MOONSHOT_API_KEY|BYTEDANCE_API_KEY|GLM_API_KEY|LLM_PROVIDER|LLM_MODEL|LLM_BASE_URL' docs/deployment-guide.md -> 0; grep -c 'ZAI_CODING_API_KEY' -> 4; grep -c 'docker compose --profile observability' -> 1; grep -c 'Docker (Future)' -> 0; grep -c '/health/ready' -> 2"
        status: pass
    human_judgment: false
  - id: D2
    description: "docs/code-standards.md's file tree, 'Adding a New Provider' recipe, error handling, and testing sections match the shipped 4-file provider layout, if/else factory dispatch, nested SSE error-frame shape, and ASGITransport + real-token test auth pattern -- test-file enumeration matches tests/*.py live at execution time"
    requirement: "DOCS-02"
    verification:
      - kind: other
        ref: "grep -c 'openai-provider.py' -> 0; grep -c 'providers/manifest.py' -> 1; grep -c 'MODEL_PRICING' -> 0; grep -c 'zai_coding.py' -> 3; grep -c 'ASGITransport' -> 1; grep -c 'dependency override' -> 0; TESTLIST_MATCH (15 live tests/*.py == 15 enumerated in doc)"
        status: pass
    human_judgment: false

# Metrics
duration: 2min
completed: 2026-09-08
status: complete
---

# Phase 5 Plan 3: Deployment Guide & Code Standards Documentation Refresh Summary

**Rewrote docs/deployment-guide.md's env-var reference and Docker section to match the shipped 12-field Settings class and real Docker/Compose setup, and docs/code-standards.md's file tree, provider recipe, error handling, and testing sections to match the shipped 4-file provider layout and live tests/*.py enumeration.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-09-08T14:59:48Z (immediately after 05-02 landed)
- **Completed:** 2026-09-08T15:01:01Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `docs/deployment-guide.md`'s Environment Variables Reference now lists exactly the real 12 `config.py` `Settings` fields (`APP_API_KEY` through `ANALYTICS_RETENTION_DAYS`) in one consolidated table, with the dead "Core Settings" / "Provider API Keys" / "Legacy Settings (still supported)" / "Default Models by Provider" subsections removed entirely (the "still supported" `LLM_PROVIDER`/`LLM_MODEL`/`LLM_BASE_URL` claim was false -- `config.py` defines no such fields).
- Replaced the placeholder "Docker (Future) -- Not yet implemented" section with a real "Docker / Compose Deployment" section documenting `make docker-build`/`docker-up`/`docker-down`, the multi-stage non-root `python:3.12-slim` image, the `gateway-data` named volume, `env_file: .env`, the `/health/ready` `HEALTHCHECK`, and the opt-in `docker compose --profile observability up` Prometheus sidecar.
- Fixed the Direct Deployment secrets export and the SSE-error troubleshooting section to reference `MANIFEST_API_KEY`/`ZAI_CODING_API_KEY` (with `LLM_API_KEY` fallback) instead of dead `OPENAI_API_KEY`/`DEEPSEEK_API_KEY`/`GLM_API_KEY` names, and corrected the health-check bullet to `/health/live` + `/health/ready`.
- `docs/code-standards.md`'s Naming Conventions table now shows `snake_case` Python files (`manifest.py`, `zai_coding.py`) instead of the stale kebab-case claim, and corrected constant/env-var examples (`GLM_CANONICAL` instead of the removed `MODEL_PRICING`).
- File Organization tree replaced the 7-provider list (`gemini.py`/`openai_provider.py`/`deepseek.py`/`moonshot.py`/`bytedance.py`/`glm.py`/`minimax.py`) with the real 4 files (`base.py`, `openai_compatible_base.py`, `manifest.py`, `zai_coding.py`), and the `tests/` file list was enumerated live via `ls tests/*.py` at execution time (15 files, including `test_analytics_retention.py`, `test_analytics_writer.py`, `test_config.py`, `test_metrics.py`, `test_openai_compatible_base.py`, `test_playground.py`, `test_providers.py`, `test_rate_limiting.py`, and `test_startup_validation.py` that the old hardcoded 6-file list omitted).
- "Adding a New Provider" recipe's factory-registration step now shows the real `if`/`elif`/`else` dispatch in `providers/__init__.py` instead of a nonexistent `match` statement, and the obsolete "Add pricing" step (referencing the removed `MODEL_PRICING`) was deleted with the remaining steps renumbered.
- Error Handling section's false "returns 400"/"returns 500" claims for unknown model/provider were replaced with the real passthrough behavior (`resolve_provider()`/`create_provider()` never raise), and the error-frame code example now matches the real nested `{"error": {"message", "type"[, "code"]}}` shape built in `routes/chat.py`'s `_tracked_stream()`.
- Testing Guidelines corrected to describe `httpx.AsyncClient` over `ASGITransport` (not FastAPI's sync `TestClient`) and the real `auth_headers()` fixture supplying a matching Bearer token (no `app.dependency_overrides` usage anywhere in the codebase); its "Test structure" list uses the same live 15-file enumeration.

## Task Commits

Each task was committed atomically:

1. **Task 1: Correct docs/deployment-guide.md's env surface and Docker section** - `ce7d7ba` (docs)
2. **Task 2: Correct docs/code-standards.md's naming, file tree, provider recipe, error handling, and testing sections** - `7415920` (docs)

**Plan metadata:** pending (this SUMMARY's own commit)

## Files Created/Modified

- `docs/deployment-guide.md` - 12-variable env-var reference table, real Docker/Compose section, corrected secrets export and SSE-error troubleshooting
- `docs/code-standards.md` - snake_case naming table, 4-file provider tree, live-enumerated tests/ list, if/else factory recipe (no pricing step), corrected error-handling and testing-guidelines sections
- `.planning/phases/05-routing-decision-documentation-refresh/deferred-items.md` - new file logging one out-of-scope stale doc claim found during Task 1 (created, not part of this plan's `files_modified`)

## Decisions Made

- Extended the "Rules" bullet's provider file-name example from the stale `openai_provider.py` to the real `manifest.py`, since it sits in the same File Organization section already being corrected and the plan's overall truth requires the file tree/recipe to match the shipped layout exactly.
- Rewrote (rather than bare-deleted) the Error Handling section's unknown-model/unknown-provider bullets to state the real passthrough behavior, since simply removing them would leave the doc silent on what actually happens for those inputs.
- Deferred docs/deployment-guide.md's pre-existing "Default `APP_API_KEY` is `changeme`" claim (real default is `""`, per `config.py` and `tests/conftest.py`'s explicit monkeypatch comment) -- not one of this plan's six listed corrections; logged to `deferred-items.md` per the scope-boundary rule instead of fixed.

## Deviations from Plan

None affecting scope or acceptance criteria - plan executed exactly as written for both tasks. One pre-existing, out-of-scope documentation inaccuracy was discovered and logged (not auto-fixed) per the scope-boundary rule; see Decisions Made and `deferred-items.md`.

## Issues Encountered

- First attempt at the "Testing Guidelines" test-structure code block accidentally replaced the `tests/` root line along with the file list (the touched range started at that line), leaving the fenced block missing its top-level directory name. Caught on re-read before verification/commit and corrected with a one-line insert restoring `tests/` as the block's first line.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `docs/deployment-guide.md` and `docs/code-standards.md` are current with the shipped Phase 3/4 Docker/Compose deployment, the real env surface, and the real 4-file provider layout.
- Full test suite re-run after both doc-only commits: 142 passed, unaffected (docs changes carry no runtime surface).
- No blockers for remaining Phase 5 work.

---
*Phase: 05-routing-decision-documentation-refresh*
*Completed: 2026-09-08*

## Self-Check: PASSED

All claimed files and commits verified to exist:
- FOUND: docs/deployment-guide.md
- FOUND: docs/code-standards.md
- FOUND: .planning/phases/05-routing-decision-documentation-refresh/05-03-SUMMARY.md
- FOUND: .planning/phases/05-routing-decision-documentation-refresh/deferred-items.md
- FOUND commit: ce7d7ba
- FOUND commit: 7415920
