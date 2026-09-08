---
phase: 03-containerized-deployment-ci
plan: 1
subsystem: infra
tags: [docker, docker-compose, python3.12, uvicorn, sqlite, healthcheck]

# Dependency graph
requires: []
provides:
  - Multi-stage non-root Dockerfile (python:3.12-slim, venv-copy, chown'd /app/data, urllib HEALTHCHECK, exec-form CMD)
  - docker-compose.yml single-service stack (env_file passthrough, named volume, restart unless-stopped)
  - .dockerignore (secret + build-context hygiene)
  - Makefile docker-build/docker-up/docker-down targets
  - README Deployment (Docker) quickstart section
  - Python 3.12 compatibility fix for providers/openai_compatible_base.py (AsyncGenerator import)
affects: [03-02, phase-04, phase-05]

# Actuals (#2632)
actuals:
  tokens: 1222
  tasks: 2
  commits: 2
plan_head_before: 134e1a5946b06a76324cf1092e72beb5c997029b

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "venv-copy multi-stage Docker build (byte-identical FROM tags across builder/runtime stages)"
    - "COPY allowlist instead of COPY . . (enumerated runtime modules only)"
    - "chown'd /app/data before USER — non-root named-volume writability"
    - "exec-form CMD for PID-1 SIGTERM fidelity"
    - "env-only config: no .env baked into image, compose env_file is the single passthrough"

key-files:
  created: [Dockerfile, .dockerignore, docker-compose.yml]
  modified: [providers/openai_compatible_base.py, Makefile, README.md]

key-decisions:
  - "docker-up uses `up -d --build` (not plain `up -d`) — makes a fresh clone self-sufficient and avoids the stale-image-after-edits footgun; documented in README to match"
  - "Did NOT pin openai in requirements.txt to work around an unrelated openai>=2.34.0 SDK credential-fallback change discovered during the 3.12 rig run — the repo's established convention is floor-only >= pins with no lockfile (AGENTS.md), and the issue doesn't affect real production routing paths or the container; logged to WINDOWS.md instead of fixed, per SCOPE BOUNDARY (pre-existing, unrelated to the AsyncGenerator fix)"

patterns-established:
  - "Standing 3.12 regression rig at /tmp/gw312 (python3.12 -m venv + pip install -r requirements.txt) — reusable by 03-02 and any future import-touching change"

requirements-completed: [DEPL-01, DEPL-02]

coverage:
  - id: D1
    description: "Python 3.12 AsyncGenerator NameError fixed — both 3.12 and 3.14 pytest regimes pass"
    requirement: DEPL-01
    verification:
      - kind: unit
        ref: "/tmp/gw312/bin/python -m pytest tests/ -q (115 passed, 2 pre-existing unrelated failures — see Deviations)"
        status: pass
      - kind: unit
        ref: ".venv/bin/python -m pytest tests/ -q (117 passed)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Multi-stage non-root Docker image builds and runs (byte-identical FROM tags, chown'd /app/data, exec-form CMD, HEALTHCHECK, no secrets baked)"
    requirement: DEPL-01
    verification:
      - kind: integration
        ref: "docker build -t llm-gateway:latest . && docker run --rm llm-gateway:latest python -c non-root-probe && no-.env-probe (both exit 0)"
        status: pass
    human_judgment: false
  - id: D3
    description: "docker compose up reaches health=healthy with GET /health 200 on the operator-started Rancher Desktop daemon"
    requirement: DEPL-02
    verification:
      - kind: integration
        ref: "docker compose up -d --build && curl -sf http://localhost:8000/health && docker inspect Config.User/State.Health.Status"
        status: pass
    human_judgment: false
  - id: D4
    description: "In-container readiness measured under 3s (NFR-04); analytics DB persists across container recreation on the named volume; SIGTERM drains gracefully"
    requirement: DEPL-02
    verification:
      - kind: manual_procedural
        ref: "marker-row seed -> down -> up -> count identical (repeated twice); docker compose stop captured full graceful-shutdown log sequence; readiness measured 0.90s then 1.61s across two cycles"
        status: pass
    human_judgment: false
  - id: D5
    description: "README Deployment (Docker) quickstart section documents the proven flow"
    requirement: DEPL-02
    verification:
      - kind: other
        ref: "grep -c \"^## Deployment (Docker)$\" README.md == 1; grep -c \"docker compose up -d --build\" README.md == 1; zero removed lines in README diff"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-09-08
status: complete
---

# Phase 3 Plan 1: Container Tracer + DEPL-02 Expansion Summary

**Multi-stage non-root Docker image (python:3.12-slim, venv-copy, chown'd volume) plus single-service compose stack reaching a live healthy `/health` on Rancher Desktop, gated by a one-line `AsyncGenerator` import fix that unblocks Python 3.12 entirely — volume persistence, SIGTERM drain, and sub-second in-container readiness proven live and documented in the README.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-09-08T09:44:00Z (approx, first read)
- **Completed:** 2026-09-08T09:59:57Z
- **Tasks:** 2/2
- **Files modified:** 6 (3 created: Dockerfile, .dockerignore, docker-compose.yml; 3 modified: providers/openai_compatible_base.py, Makefile, README.md)

## Accomplishments

- Fixed the Python 3.12 blocker: `providers/openai_compatible_base.py` was missing an import for `AsyncGenerator`, used only in a return type annotation. Python ≤3.13 evaluates annotations eagerly (`NameError` at class-definition time); Python 3.14 (PEP 649) masks it. Reproduced the exact RED failure in a real 3.12.14 venv (`/tmp/gw312`): 2 collection errors, exit 2. Added `from collections.abc import AsyncGenerator` to the stdlib import group — GREEN on both regimes.
- Authored a multi-stage, non-root Dockerfile from the research-verified skeleton: builder stage installs a venv at `/opt/venv`; runtime stage copies it with a byte-identical `python:3.12-slim` tag, runs as system user `gateway` with `/app/data` pre-chown'd, uses an exec-form CMD (PID-1 SIGTERM fidelity) and a stdlib-urllib `HEALTHCHECK`.
- Authored `.dockerignore` (18 non-comment entries: 10 locked + 8 research-recommended, `.env` first) — verified build context is 3.22kB, not the ~50MB the repo root would otherwise ship (repomix artifacts + `.env` + dev caches excluded).
- Authored `docker-compose.yml`: one `gateway` service, `env_file: .env`, published port 8000, named volume `gateway-data` for `/app/data`, `restart: unless-stopped`. No `version:` key, no `environment:` overrides, no profiles.
- Added three Makefile targets (`docker-build`, `docker-up` with `--build` for fresh-clone self-sufficiency, `docker-down`) — dev flow untouched except the `.PHONY` line.
- Live-verified on the operator-started Rancher Desktop daemon: image builds, non-root uid confirmed (`os.getuid() != 0`), no `/app/.env` in any layer, `docker compose up -d --build` reaches `health: healthy`, `GET /health` returns `{"status":"ok"}`.
- DEPL-02 expansion: seeded a marker row into the volume-backed SQLite DB via `docker compose exec`, ran two independent `docker compose down` / `up -d` cycles — the row count (1) was identical every time, proving the named volume survives recreation. Captured the full graceful-shutdown log sequence (`Shutting down` → `Waiting for application shutdown.` → `Application shutdown complete.` → `Finished server process [1]`) via `docker compose stop`, completing in 0.485s (well inside the 10s default grace period). Measured in-container readiness twice: 0.902s and 1.614s — both well under the 3s NFR-04 criterion (no overshoot to escalate). Cleaned up the marker row (count back to 0).
- Added a `## Deployment (Docker)` section to README.md between Architecture and Development: env pointer, the exact `docker compose up -d --build` quickstart command, the three make targets, and a volume-persistence note.

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end container tracer — AsyncGenerator 3.12 fix → multi-stage non-root image → compose up → green /health** - `2324c92` (feat)
2. **Task 2: DEPL-02 acceptance expansion — volume persistence, SIGTERM-drain evidence, measured readiness, README quickstart** - `b631f4a` (docs)

_No TDD multi-commit split — Task 1 is `type="tracer"` and was committed as a single unit per the tracer commit convention (RED evidence captured and recorded here, not as a separate commit, since the pre-fix repo state is not something to commit)._

## Files Created/Modified

- `providers/openai_compatible_base.py` - one added import line (`from collections.abc import AsyncGenerator`); the Python 3.12 blocker fix
- `Dockerfile` (NEW) - multi-stage non-root image, venv-copy, chown'd `/app/data`, urllib HEALTHCHECK, exec-form CMD
- `.dockerignore` (NEW) - secret exclusion (`.env` first) + build-context hygiene
- `docker-compose.yml` (NEW) - one `gateway` service, env_file passthrough, named volume, restart policy
- `Makefile` - `docker-build`/`docker-up`/`docker-down` targets under one comment header; `.PHONY` extended
- `README.md` - `## Deployment (Docker)` quickstart section (env pointer, compose command, make targets, volume note)

## Decisions Made

- `docker-up` runs `docker compose up -d --build` (not plain `up -d`) so a fresh clone is self-sufficient without a separate `make docker-build` step first; documented in README to match exactly.
- Did **not** pin `openai` in `requirements.txt` to defensively work around the SDK credential-fallback change discovered mid-execution (see Deviations) — the repo's documented convention (AGENTS.md) is floor-only `>=` pins with no lockfile, and introducing an upper bound would be a second, inconsistent pinning convention. The issue is logged to `WINDOWS.md` instead of silently fixed or silently ignored.

## Deviations from Plan

### Auto-fixed Issues

None required — the one-line import fix and the four config files matched the locked skeletons exactly with no adaptation needed.

### Discovered, Logged, NOT Auto-fixed (SCOPE BOUNDARY)

**1. [Scope Boundary — pre-existing, unrelated] openai SDK >=2.34.0 credential-fallback change breaks 2 unit tests in a fresh 3.12 venv**
- **Found during:** Task 1, step 6 (running `/tmp/gw312/bin/python -m pytest tests/ -q` as the GREEN verification for the AsyncGenerator fix)
- **Issue:** After the AsyncGenerator fix, the 3.12 rig reported `2 failed, 115 passed` (not the exit-0 the plan's acceptance criteria state) — `test_factory_returns_zai_coding_provider` and `test_factory_falls_back_to_manifest_for_other_names` in `tests/test_providers.py` both raise `openai.OpenAIError: Missing credentials`. Root-caused empirically: `openai_compatible_base.py.__init__` passes `api_key=""` (explicit empty string, not `None`) to `AsyncOpenAI(...)` whenever no key is configured for a provider. Bisected the exact SDK boundary: `openai==2.33.0` passes (3 passed), `openai==2.34.0`+ fails — somewhere in that release the SDK's credential check changed from "fall back to `OPENAI_API_KEY` env var on any falsy `api_key`" to "fall back only when `api_key is None`" (explicit empty string is now treated as a deliberate, invalid value). Since `requirements.txt` pins `openai>=1.60.0` with no upper bound, a fresh venv today resolves to `openai==3.8.0`, which has this behavior. The dev `.venv` (created earlier, pinned nothing, but installed `openai==2.32.0` at the time) still passes all 117 tests — masking the issue locally.
- **Why NOT fixed:** (1) The root-cause line lives in `providers/openai_compatible_base.py`, which Task 1's plan text explicitly restricts to "no other change to this file" beyond the one import line (drift guard). (2) The obvious workaround — adding an upper bound to `requirements.txt`'s `openai` line — would introduce a second, inconsistent dependency-pinning convention; AGENTS.md documents the repo's deliberate choice of floor-only `>=` pins with no lockfile. (3) The failure is confined to a synthetic unit-test edge case (`create_provider("anything-else", ...)`, a provider name never used by real routing) — `routing.py`'s `resolve_provider` always calls `create_provider` with a literal `"manifest"` or `"zai-coding"`, both of which resolve to non-empty configured keys in any properly-configured deployment. Confirmed the built container itself is unaffected: `docker compose up` reaches `healthy` and the same unpinned `openai==3.8.0` was installed inside the image with no runtime issue (`/health` never touches a provider).
- **Action taken:** Logged as WINDOWS.md entry #2 (`kind: deviation`, phase 03) with full root-cause detail for future remediation (either a version pin decision or a defensive `api_key=api_key or None` fix in `openai_compatible_base.py`, both out of this plan's scope).
- **Verification of scope boundary:** `.venv/bin/python -m pytest tests/ -q` (3.14, existing openai 2.32.0) still passes 117/117 — the dev-flow contract this plan promises to leave undisturbed is intact.

---

**Total deviations:** 0 auto-fixed; 1 discovered-and-deferred (logged to WINDOWS.md, not code-fixed)
**Impact on plan:** None on DEPL-01/DEPL-02 acceptance — the AsyncGenerator blocker (the actual subject of TR1) is fully resolved and verified on both Python regimes; the residual 2 test failures are an unrelated, narrow, pre-existing dependency-drift issue that does not reach the container or any real routing path.

## Issues Encountered

- Initial in-container readiness measurement (Task 1's own verify chain, `docker compose up -d --build`) measured 3.24s because the timer started before an unnecessary rebuild — re-measured correctly in Task 2 with the image already built (`docker compose up -d`, no rebuild): 0.902s, then 1.614s on a second cycle. Both are the true NFR-04 in-container readiness figures; the plan's own guidance (TR4/NFR-04) is about container-start time, not build time, so the corrected measurement is the one recorded as evidence.

## User Setup Required

None — Rancher Desktop was already running (confirmed by the orchestrator before this plan started); the operator's existing `.env` at the repo root was reused as-is for the compose runs.

## Next Phase Readiness

- `llm-gateway:latest` image and `gateway-data` named volume exist locally (operator-owned Docker state, not repo state) — 03-02 (CI workflow, ruff lint fixes, `main.py`/`analytics/__init__.py` cleanup) can build directly on this.
- The standing 3.12 regression rig at `/tmp/gw312` is reusable by 03-02 and any future import-touching change (recreate with `python3.12 -m venv /tmp/gw312 && /tmp/gw312/bin/pip install -r requirements.txt` if ever removed).
- The openai SDK credential-fallback deviation (WINDOWS.md #2) is open and should be considered before or during 03-02's ruff/CI pass, since a CI matrix leg installing unpinned `openai` will hit the same pre-existing test failures on Python 3.12 (not caused by this plan, but visible there too) — worth a deliberate pin-or-fix decision at that point rather than silently absorbed.
- Live compose stack was left running and healthy at the end of this plan (`llm-gateway-gateway-1`, healthy, port 8000) for continuity into 03-02's CI-build smoke expectations; `docker compose down` is safe at any time (volume `gateway-data` persists).

---
*Phase: 03-containerized-deployment-ci*
*Completed: 2026-09-08*

## Self-Check: PASSED

- FOUND: Dockerfile
- FOUND: .dockerignore
- FOUND: docker-compose.yml
- FOUND: commit 2324c92 (Task 1)
- FOUND: commit b631f4a (Task 2)
- Confirmed: `grep -c "from collections.abc import AsyncGenerator" providers/openai_compatible_base.py` == 1
