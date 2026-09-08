# Phase 3: Containerized Deployment & CI - Pattern Map

**Mapped:** 2026-09-08
**Files analyzed:** 9 (4 new, 5 modified)
**Analogs found:** 9 / 9 (5 in-repo analogs, all git-verified tracked; 4 verified RESEARCH.md skeletons for the new infra files — no in-repo analogs exist for those)

> **Primary pattern source for the four NEW files:** the verified skeletons in `03-RESEARCH.md` §Code Examples, quoted verbatim below. They are research-verified (local probes + official docs, HIGH confidence), so the planner should treat them as the pattern, not as inspiration.
>
> **Mandatory sequencing fact (from RESEARCH, empirically reproduced):** the `AsyncGenerator` import fix in `providers/openai_compatible_base.py` must land in or before the first task. Without it, the CI 3.12 matrix leg fails at pytest collection (exit 2, reproduced in a real 3.12.14 venv) and the `python:3.12-slim` container crash-loops on startup.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Dockerfile` (NEW) | config (container build) | batch (build pipeline) | `03-RESEARCH.md` §Code Examples skeleton | skeleton-exact (no in-repo analog) |
| `.dockerignore` (NEW) | config (build-context filter) | file-I/O filter | CONTEXT locked list + RESEARCH §Pitfall 3 additions | decision-list (no in-repo analog) |
| `docker-compose.yml` (NEW) | config (orchestration) | long-running service | `03-RESEARCH.md` §Code Examples skeleton | skeleton-exact (no in-repo analog) |
| `.github/workflows/ci.yml` (NEW) | config (CI) | batch (event-triggered) | `03-RESEARCH.md` §Code Examples skeleton | skeleton-exact (no in-repo analog) |
| `Makefile` (MOD) | build tooling | command dispatch | `Makefile` itself (existing target style, lines 1-47) | exact (self) |
| `README.md` (MOD) | docs | n/a | `README.md` itself (Quick Start subsections + `## Development` listing) | exact (self) |
| `providers/openai_compatible_base.py` (MOD) | service (provider base) | streaming | `providers/base.py` lines 1-2 (import convention) | role-match |
| `main.py` (MOD) | entrypoint (import-line touch only) | request-response | `main.py` itself (existing import block, lines 1-15) | exact (self) |
| `analytics/__init__.py` (MOD) | package marker | n/a | `routes/__init__.py` (tracked 0-byte empty package marker) | exact |

All in-repo analogs verified git-tracked (`git ls-files` prints each). `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `.github/` do not exist in the repo (verified absent) — hence the RESEARCH skeletons.

## Pattern Assignments

### `Dockerfile` (NEW — config, container build)

**Pattern source:** `03-RESEARCH.md` §Code Examples — quote verbatim; every load-bearing element is research-verified (venv-copy works because both `FROM` lines use the byte-identical tag; HEALTHCHECK one-liner validated under python 3.12 against a live server and a dead port; exec-form CMD verified to produce graceful SIGTERM → lifespan shutdown, exit 143).

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

**Codebase anchors that make each element non-negotiable (do not "improve" them):**

- **COPY allowlist enumeration** — verified top-level layout: modules `main.py`, `config.py`, `rate_limiter.py`; packages `analytics/`, `routes/`, `providers/`, `static/`. Everything else (`tests/`, `docs/`, `data/`, `.planning/`, repomix files) stays out.
- **`chown gateway:gateway /app/data`** — the lifespan itself creates and hard-checks the data dir: `main.py:39-57` does `parent.mkdir(parents=True, exist_ok=True)` + `os.access(parent, os.W_OK)` → `RuntimeError("ANALYTICS_DB_PATH parent directory is not writable: …")`. A root-owned volume mount-point crash-loops (RESEARCH §Pitfall 2).
- **`WORKDIR /app` + CWD-relative paths** — `FileResponse("static/playground/index.html")`, `StaticFiles(directory="static")` (main.py:101-106) and the default `ANALYTICS_DB_PATH=data/analytics.db` (config.py:30) are CWD-relative; uvicorn must start with CWD=`/app`.
- **`--host 0.0.0.0 --port 8000` in CMD** — matches the existing serving convention already used by every Makefile run target (Makefile:14 and :22 both pass `--host 0.0.0.0 --port 8000`). Never `127.0.0.1` inside a container.
- **Single uvicorn, no workers** — `analytics/writer.py:35` owns an in-process `asyncio.Queue`; `main.py:58-71` owns per-process `app.state`. Multi-worker is a correctness regression, not an enhancement (RESEARCH Alternatives table).
- **requirements.txt** (11 lines, unpinned `>=`): the venv install ships pytest+pytest-asyncio too (~20MB) — accepted at locked scope; no requirements split this phase.

---

### `.dockerignore` (NEW — config, build-context filter)

**Pattern source:** CONTEXT locked list + RESEARCH §Pitfall 3 recommended additions. `.gitignore` is syntax-adjacent only — RESEARCH verified `.gitignore` does NOT cover `server.log`, the two repomix files (~49MB combined in repo root), or `.omx`, so `.dockerignore` must be authored independently.

Locked entries (CONTEXT decision, verbatim): `.venv`, `.git`, `data/`, `.planning/`, `plans/`, `docs/`, `__pycache__`, repomix artifacts, `server.log`.

Recommended additions (RESEARCH §Pitfall 3 — defense in depth; the Dockerfile COPY allowlist already prevents these entering *layers*, but .dockerignore also shrinks *context upload*): `.env` (secrets — the single most important addition), `.pytest_cache`, `.omx`, `.claude`, `.superpowers`, `.ngrok`, `*.pyc`, `tests/` (CI tests on checkout; the image needs no tests).

**Compositional note for the planner:** list the locked entries exactly as decided, then the additions; a flat newline-separated list (one entry per line, `#` comments allowed) is the entire file format.

---

### `docker-compose.yml` (NEW — config, orchestration)

**Pattern source:** `03-RESEARCH.md` §Code Examples — quote verbatim:

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

**Constraints:** ONE service; no `version:` top-level key (obsolete — modern Compose warns, RESEARCH §State of the Art); no `environment:` entries (would override `env_file` — env-only config, see Shared Patterns); no profiles, no override files (locked YAGNI decision).

---

### `.github/workflows/ci.yml` (NEW — config, CI)

**Pattern source:** `03-RESEARCH.md` §Code Examples — quote verbatim. Three jobs: lint / test matrix [3.12, 3.14] / docker-build. Action majors verified current this session (`checkout@v7.0.1`, `setup-python@v7.0.0`, both 2026-07-20).

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:                              # DEPL-03 "lint" — post-research decision (CONTEXT 2026-09-08)
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

**Hard ordering constraint:** the lint job is only green-day-one because the 3 ruff F401/F821 findings are fixed in this phase (post-research decision in CONTEXT). The four findings (ruff 0.8.4, verified): `analytics/__init__.py:1:26` + `:2:28` (F401 re-exports), `main.py:6:30` (F401 `Request`, auto-fixable), `providers/openai_compatible_base.py:27:10` (F821 — the blocker). Fix them in or before the same wave that adds ci.yml.

**Checkpoint for planner:** ruff carries a SUS package-legitimacy verdict (RESEARCH §Package Legitimacy Audit — signals are weak: Astral-maintained, Production/Stable, adopted by FastAPI/pytest/pandas) → insert `checkpoint:human-verify` before adopting the lint job. Optional hardening: pin `ruff==0.16.6` instead of floating latest (RESEARCH assumption A5).

---

### `Makefile` (MOD — build tooling; dev flow untouched, 3 targets added)

**Analog:** the Makefile's own existing conventions (all 47 lines read; tracked).

**`.PHONY` convention** (line 1 — single line listing every target; extend it, don't add a second `.PHONY`):

```make
.PHONY: install start stop health dev clean test test-unit test-integration
```

**Target-block convention** — comment line directly above each target, recipe uses `@`-prefixed shell guards where output control matters (lines 6-9, 11-17):

```make
# Install Python dependencies
install:
	test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt
```

**Env-guard + serve convention** (lines 11-17 — note `--host 0.0.0.0 --port 8000`, reused verbatim by the Dockerfile CMD):

```make
# Start server in background on port 8000
start:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example — edit with your API keys"; fi
	@if lsof -ti:8000 > /dev/null 2>&1; then echo "Server already running on :8000"; else \
		nohup .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 & \
		sleep 1; \
		make health; fi
```

**New targets** (RESEARCH §Code Examples — quote as-is; append after `clean` (lines 44-47) under a `# Docker deployment` comment, and add all three names to the line-1 `.PHONY` list):

```make
docker-build:
	docker build -t llm-gateway:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down
```

Open choice flagged by RESEARCH: `docker compose up -d` builds only if the image is absent — either document "run `make docker-build` first after edits" or use `up -d --build`. Pick ONE and document it in the README quickstart. The `image: llm-gateway:latest` name in compose is shared with `make docker-build` deliberately.

---

### `README.md` (MOD — docs; one short deployment quickstart section, nothing else)

**Analog:** the README's own section conventions (headings and line numbers verified by heading grep).

**Quick Start subsection style** — `### Configure` (lines 31-35) is the exact env-pointer pattern to mirror:

```markdown
### Configure

```bash
cp .env.example .env
```
```

**Command-block style** — `### Run` (lines 55-65), the shape the new section copies:

```markdown
### Run

```bash
# Production (background)
make start

# Development (auto-reload)
make dev
```

Server starts at `http://0.0.0.0:8000`.
```

**Placement:** insert a new `## Deployment (Docker)` section between `## Architecture` (line 248) and `## Development` (line 274). Content = env pointer (mirror lines 33-35) + compose-up bash block (mirror `### Run` shape) + the `make docker-build`/`docker-up`/`docker-down` target list in the same one-line-comment style as the `## Development` listing (lines 276-284). Optional one-line notes from RESEARCH: single-quote `.env` values containing `$` (compose interpolation, §Pitfall 5) and "single process by design" (§Pitfall 8). Nothing else — the decision locks the scope.

**Do not touch:** `## Configuration` tables (env surface is unchanged — env vars pass through compose `env_file` to the same pydantic Settings).

---

### `providers/openai_compatible_base.py` (MOD — service, streaming; one-line import fix)

**Analog:** `providers/base.py` lines 1-2 — the in-repo `AsyncGenerator` import convention (tracked):

```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator, NotRequired, TypedDict
```

**Current state of the file** (lines 1-9 read; tracked):

```python
"""Shared base class for OpenAI-compatible API providers."""

import logging

from openai import AsyncOpenAI

from providers.base import LLMProvider, StreamChunk, UsageData
```

**The defect** (lines 25-27; ruff F821 at 27:10):

```python
    async def chat_stream(
        self, messages: list[dict], system_prompt: str, params=None
    ) -> AsyncGenerator[StreamChunk, None]:
```

`AsyncGenerator` is used at line 27 with no import anywhere in the file. Python ≤3.13 evaluates annotations eagerly → `NameError` at class definition → the whole `providers` package fails to import → `main.py` fails → the 3.12 CI leg exits 2 at collection and the container crash-loops. Python 3.14 (PEP 649 lazy annotations) masks it locally — that's why all 117 tests pass on the dev workstation.

**The fix — add one import line to the stdlib group** (after `import logging`, keeping the stdlib → third-party → local grouping the file already follows):

```python
import logging
from collections.abc import AsyncGenerator
```

Spelling decision: RESEARCH recommends `from collections.abc import AsyncGenerator` (verified working on 3.12; modern form). The repo's existing `providers/base.py:2` uses the deprecated-but-functional `from typing import AsyncGenerator` — also F821-clean under ruff default rules. Either spelling fixes the crash; prefer `collections.abc` (research-verified, non-deprecated). This is the ONLY code change to this file.

---

### `main.py` (MOD — dead-symbol removal on the import line)

**Analog:** the file's own import block (lines 1-15 read; tracked). Line 6:

```python
from fastapi import FastAPI, Request
```

**The fix** (ruff F401 at 6:30, auto-fixable; verified unused by ruff run in RESEARCH §Pitfall 7):

```python
from fastapi import FastAPI
```

No other change to main.py. The lifespan (lines 20+: `APP_API_KEY` fail-fast at main.py:25-26, data-dir mkdir/write-check at 39-57, writer lifecycle at 58-71) is exactly what the container exercises — it is referenced by the Dockerfile/compose rationales above and must not be modified.

---

### `analytics/__init__.py` (MOD — dead re-exports)

**Analog:** `routes/__init__.py` — tracked 0-byte empty package marker (verified via `wc -c` + `git ls-files`). Emptying the file matches an existing in-repo convention.

**Current state** (entire file, 2 lines, 79 bytes; tracked):

```python
from analytics.db import AnalyticsDB
from analytics.cost import calculate_cost
```

Both are ruff F401 findings with **zero in-repo consumers** — verified by repo grep: no source file does `from analytics import …` (main.py:13-14 imports `from analytics.db import AnalyticsDB` and `from analytics.writer import AnalyticsWriter` directly; RESEARCH §Pitfall 7 corroborates).

**The fix:** delete both lines, leaving a 0-byte `analytics/__init__.py` (keep the file — it's the package marker, matching `routes/__init__.py`). Alternative considered and rejected: keeping re-exports with `__all__` — defensible per RESEARCH, but dead code with no consumers fails the delete-weightless-code bar; deletion is the clean cutover.

## Shared Patterns

### Import grouping (stdlib → third-party → local, blank-line separated)
**Source:** `main.py:1-15`, `providers/openai_compatible_base.py:1-7`
**Apply to:** the `AsyncGenerator` import insertion (it goes in the stdlib group, not appended at the bottom).

```python
import logging
import os                      # stdlib first
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI    # third-party second

from analytics.db import AnalyticsDB   # local last
```

### Serving convention: `--host 0.0.0.0 --port 8000`
**Source:** `Makefile:14,22` (every run target); health probe at `http://localhost:8000/health` (Makefile:29-30)
**Apply to:** Dockerfile `CMD` (already in the skeleton) — never bind `127.0.0.1` in-container; the published port forwards to the container's interface.

### Env-only config, `.env.example` as documented surface
**Sources:** `Makefile:13` (start guard `cp .env.example .env`), `README.md:31-35` (Configure section), `.env.example` (tracked, 28 lines — APP_API_KEY required), `config.py:34-38` (`model_config = {"env_file": ".env", "extra": "ignore"}` resolves from process env when no `.env` exists at WORKDIR)
**Apply to:** compose `env_file: .env` (single source of truth, no `environment:` overrides), Dockerfile (never COPY `.env`), README quickstart env pointer. No secrets baked anywhere — `.dockerignore` + COPY allowlist are the two defense layers.

### CWD-relative runtime paths → `WORKDIR /app` invariant
**Source:** `main.py:101-106` (`static/` mounts), `config.py:30` (`ANALYTICS_DB_PATH=data/analytics.db`)
**Apply to:** Dockerfile (`WORKDIR /app` before CMD; `/app/data` chown'd), compose (`gateway-data:/app/data` volume mount point).

### Makefile hygiene
**Source:** `Makefile:1` (single `.PHONY` line), lines 6-7 (comment-above-target)
**Apply to:** the three docker targets — comment header `# Docker deployment`, names appended to line 1's `.PHONY`.

### Lint-green-before-lint-job
**Source:** RESEARCH §Pitfall 7 (4 findings quoted verbatim)
**Apply to:** plan ordering — the three Python fixes land in or before the wave that adds `.github/workflows/ci.yml`, or CI starts permanently red.

## No Analog Found

No in-repo analogs exist for these files (verified absent: no `Dockerfile`, `docker-compose.yml`, `.dockerignore`, or `.github/` anywhere in the repo). Their patterns come from the verified RESEARCH.md skeletons quoted in full above — planner should copy them verbatim, not re-derive:

| File | Role | Data Flow | Pattern Source |
|------|------|-----------|----------------|
| `Dockerfile` | config (container build) | batch | RESEARCH §Code Examples (verified skeleton) |
| `.dockerignore` | config (context filter) | file-I/O filter | CONTEXT locked list + RESEARCH §Pitfall 3 |
| `docker-compose.yml` | config (orchestration) | long-running service | RESEARCH §Code Examples (verified skeleton) |
| `.github/workflows/ci.yml` | config (CI) | event-triggered batch | RESEARCH §Code Examples (verified skeleton) |

## Metadata

**Analog search scope:** repo root (Makefile, README.md, requirements.txt, .env.example, top-level *.py), `analytics/`, `routes/`, `providers/`, `tests/` (layout only); tracked-source gate run on every named analog (`git ls-files -- <path>` non-empty for all)
**Files scanned:** 9 named files + 2 convention checks (`providers/base.py`, `routes/__init__.py`) + top-level layout glob
**Pattern extraction date:** 2026-09-08
**Key repo facts baked in:** tests = 117 passing; local dev Python 3.14.7 vs target 3.12 (PEP 649 masks the F821); Docker daemon down locally (CLI 29.5.3-rd present) → runtime acceptance is operator-gated (Rancher Desktop), build proof rides the CI docker-build job
