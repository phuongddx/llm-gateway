# Phase 3: Containerized Deployment & CI - Research

**Researched:** 2026-09-08
**Domain:** Docker containerization (FastAPI/uvicorn + SQLite), Docker Compose, GitHub Actions CI
**Confidence:** HIGH (every load-bearing claim verified locally or against official docs this session; docker daemon down locally, so container behavior is CI-gated — see Environment Availability)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- `Dockerfile`: python:3.12-slim multi-stage — builder stage installs requirements into a venv, runtime stage copies venv + app; non-root user; HEALTHCHECK hitting `/health`
- `.dockerignore`: .venv, .git, data/, .planning/, plans/, docs/, __pycache__, repomix artifacts, server.log
- `docker-compose.yml`: ONE service, `env_file: .env`, port 8000, named volume for `data/` (analytics.db survives recreates), `restart: unless-stopped`. No profiles, no override files (YAGNI)
- `.github/workflows/ci.yml` on push + PR to main
- Matrix Python [3.12, 3.14]: pip install -r requirements.txt → pytest -q
- One `docker build` smoke job (no push, no registry credentials)
- Makefile keeps dev flow untouched; ADD `docker-build`, `docker-up`, `docker-down` targets
- README gains a short deployment quickstart (compose up + env pointer); nothing else

### Claude's Discretion

None — all areas resolved.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEPL-01 | Gateway ships as a multi-stage, non-root Docker image that reaches request-readiness <3s from process start (NFR-04 holds in-container) | Verified venv-copy multi-stage skeleton (§Code Examples); non-root + volume-ownership mechanics (§Pitfalls 2); measured local startup 3.21s cold / <1.5s warm with in-container measurement protocol (§Open Questions Q2); **blocking pre-req: 3.12 import failure must be fixed first (§Pitfall 1)** |
| DEPL-02 | `docker compose up` on fresh clone with `.env` → green healthcheck; analytics DB persists on volume across recreation; all config via single-`.env` passthrough, no secrets baked | Verified compose skeleton with `env_file`, named volume, HEALTHCHECK; env passthrough mechanics verified against pydantic-settings config (§Code Examples, §Pitfalls 3/5); `.env` exclusion from image enforced by COPY allowlist + .dockerignore |
| DEPL-03 | GitHub Actions runs lint + tests (and builds the image) on push/PR — broken changes caught before the deployed container | Verified CI skeleton: `actions/checkout@v7.0.1` / `setup-python@v7.0.0` are current majors; Python 3.12+3.14 both available (3.14.0–3.14.7 `"stable": true` in manifest); plain `docker build` on ubuntu-latest (Docker preinstalled); lint reconciliation (§Open Questions Q1) + ruff findings (§Pitfall 7) |
</phase_requirements>

## Summary

The gateway is a **single-process async app whose correctness depends on staying single-process**: the `AnalyticsWriter` bounded queue is an in-process `asyncio.Queue` drained by one lifespan-owned consumer task, and `app.state` (DB connection, writer) is per-process [VERIFIED: analytics/writer.py:35 `self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)`; main.py:58-65]. Therefore the container runs plain `uvicorn main:app` (no gunicorn, no `--workers`), and I verified empirically that uvicorn 0.44.0 handles SIGTERM as PID 1 by running the full lifespan shutdown — log sequence `Shutting down → Waiting for application shutdown. → Application shutdown complete. → Finished server process`, exit code 143 [VERIFIED: local run 2026-09-08]. That shutdown path is exactly what drains the analytics queue before `db.close()` (main.py:70-71).

**The single most important discovery is a blocker:** `providers/openai_compatible_base.py:27` annotates `-> AsyncGenerator[StreamChunk, None]` without importing `AsyncGenerator` anywhere in the file. Python ≤3.13 evaluates annotations eagerly; **Python 3.14 made them lazy (PEP 649)**, which is why the dev workstation (3.14.7) and all 117 tests pass while a real Python 3.12.14 venv with `requirements.txt` installed fails at pytest collection: `NameError: name 'AsyncGenerator' is not defined` (exit code 2, 2 collection errors) [VERIFIED: local reproduction, /tmp/gw312 venv, full command `pip install -r requirements.txt && pytest -q`]. Consequence: **the CI 3.12 matrix leg goes red immediately, and a python:3.12-slim container crash-loops on startup** — the fix (one import line, `from collections.abc import AsyncGenerator`) must land before or with the CI/Docker work. Ruff flagged this statically as F821 [VERIFIED: local ruff 0.8.4 run].

Everything else is standard, verified mechanics: venv-copy multi-stage on python:3.12-slim (tag active on Docker Hub, pushed 2026-09-02, multi-arch) [VERIFIED: hub.docker.com API]; exec-form `CMD` so uvicorn receives SIGTERM directly (shell form would swallow it); stdlib-urllib HEALTHCHECK (curl/wget absent on slim; the exact one-liner validated under python3.12 against a live server and against a dead port) [VERIFIED]; `chown` of `/app/data` in the image so a fresh named volume inherits non-root writability (the lifespan otherwise aborts with its own actionable `RuntimeError` — main.py:41-48 does `mkdir` + `os.access` write checks); a .dockerignore that MUST also cover `.env` (secrets) and the two repomix files totaling ~49MB in the repo root (build-context bloat) [VERIFIED: `repomix-output.xml` 24.5MB + `repomix-llmgateway.md` 24.4MB]. GitHub Actions current majors are `checkout@v7` / `setup-python@v7` [VERIFIED: api.github.com releases/latest, published 2026-07-20].

**Primary recommendation:** Land the one-line `AsyncGenerator` import fix (plus optionally the 3 trivial ruff findings) FIRST, then ship the four files exactly as sketched in §Code Examples — venv-copy Dockerfile with COPY allowlist + exec-form CMD + urllib HEALTHCHECK + chown'd `/app/data`; single-service compose with `env_file: .env` + named volume + `restart: unless-stopped`; three-job CI (lint / test matrix [3.12, 3.14] / docker-build); Makefile + README quickstart.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HTTP serving / SSE streaming | Container (uvicorn, single process) | — | One process owns the in-memory queue + aiosqlite connection; multi-worker would fork both (§Pitfalls 8) |
| Analytics persistence | Container-local named volume (SQLite WAL) | — | `ANALYTICS_DB_PATH=data/analytics.db` is CWD-relative; volume keeps it across recreation [VERIFIED: config.py:30, main.py:39-48] |
| Config/secrets delivery | Host `.env` → compose `env_file` → container env → pydantic-settings | — | No config file inside the container; `model_config = {"env_file": ".env", ...}` [VERIFIED: config.py:34-38] resolves from env vars when no `.env` file exists in WORKDIR |
| Liveness signal | Docker HEALTHCHECK → `GET /health` | — | Unauthenticated endpoint returning `{"status": "ok"}` [VERIFIED: main.py:87-89] |
| Change gating | GitHub Actions (push/PR to main) | Branch protection (manual repo setting) | Workflow is in-repo; requiring it on `main` is a Settings → Branches operator step |
| Process lifecycle | Docker/compose restart policy + uvicorn signal handling | — | SIGTERM → lifespan shutdown → writer drain, verified empirically; compose sends SIGTERM, waits `stop_grace_period` (default 10s) then SIGKILL [CITED: docs.docker.com/reference/compose-file/services] |

## Standard Stack

No new runtime dependencies. Everything below is either already in the repo or infrastructure config.

### Core

| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| python base image | `python:3.12-slim` | Builder + runtime stages | Locked decision; tag active on Docker Hub (last pushed 2026-09-02, amd64+arm64 among 16 manifests, ~46MB compressed) [VERIFIED: hub.docker.com/v2/repositories/library/python/tags/3.12-slim] |
| uvicorn | 0.44.0 (local venv; requirements floor `>=0.34.0`) | Container process, PID 1 | Empirically verified graceful SIGTERM→lifespan shutdown; `--timeout-graceful-shutdown` flag exists if ever needed [VERIFIED: local run + `uvicorn --help`] |
| docker compose | v5.1.4 (local CLI) | Single-service orchestration | `env_file`, named volumes, `restart: unless-stopped`, HEALTHCHECK passthrough all standard [CITED: docs.docker.com/reference/compose-file/services] |
| actions/checkout | @v7 (v7.0.1 current) | CI checkout | [VERIFIED: api.github.com/repos/actions/checkout/releases/latest, published 2026-07-20] |
| actions/setup-python | @v7 (v7.0.0 current) | CI Python matrix + pip cache | 3.12 and 3.14 both stable-available (3.14.0–3.14.7 in versions-manifest.json) [VERIFIED: api.github.com + actions/python-versions manifest] |
| ruff (CI-only, optional lint job) | 0.16.6 current (0.8.4 local) | DEPL-03 "lint" | See §Package Legitimacy Audit and §Open Questions Q1 |

### Supporting

| Component | Version | Purpose | When to Use |
|-----------|---------|---------|-------------|
| `python -c "import urllib.request; ..."` | stdlib | HEALTHCHECK probe | curl/wget absent on slim; validated one-liner (below) |
| `sqlite3` via stdlib `python -c` | stdlib | One-time VACUUM on legacy DBs inside container | Avoids apt-installing the sqlite3 CLI; keeps image slim |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Plain `uvicorn main:app` | gunicorn + uvicorn workers / `uvicorn --workers N` | **Rejected — breaks correctness**: each worker gets its own lifespan → N in-memory queues, N writers, N SQLite connections, and slowapi per-IP rate-limit counters become per-worker (effective limit ×N). WAL tolerates multi-connection but the design + RELI-02 guarantees are single-writer, single-process; a single-user personal gateway has no throughput need for workers [VERIFIED: writer.py:35, main.py:58-71, rate_limiter.py single module-level Limiter] |
| Multi-stage venv copy | Single-stage `pip install --system` | Single stage ships pip/setuptools/wheel and build caches; venv copy keeps runtime stage minimal. Locked decision anyway |
| python:3.12-slim by tag | Pin by digest (`@sha256:78387bc…`) | Digest = reproducible but frozen security updates; tag = fresh patches. For a personal gateway, tag is the right default [VERIFIED: current digest from Hub API if pinning is ever wanted] |
| docker/build-push-action | Plain `docker build` step | Locked: build-only smoke, no registry. Plain build = zero third-party action surface |
| apt `sqlite3` in runtime image | stdlib python one-liner | apt costs `apt-get update` build time + ~5MB for a rarely-used operator command; one-liner is free |

**Installation:** no `pip install` changes. Container builder: `pip install --no-cache-dir -r requirements.txt` (single manifest; note it includes pytest+pytest-asyncio → ~20MB of test deps ride along in the venv — acceptable at locked scope; a requirements split is a future option, NOT this phase).

## Package Legitimacy Audit

> Gate run via `gsd-tools query package-legitimacy check --ecosystem pypi ruff`. No packages are installed into the application by this phase; `ruff` is the only new tool and is CI-workflow-only (never in requirements.txt — keeps NFR-02 runtime-dep discipline and the image slim).

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| ruff | PyPI | ~3.9 yrs (first release 0.0.100 uploaded 2022-11-04; current 0.16.6) | not returned by gate tooling | github.com/astral-sh/ruff | SUS ("too-new", "unknown-downloads") | Flagged — planner inserts `checkpoint:human-verify` before the lint job installs it |

**Verdict context (why the SUS signals are weak here, verified this session):** PyPI metadata shows maintainer `Astral Software Inc. <hey@astral.sh>`, owners `crmarsh`/`zanie`/`sarasklenka` (Astral staff), `Development Status :: 5 - Production/Stable`, and a who's-who adopter list (FastAPI, pytest, Pydantic, pandas, scipy) [VERIFIED: pypi.org/pypi/ruff/json]. The gate's "too-new" reason reflects the **latest** release timestamp (2026-09-03 — ruff ships weekly), not package age; "unknown-downloads" is a data gap (PyPI download counts unavailable to the tool). Per protocol the SUS disposition stands: one human-verify checkpoint before adopting.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** ruff (CI-only; see above)

## Architecture Patterns

### System Architecture Diagram

```
            git push / PR to main
                   │
                   ▼
        ┌─────────────────────────┐
        │  GitHub Actions (ci.yml) │
        │  ┌────────────────────┐  │   broken change caught HERE,
        │  │ lint (ruff check)  │  │   before any deploy
        │  ├────────────────────┤  │
        │  │ test × [3.12,3.14] │  │   pip install -r requirements.txt
        │  │   pytest -q        │  │   →  exit 0 | 1(fail) | 2(collect)
        │  ├────────────────────┤  │
        │  │ docker-build smoke │  │   docker build -t llm-gateway:ci .
        │  └────────────────────┘  │
        └───────────┬─────────────┘
                    │ green merge (operator deploys)
                    ▼
  host: cp .env.example .env; edit APP_API_KEY
                    │
                    ▼
        ┌──────────────────────────────┐
        │ docker compose up -d         │
        │  build: .  →  llm-gateway    │
        │  env_file: .env ───────────────► container env ─► pydantic Settings
        │  ports: "8000:8000"          │   (no .env file baked; env-only)
        │  volume: gateway-data:/app/data ─┐
        │  restart: unless-stopped     │   │ analytics.db + WAL survive
        └───────────┬──────────────────┘   │ container recreation
                    ▼                      │
        ┌─────────────────────────────────┴──────────┐
        │ container (non-root, PID 1 = uvicorn)      │
        │  CMD ["uvicorn","main:app",                │
        │       "--host","0.0.0.0","--port","8000"]  │
        │  lifespan: mkdir data/ → AnalyticsDB init  │
        │    → write_probe → AnalyticsWriter start   │
        │    → startup purge (first consumer action) │
        │  HEALTHCHECK (in-container):               │
        │    python -c urllib … /health  ─ exit 0/1  │
        │  SIGTERM (docker stop) → lifespan shutdown │
        │    → writer.stop() drains → db.close()     │
        └────────────────────────────────────────────┘
```

### Recommended Project Structure (new/modified files only)

```
llm-gateway/
├── Dockerfile                 # NEW — multi-stage, non-root, HEALTHCHECK
├── .dockerignore              # NEW — context hygiene + secret exclusion
├── docker-compose.yml         # NEW — one service, env_file, named volume
├── .github/workflows/ci.yml   # NEW — lint + matrix tests + docker build
├── Makefile                   # MODIFIED — +docker-build/up/down, .PHONY
└── README.md                  # MODIFIED — deployment quickstart section
```

### Pattern 1: venv-copy multi-stage on python:3.12-slim

**What:** Build a venv at a fixed absolute path (`/opt/venv`) in a builder stage, copy the directory into an identical runtime stage.
**When to use:** Always for pip-based Python images.
**Why it works:** venvs are not relocatable, but same-path copies are — shebangs and `pyvenv.cfg` point at `/opt/venv/...` and the base interpreter `/usr/local/bin/python3.12`, which exists in both stages **as long as both `FROM` lines use the same tag**. Keep the tag byte-identical in both stages.

### Pattern 2: COPY allowlist (not `COPY . .`)

**What:** Copy only the runtime modules. The app is small and fully enumerated: `main.py config.py rate_limiter.py` + `analytics/ routes/ providers/ static/`.
**Why:** allowlist beats blocklist — `.env` and the 49MB of repomix output can never enter an image layer even if `.dockerignore` regresses. `.dockerignore` remains mandatory anyway for **build-context size** (context upload happens before Dockerfile instructions).

### Pattern 3: exec-form CMD for signal fidelity

**What:** `CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]`.
**Why:** exec form makes uvicorn PID 1 — it registers its own SIGTERM/SIGINT handlers. Shell form (`CMD uvicorn …`) puts `/bin/sh` at PID 1; the graceful path is then shell-dependent. Verified end-to-end: SIGTERM produced the full graceful sequence and lifespan shutdown (writer drain) ran before exit [VERIFIED: local run]. Compose sends SIGTERM on stop, waits `stop_grace_period` (default 10s), then SIGKILL [CITED: docs.docker.com/reference/compose-file/services `stop_grace_period`, `stop_signal`]. The writer's own drain bound is 5s (`_DRAIN_TIMEOUT_S`, writer.py:8), inside the 10s grace — no extra compose knob needed.

### Pattern 4: env-only config inside the container

**What:** No `.env` file in the image. Compose `env_file: .env` injects variables into the container environment; `Settings` reads env vars case-insensitively and `model_config = {"env_file": ".env", "extra": "ignore"}` [VERIFIED: config.py:34-38] simply finds no `.env` at WORKDIR and uses the process env instead.

### Anti-Patterns to Avoid

- **`COPY . .` into the image** — see Pattern 2.
- **Binding `--host 127.0.0.1` in the container** — port mapping dies (the published port forwards to the container's interface; uvicorn must listen on `0.0.0.0`). The Makefile's existing targets already use `--host 0.0.0.0` [VERIFIED: Makefile:15,22] — keep it in CMD.
- **Placing the app anywhere but WORKDIR `/app`** — `FileResponse("static/playground/index.html")`, `StaticFiles(directory="static")` [VERIFIED: main.py:101-106] and the default `ANALYTICS_DB_PATH=data/analytics.db` are **CWD-relative**; uvicorn must start with CWD=`/app`.
- **Multi-worker anything** — see Alternatives table.
- **`version:` top-level key in compose** — obsolete; omit it (modern Compose emits a warning) [ASSUMED — cosmetic, A1].

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Process supervision / worker management | gunicorn config, custom reaper | Plain single `uvicorn` CMD | The app's invariants (single writer queue, in-memory rate limits) are per-process; supervision adds nothing for one process [VERIFIED: writer.py:35] |
| Zombie reaping | — | Nothing (or `init: true` if ever needed) | uvicorn spawns no children; PID-1 signal handling is native to uvicorn |
| HTTP health probe | requests/httpx dependency, shell curl installs | stdlib `urllib.request` one-liner | Validated under python3.12: exit 0 on 200, non-zero on refused/timeout [VERIFIED] |
| Image build in CI | custom scripts / third-party build actions | `docker build` step | Locked decision; Docker is preinstalled on ubuntu-latest runners (APT `docker` third-party repo listed in the runner image table) [CITED: actions/runner-images README] |
| Dependency caching in CI | manual cache steps | `setup-python` `cache: 'pip'` | Hashes `requirements.txt` automatically [CITED: setup-python README] |

**Key insight:** this phase should add ~4 config files and ~1 line of Python. If implementation starts writing application code beyond the `AsyncGenerator` import fix, scope has drifted.

## Common Pitfalls

### Pitfall 1: Python 3.12 breaks at import — CI 3.12 leg and container BOTH dead without the fix
**What goes wrong:** `providers/openai_compatible_base.py:27` uses `AsyncGenerator` in a return annotation with no import of it in the file [VERIFIED: read lines 1-34; ruff F821]. Python ≤3.13 evaluates annotations eagerly → `NameError` at class-definition time → the whole `providers` package fails to import → `main.py` fails → uvicorn exits.
**Why it happens:** local dev is 3.14.7, where PEP 649 deferred annotations mask it — I proved the mechanism both ways: `python3.12 -c "def f() -> X: pass"` → NameError; `python3(3.14) -c …` → no error [VERIFIED].
**How to avoid:** Add `from collections.abc import AsyncGenerator` to the imports of `providers/openai_compatible_base.py`. Then the exact CI command (`pip install -r requirements.txt && pytest -q`) passes on 3.12 — I reproduced the failing command in a 3.12.14 venv: `ERROR tests/test_openai_compatible_base.py`, `ERROR tests/test_providers.py`, "Interrupted: 2 errors during collection", exit 2 [VERIFIED: local reproduction].
**Warning signs:** CI 3.12 red while 3.14 green; container log showing a `NameError` traceback then exit.

### Pitfall 2: Non-root user + named volume = read-only `data/` unless chown'd at build
**What goes wrong:** fresh named volumes initialize by copying the image's mount-point **content** into the empty volume [CITED: docs.docker.com/engine/storage/volumes "Mounting a volume over existing data"]. If `/app/data` in the image is root-owned, the volume dir is root-owned and the non-root process cannot write.
**Why it happens:** the lifespan creates `data/` itself (`parent.mkdir(parents=True, exist_ok=True)`) and then hard-checks writability: `os.access(parent, os.W_OK)` → `RuntimeError("ANALYTICS_DB_PATH parent directory is not writable: …")`, plus a `write_probe()` on the DB [VERIFIED: main.py:39-57]. Root-owned mount → container crash-loops with an actionable-but-avoidable error (and `restart: unless-stopped` keeps retrying [CITED: restart policy semantics]).
**How to avoid:** `RUN mkdir -p /app/data && chown gateway:gateway /app/data` in the Dockerfile (before `USER`). Copy-up preserves ownership [ASSUMED — standard copy-up behavior, A3; confirmed cheaply by the phase smoke test: `docker compose up` → healthcheck green ⇒ ownership survived].
**Warning signs:** container restarting; log ends with `ANALYTICS_DB_PATH parent directory is not writable`.

### Pitfall 3: .dockerignore incompleteness — 49MB context and/or secret bake
**What goes wrong:** repo root contains `repomix-output.xml` (24.5MB) + `repomix-llmgateway.md` (24.4MB), `server.log`, `.env`, `.omx/`, `.claude/`, `.superpowers/`, `.ngrok/`, `.pytest_cache/`, `data/` [VERIFIED: directory listing]. Without .dockerignore entries, every build ships a ~50MB+ context; a bare `COPY . .` would additionally bake `.env` (secrets) and the dev analytics DB.
**How to avoid:** locked .dockerignore list PLUS (recommendation): `.env`, `.pytest_cache`, `.omx`, `.claude`, `.superpowers`, `.ngrok`, `*.pyc`, `tests/` (CI tests on checkout; the image needs no tests). Note `.gitignore` does NOT cover server.log/repomix/.omx — .dockerignore must be authored independently.
**Warning signs:** `docker build` "transferring context" showing tens of MB.

### Pitfall 4: Shell-form CMD silently breaks graceful shutdown
Covered in Pattern 3. Use exec form only.

### Pitfall 5: compose `env_file` interpolation mangles `$` in values
**What goes wrong:** compose applies variable interpolation to unquoted and double-quoted `.env` values; only single-quoted values pass through literally [CITED: docs.docker.com env_file format rules: "Unquoted and double-quoted (`"`) values have Interpolation applied"; `VAR='$OTHER'` → literal `$OTHER`].
**How to avoid:** our `.env.example` values are plain, but document (README quickstart note) that keys containing `$` should be single-quoted. `environment:` entries would override `env_file` for the same var — we define none, so `env_file` is the single source.
**Warning signs:** 401s from providers with a key that works locally.

### Pitfall 6: Missing `.env` → fail-fast, two layers deep
Fresh clone without `.env`: `docker compose up` errors on `env_file` (required by default) [CITED: `required` attribute defaults to `true`] — good, loud, before start. If someone bypasses compose (`docker run` with no env), the lifespan aborts on `APP_API_KEY` (`RuntimeError("APP_API_KEY env var is required but not set")` [VERIFIED: main.py:25-26]) and `restart: unless-stopped` retries — container shows `Restarting (1)` in `docker compose ps`; `docker compose logs` shows the actionable message. This is correct fail-fast behavior; just expect it in the acceptance walkthrough.

### Pitfall 7: A lint step is red on day one
`ruff check .` with zero config currently reports 4 findings on ruff 0.8.4 [VERIFIED: local run]:
```
analytics/__init__.py:1:26: F401 `analytics.db.AnalyticsDB` imported but unused
analytics/__init__.py:2:28: F401 `analytics.cost.calculate_cost` imported but unused
main.py:6:30: F401 [*] `fastapi.Request` imported but unused   (auto-fixable)
providers/openai_compatible_base.py:27:10: F821 Undefined name `AsyncGenerator`  (the Pitfall-1 blocker)
```
The `analytics/__init__.py` re-exports have **zero in-repo consumers** (`from analytics import` matches nothing [VERIFIED: repo grep]) — deleting or keeping with `__all__` are both defensible; `Request` is auto-fixable. Do not add a lint job without first making it green (or scoping the job), or CI starts permanently red — the opposite of DEPL-03's purpose.

### Pitfall 8: "Just add workers for robustness" refactor temptation
Multi-worker is a regression here, not an enhancement — see Alternatives table. Document in the README quickstart line if needed ("single process by design").

### Pitfall 9: NFR-04 in-container timing is untested until the smoke runs
Local cold start (fork → first `/health` 200, includes interpreter+imports+lifespan): **3.21s**; warm: whole probe script incl. startup finished in 2.66s [VERIFIED: local timings on M3 Pro, uvicorn 0.44.0]. The <3s criterion is therefore **borderline-by-measurement** on macOS; Linux containers import faster but CI runners are slower machines. Plan the acceptance as a measured number, not an assumption (§Open Questions Q2). HEALTHCHECK `--start-period=10s` keeps health green during boot without weakening the criterion.

## Code Examples

### Dockerfile (recommended skeleton)

```dockerfile
# syntax=docker/dockerfile:1
# ^ keeps BuildKit on latest stable frontend [CITED: docs.docker.com/reference/dockerfile §syntax]

FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
# --system users via Debian useradd (passwd pkg is required-pack in slim) [ASSUMED: A2 — smoke-verifiable]
RUN groupadd --system gateway && useradd --system --gid gateway gateway \
    && mkdir -p /app/data && chown gateway:gateway /app/data
COPY --from=builder /opt/venv /opt/venv
COPY main.py config.py rate_limiter.py requirements.txt ./
COPY analytics ./analytics
COPY routes ./routes
COPY providers ./providers
COPY static ./static
USER gateway
EXPOSE 8000
# exit 0 = healthy, 1 = unhealthy; defaults: interval 30s, timeout 30s, retries 3
# [CITED: docs.docker.com/reference/dockerfile §HEALTHCHECK]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
# exec form → uvicorn is PID 1, receives SIGTERM directly (verified graceful)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The HEALTHCHECK command bytes are validated: under python 3.12.14 it exited 0 against a live server and non-zero against a dead port [VERIFIED: local run]. `--start-interval` defaults to 5s during the start period (Docker ≥25) [CITED], so the container flips healthy within ~5s of readiness.

### docker-compose.yml

```yaml
services:
  gateway:
    build: .
    image: llm-gateway:latest   # stable name shared with `make docker-build`
    env_file: .env              # required: true by default → loud error if missing [CITED]
    ports:
      - "8000:8000"
    volumes:
      - gateway-data:/app/data  # ANALYTICS_DB_PATH default is data/analytics.db (CWD-relative)
    restart: unless-stopped     # "restarts … irrespective of the exit code but stops
                               #  restarting when the service is stopped or removed" [CITED]

volumes:
  gateway-data:                 # named volume; survives `docker compose down` (not `down -v`)
```

No top-level `version:` key [ASSUMED: A1]. Compose also auto-loads `./.env` for its own `${…}` interpolation; our file has no interpolations, so no interaction.

### .github/workflows/ci.yml

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:                              # DEPL-03 "lint" — see Open Questions Q1
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7      # v7.0.1 current [VERIFIED: api.github.com]
      - uses: actions/setup-python@v7  # v7.0.0 current [VERIFIED: api.github.com]
        with:
          python-version: "3.12"
      - run: pip install ruff          # CI-only; NOT into requirements.txt (NFR-02 + slim image)
      - run: ruff check .

  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false                # see both legs' results even if one fails
      matrix:
        python-version: ["3.12", "3.14"]   # both stable in setup-python manifest [VERIFIED]
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip                  # hashes requirements.txt by default [CITED: setup-python README]
      - run: pip install -r requirements.txt
      - run: pytest -q                # exit 0 pass / 1 fail / 2 collection error [VERIFIED: local exit-code probes]

  docker-build:
    runs-on: ubuntu-latest            # Docker preinstalled on ubuntu images [CITED: runner-images README]
    steps:
      - uses: actions/checkout@v7
      - run: docker build -t llm-gateway:ci .
```

Caveat worth knowing: with unpinned `>=` requirements, a restored pip cache can serve an older-but-satisfying version — the setup-python docs note this exact behavior [CITED]. Harmless here (matrix consistency within a run is what matters).

### Makefile additions (existing targets untouched)

```make
docker-build:
	docker build -t llm-gateway:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down
```
Add all three to `.PHONY`. (`docker compose up -d` builds the image only if absent; run `make docker-build` first after edits, or use `docker compose up -d --build` — pick one and document it in the README quickstart.)

### One-time VACUUM inside the container (README operator note, stdlib only)

```bash
docker compose exec gateway python -c "import sqlite3; c=sqlite3.connect('data/analytics.db'); c.execute('VACUUM'); c.close()"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| actions/checkout@v4 / setup-python@v5 | @v7 both (v7.0.1 / v7.0.0, 2026-07) | 2026-07-20 | Workflows pinned to old majors still run but miss node24/ESM updates [VERIFIED: api.github.com] |
| eager annotation evaluation | lazy (PEP 649) default | Python 3.14 | Masks undefined annotation names on 3.14 that crash ≤3.13 — the exact Pitfall-1 mechanism [VERIFIED: bidirectional local probes] |
| gunicorn+uvicorn-worker as default FastAPI deploy | single uvicorn for stateful single-process apps | ongoing practice | Correct here for queue/limiter state ownership [VERIFIED: code reading] |
| Compose `version:` field | omitted (obsolete) | Compose v2 spec era | warnings on modern compose [ASSUMED: A1] |

**Deprecated/outdated:** none in-repo to migrate (this phase is additive).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Top-level `version:` key obsolete in modern compose files | Code Examples / Anti-patterns | Cosmetic warning only |
| A2 | `useradd`/`groupadd` (Debian `passwd`/`shadow`, required packages) exist in python:3.12-slim | Dockerfile skeleton | Build-time failure, 1-line fix (`adduser --system` variant); smoke catches |
| A3 | Named-volume copy-up preserves file ownership (content-copy is [CITED]; ownership aspect standard behavior) | Pitfall 2 | Container crash-loops with lifespan's actionable RuntimeError; smoke catches; fix = `chown` in Dockerfile (already present) |
| A4 | ubuntu-latest docker CLI builds without setup (Buildx default) | CI docker job | docker-build job red on first run; visible immediately, fix is one action swap |
| A5 | ruff default rule set stable enough for an unpinned CI install | CI lint job | Future ruff release adds rules → lint goes red; mitigation = pin `ruff==0.16.6` |
| A6 | In-container startup <3s (local: 3.21s cold macOS / <1.5s warm) | Pitfall 9 | Criterion DEPL-01 misses; mitigation = measure in smoke; escalation = user decision on criterion or optimization (precompiled bytecode, import trim) |
| A7 | Compose healthcheck honors Dockerfile HEALTHCHECK without repetition in compose file | DEPL-02 | None — duplicating it in compose would also work |

**Items NOT assumed (all verified or cited):** 3.12 import failure + fix need; graceful SIGTERM behavior; healthcheck one-liner; action majors; Python 3.14 availability; python:3.12-slim tag liveness; env_file/restart/stop_grace semantics; HEALTHCHECK syntax/defaults; volume copy-up content semantics; pytest exit codes; runner Docker availability; repomix file sizes.

## Open Questions

1. **Lint job in CI — locked CONTEXT says matrix+docker only; DEPL-03 says "lint + tests (and builds the image)"**
   - What we know: CONTEXT.md's CI decision lists matrix pytest + docker-build smoke, no lint. REQUIREMENTS.md DEPL-03 explicitly says "runs lint + tests". Repo has no linter configured (AGENTS.md confirms).
   - Recommendation: add the tiny `lint` job (ruff) AND fix the 4 findings in the same plan — the F821 fix is mandatory anyway (Pitfall 1), `Request` is auto-fixable, and the two `analytics/__init__.py` re-exports have no consumers (delete or keep via `__all__`). Total ~4 small edits buys the requirement's literal satisfaction. If the user prefers strict CONTEXT scope, drop the lint job and record DEPL-03's "lint" as satisfied by the matrix — but that leaves the requirement text unmet. Planner should surface this one question.
2. **In-container <3s readiness measurement protocol**
   - What we know: 3.21s cold / <1.5s warm locally [VERIFIED]; container untested (docker daemon down).
   - Recommendation: acceptance step = start container, poll `/health` at 100ms, report measured number in the task evidence; treat <3s as target, marginal overshoot → user decision (criterion adjustment vs optimization). Do NOT build optimization (precompileall, import trimming) preemptively.
3. **Local docker smoke before CI**
   - What we know: Docker CLI 29.5.3-rd + compose v5.1.4 + buildx v0.34.1 installed, but the Rancher Desktop daemon socket is absent (`docker info` fails) [VERIFIED].
   - Recommendation: plan the smoke test as either (a) operator starts Rancher Desktop then runs the compose acceptance locally, or (b) rely on the CI docker-build job for build verification and do the runtime acceptance when a daemon is available. DEPL-02's "fresh clone with .env → green healthcheck" acceptance needs a daemon; flag it as a checkpoint in the plan.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker daemon | DEPL-01/02 local smoke | ✗ (CLI yes, daemon down — Rancher Desktop socket missing) | CLI 29.5.3-rd | CI docker-build job for build proof; start Rancher Desktop for runtime acceptance (Open Question 3) |
| docker compose | DEPL-02 | ✓ (CLI plugin) | v5.1.4 | — |
| docker buildx | DEPL-01 | ✓ (CLI plugin; needs daemon to run) | v0.34.1 | — |
| Python 3.12 (local) | matrix-leg parity check | ✓ | 3.12.14 (homebrew) | CI matrix leg |
| Python 3.14 (local) | dev | ✓ | 3.14.7 (.venv) | — |
| ruff (local) | lint parity check | ✓ | 0.8.4 (CI will get current 0.16.6) | — |
| GitHub remote | DEPL-03 | ✓ | `github.com-phuongddx:phuongddx/llm-gateway` | — |
| Network (docs/registries/APIs) | research | ✓ | — | — |

**Missing dependencies with no fallback:** Docker daemon for the DEPL-02 runtime acceptance — resolvable by the operator starting Rancher Desktop (it is installed); otherwise the phase's runtime proof is deferred to CI + a post-merge checkpoint.

**Missing dependencies with fallback:** none beyond the above.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (>=8.0.0) + pytest-asyncio (>=0.24.0), `asyncio_mode = auto` [VERIFIED: pytest.ini, requirements.txt] |
| Config file | `pytest.ini` (2 lines) |
| Quick run command | `.venv/bin/python -m pytest tests/ -q` (~7s locally for a small file; full suite ~117 tests per CONTEXT.md) |
| Full suite command | `.venv/bin/python -m pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DEPL-01 | Image builds multi-stage, non-root, healthy | CI smoke (build) + manual runtime acceptance | `docker build -t llm-gateway:ci .` (CI job) | n/a — new workflow file IS the check |
| DEPL-01 | 3.12/3.14 both import & pass the suite | CI matrix (the matrix leg is the regression test for Pitfall 1) | `pytest -q` on [3.12, 3.14] | ✅ existing 117-test suite |
| DEPL-02 | compose up → green healthcheck; volume persistence | manual acceptance (daemon-gated) | `docker compose up -d && docker compose ps` (health=healthy); recreate + verify analytics rows | n/a — environment-gated |
| DEPL-02 | no secrets baked | static acceptance | `.dockerignore` contains `.env` + Dockerfile COPY allowlist (no `.env` possible) | n/a |
| DEPL-03 | lint+tests+build gate pushes/PRs | the CI run itself | green check on the phase PR | workflow file is the deliverable |

Exit-code semantics the CI relies on: pytest 0=pass, 1=failures, 2=collection error [VERIFIED: local probes — the 3.12 venv returned 2, a passing 3.14 run returned 0]; docker build non-zero on failure.

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/ -q` (+ the 3.12 venv leg while touching imports: `/tmp/gw312/bin/python -m pytest tests/ -q` — recreate with `python3.12 -m venv && pip install -r requirements.txt` if gone)
- **Per wave merge:** full suite + `ruff check .` + `docker build` (CI enforces all three on PR anyway)
- **Phase gate:** full suite green × both matrix legs + green CI on the phase PR + DEPL-02 manual acceptance walkthrough

### Wave 0 Gaps
None — existing test infrastructure covers all automatable phase requirements. Container-runtime checks are environment-gated (daemon), not test-infrastructure gaps. No new test files recommended: the 3.12 matrix leg is the permanent regression test for Pitfall 1; a dedicated unit test would assert what collection already proves.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (unchanged) | Existing `APP_API_KEY` Bearer gate via env passthrough — no change this phase |
| V3 Session Management | no | Stateless token, no sessions |
| V4 Access Control | yes (container) | Non-root `USER gateway` (DEPL-01); no container capabilities added |
| V5 Input Validation | yes (unchanged) | pydantic-settings validates env (`RATE_LIMIT` parse, queue/retention bounds) [VERIFIED: config.py:40-72] |
| V6 Cryptography | no | No crypto added |

### Known Threat Patterns for containerized FastAPI + SQLite

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret baked into image layers | Information Disclosure | `.dockerignore` `.env` + COPY allowlist (defense in depth); secrets only via compose `env_file` at runtime |
| Root-privileged container escape surface | Elevation of Privilege | `USER gateway` (system user, no shell login needed); no `--privileged`, no added caps |
| Base-image supply chain | Tampering | Official `python` library image, tag-active and patched 2026-09-02 [VERIFIED: Hub API]; digest-pinning available if wanted |
| Healthcheck endpoint as recon | Information Disclosure | `/health` returns only `{"status": "ok"}` (baseline, unchanged) [VERIFIED: main.py:87-89] |
| `.env` on host readable | Information Disclosure | `.gitignore` already excludes `.env`; README quickstart should note file perms are the operator's responsibility (single-user host model) |

## Sources

### Primary (HIGH confidence — local empirical runs, 2026-09-08)
- Python 3.12.14 venv + `requirements.txt` + `pytest -q` → NameError/exit 2 reproduction; bidirectional annotation-evaluation probes (3.12 NameError / 3.14 silent)
- uvicorn 0.44.0 live run: SIGTERM graceful-shutdown log sequence, exit 143, `/health` 200; startup timings 3.21s cold / warm script 2.66s
- HEALTHCHECK urllib one-liner under python3.12: exit 0 healthy / non-zero dead
- ruff 0.8.4 `ruff check .` — 4 findings (concise output quoted in Pitfall 7)
- Repo reads: main.py (lifespan, /health, static CWD paths), config.py (Settings/env), analytics/writer.py (queue), Makefile, .env.example, .gitignore, requirements.txt, pytest.ini, directory listing (repomix sizes)
- pytest exit codes 0/2 (local probes)
- `docker info` daemon-down observation; git remote; local tool versions

### Official documentation (fetched this session)
- docs.docker.com/reference/compose-file/services — `env_file` (required/format/interpolation rules), `restart` policies, `stop_grace_period`/`stop_signal`
- docs.docker.com/reference/dockerfile — HEALTHCHECK forms/defaults/exit codes, `# syntax=docker/dockerfile:1`, USER/WORKDIR/CMD/ENTRYPOINT sections
- docs.docker.com/engine/storage/volumes — empty-volume copy-up ("these files or directories are propagated (copied) into the volume"), compose named-volume reuse
- actions/setup-python README + docs/advanced-usage.md — v7 usage, `cache: 'pip'`, unpinned-requirements cache caveat, matrix syntax
- actions/python-versions versions-manifest.json — 3.14.0–3.14.7 `"stable": true`
- actions/runner-images README — ubuntu-latest = 24.04; Docker installed via APT third-party repo
- api.github.com releases/latest — actions/checkout v7.0.1, actions/setup-python v7.0.0 (both 2026-07-20)
- hub.docker.com API — `python:3.12-slim` tag active (pushed 2026-09-02, multi-arch, digest sha256:78387bc3881b…)
- pypi.org/pypi/ruff/json — ruff 0.16.6, Astral maintainer, first release 2022-11-04
- gsd-tools `package-legitimacy check --ecosystem pypi ruff` → SUS verdict (contextualized in §Package Legitimacy Audit)

### Tertiary (LOW confidence)
- uvicorn.org — DNS unreachable this session (ENOTFOUND); graceful-shutdown claims rest on the local empirical run instead, so nothing load-bearing is assumed from memory

## Metadata

**Confidence breakdown:**
- Standard stack / versions: HIGH — every version claim verified against live registries/APIs this session
- Architecture (Dockerfile/compose/CI skeletons): HIGH — patterns validated by local probes + official reference; container end-to-end pending daemon (CI-gated)
- Pitfalls: HIGH — Pitfall 1 (3.12 blocker), 3 (context size), 7 (lint findings) empirically reproduced; Pitfall 2's ownership aspect [ASSUMED A3] closes via the phase smoke test
- CI/Actions specifics: HIGH — majors and Python availability verified; branch-protection step is manual by nature

**Research date:** 2026-09-08
**Valid until:** 2026-10-08 (action majors and image tags drift slowly; re-check `@v7` majors and ruff findings if planning later)

## RESEARCH COMPLETE

**Phase:** 3 — Containerized Deployment & CI
**Confidence:** HIGH

Ready for planning. The one mandatory sequencing fact for the planner: **the `from collections.abc import AsyncGenerator` import fix in `providers/openai_compatible_base.py` must land in (or before) the first task** — without it the CI 3.12 matrix leg fails at collection (exit 2, reproduced locally) and the python:3.12-slim container cannot start. Everything else is verified-mechanics file authoring per §Code Examples.
