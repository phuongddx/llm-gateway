# Repository Guidelines

## Project Overview

LLM Gateway is a small async **FastAPI** proxy that exposes an OpenAI-compatible
chat API (`POST /v1/chat/completions`, `GET /v1/models`) authenticated by a
single shared Bearer token, and forwards each request to **Manifest**
(`https://app.manifest.build/v1`) — a third-party router fanning out across
500+ upstream models (OpenAI, Anthropic, Gemini, DeepSeek, Kimi, GLM,
MiniMax, Doubao, etc) — or, for `glm-*` models when `ZAI_CODING_API_KEY`
(or the `LLM_API_KEY` fallback) is set, to the **z.ai GLM Coding Plan**
endpoint (`https://api.z.ai/api/coding/paas/v4`). The gateway's own value-add: a stable
model-name routing table with passthrough for unknown models, SQLite-backed
request analytics (tokens/latency/TTFT/cost/credits/status) exposed via a small REST
API, IP-based rate limiting, and a bundled static browser playground for
manual testing.

> **Docs drift warning:** `docs/project-overview-pdr.md`, `docs/deployment-guide.md`,
> `docs/code-standards.md`, and `docs/project-roadmap.md` still describe an
> **older 8-native-provider architecture** (per-provider files `gemini.py`,
> `openai_provider.py`, `deepseek.py`, `moonshot.py`, `bytedance.py`, `glm.py`,
> `minimax.py` — all deleted) with per-provider cost pricing tables. That
> architecture was replaced by the single-Manifest-provider cutover
> (`plans/0419-2337-manifest-provider-integration/`). Treat **README.md**,
> **`docs/codebase-summary.md`**, and **`docs/system-architecture.md`** as the
> authoritative current-state docs; the other four are historical/roadmap
> context only — don't cite their provider lists as current fact.

## Architecture & Data Flow

Request flow for `POST /v1/chat/completions`:

1. `verify_auth` dependency (`routes/chat.py`) checks `Authorization: Bearer <token>`
   against `settings.app_api_key`; mismatch → `401`.
2. `@limiter.limit(settings.rate_limit)` (slowapi, per-IP) enforces the configured
   rate window; over limit → `429`.
3. `resolve_provider(model)` (`analytics/routing.py`) looks up the static
   `MODEL_ROUTING` dict; non-GLM entries map to `("manifest", model_id)`, GLM
   entries to `("zai-coding", canonical_id)` — flash-named aliases canonicalize
   to `glm-5.3-flash`, other GLM aliases to `glm-5.3` — and degrade to
   `("manifest", canonical_id)` when no effective z.ai key is set. Unknown
   `glm-*` names go to `("zai-coding", model)` under the same key gate; all
   other unknown names pass through unchanged as `("manifest", model)`.
4. `create_provider(provider_name, model_id)` (`providers/__init__.py`) is a
   factory: `"zai-coding"` constructs `ZAICodingProvider`, everything else
   `ManifestProvider`. Adding further providers here remains the dispatch
   extension point.
5. `ManifestProvider(OpenAICompatibleProvider)` (`providers/manifest.py`) opens
   an `AsyncOpenAI` client (`base_url="https://app.manifest.build/v1"`,
   `default_model="auto"`) and streams via `chat.completions.create(stream=True,
   stream_options={"include_usage": True})`.
6. `_tracked_stream()` (`routes/chat.py`) wraps the provider's async generator,
   emitting SSE frames `data: {"token": ...}\n\n`, ending with `data: [DONE]\n\n`.
   It measures latency/TTFT, calls `calculate_cost()` (`analytics/cost.py`,
   **always returns `0.0`** — Manifest bills internally) plus `estimate_credits()`
   (same module; per-request z.ai coding-plan credit estimate, `0.0` for
   non-`zai-coding` traffic), and logs a row (including `credits_used`) by
   enqueuing it via `analytics_writer.enqueue(record)` — non-blocking on the
   bounded queue sized by `ANALYTICS_QUEUE_SIZE` (drop-newest when full) —
   drained by the single lifespan-owned consumer task that serially calls
   `AnalyticsDB.log_request`; failures are logged by the writer, never
   silently lost.
7. Streaming errors are caught broadly, logged via `logging`, and surfaced to
   the client as a generic nested object
   `data: {"error": {"message": "Internal error processing request", "type": "server_error"}}\n\n`
   — except `zai-coding`, which maps quota errors (HTTP 429 / code 1113) to
   "zai-coding quota exhausted — resets within the 5-hour window" and auth
   failures (401/403) to "zai-coding authentication failed" (these zai frames
   additionally carry a `"code"` key — `"zai_quota_exhausted"` /
   `"zai_auth_failed"`). Internal exception text is never leaked over SSE.

Provider hierarchy: `LLMProvider(ABC)` (`providers/base.py`, one abstract
method `chat_stream`) → `OpenAICompatibleProvider` (`providers/openai_compatible_base.py`,
concrete OpenAI-wire implementation; subclasses only set two class attrs
`base_url`/`default_model`) → `ManifestProvider` (6 lines) and
`ZAICodingProvider` (10 lines; base_url `https://api.z.ai/api/coding/paas/v4`,
default_model `glm-5.3`), both zero extra logic.
**To add a new directly-supported OpenAI-compatible backend**: subclass
`OpenAICompatibleProvider`, set `base_url`/`default_model`, wire it into
`create_provider()`, add routing entries to `MODEL_ROUTING`.

`main.py` wires it all together: an `@asynccontextmanager lifespan()` hard-fails
startup if `APP_API_KEY` is unset, creates `data/`, initializes `AnalyticsDB`
onto `app.state.analytics_db`, and closes it on shutdown. Routers are imported
*after* app/middleware setup (`# noqa: E402`) to avoid circular imports — same
reason `rate_limiter.py`'s `Limiter` instance is a standalone module imported by
both `main.py` and `routes/chat.py`. Note: `main.py`'s router import line
(`from routes.analytics import router as analytics_router, analytics_router as
analytics_api_router`) inverts the source names via aliasing — functionally
correct but easy to misread; `routes/analytics.py`'s actual `router` (→ `/v1/models`)
becomes local `analytics_router`, and its `analytics_router` (→ `/v1/analytics/*`
prefix) becomes local `analytics_api_router`.

## Key Directories

| Path | Purpose |
|---|---|
| `routes/` | FastAPI routers — `chat.py` (chat completions + auth dependency), `analytics.py` (models/analytics endpoints) |
| `analytics/` | `db.py` (SQLite/aiosqlite request-log storage + aggregation queries incl. `get_credits_summary()`), `cost.py` (cost stub `0.0` + z.ai credit estimation), `routing.py` (`MODEL_ROUTING` table + `resolve_provider`) |
| `providers/` | Provider abstraction — `base.py` (ABC + TypedDicts), `openai_compatible_base.py` (shared OpenAI-wire impl), `manifest.py` (Manifest provider), `zai_coding.py` (z.ai coding provider), `__init__.py` (factory) |
| `static/playground/` | Zero-build vanilla-JS SPA chat UI for manual testing, served at `GET /playground` and mounted at `/static` |
| `tests/` | pytest suite — see Testing & QA below |
| `docs/` | Mixed current + stale architecture/process docs (see drift warning above) |
| `plans/` | Dated feature-plan folders (`plans/<MMDD-HHMM>-<slug>/plan.md` + `phase-NN.md`) with YAML frontmatter (status/priority/blockedBy/supersedes) — project history/feature areas; `plans/reports/` holds generated retros and per-agent-role review reports |
| `.omx/`, `.claude/agent-memory/` | AI coding-harness telemetry/state and per-role agent memory — **not application code**, orthogonal to the gateway |

## Development Commands

All via `Makefile` (no separate lint target exists):

```bash
make install         # python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
make dev              # uvicorn main:app --reload (auto-copies .env.example -> .env if missing)
make start            # background server (nohup), then make health
make stop             # kill process bound to :8000
make health           # curl http://localhost:8000/health
make test             # .venv/bin/python -m pytest tests/ -v
make test-unit        # pytest tests/ -v -k "not client"   (excludes tests using the `client` fixture)
make test-integration  # pytest tests/ -v -k "client"
make clean            # remove __pycache__, egg-info, dist, build
```

Server runs on `0.0.0.0:8000`. `.ngrok/expose.sh` tunnels that port to a fixed
`ngrok-free.app` subdomain for external testing.

Single test file/function:
```bash
.venv/bin/python -m pytest tests/test_routing.py -v
.venv/bin/python -m pytest tests/test_chat_endpoint.py::test_health_endpoint -v
```

## Code Conventions & Common Patterns

- **Naming**: snake_case for functions/modules/variables; PascalCase for
  classes; UPPER_SNAKE for constants (`MODEL_ROUTING`) and env vars. (Ignore
  `docs/code-standards.md`'s claim of kebab-case filenames — every real file
  uses snake_case; that doc entry is stale/incorrect.)
- **Type hints**: pervasive, modern PEP 604 unions (`str | None`, not
  `Optional[str]`), builtin generics (`list[dict]`, not `typing.List`),
  `TypedDict` for structured payloads (`UsageData`, `GenParams`).
- **Async**: all I/O (DB, HTTP, route handlers) is `async def`; streaming uses
  native async generators; analytics writes go through the lifespan-owned
  bounded `AnalyticsWriter` queue (producers enqueue non-blocking; one consumer
  task serially drains, its task reference held on
  `app.state.analytics_writer`) — never a per-request background task per
  stream; never a bare unawaited coroutine.
- **Error handling**: `HTTPException` for API-facing errors; broad
  `except Exception` around streaming/logging paths that must never crash the
  request, logged via `logger = logging.getLogger(__name__)` (per-module), with
  generic messages returned to clients (no internal exception text leaked).
- **Docstrings**: one-line module docstring on every file explaining purpose/why
  (e.g. `"""Return 0.0 — Manifest handles billing internally."""`); inline
  comments explain non-obvious workarounds (e.g. `# noqa: E402` import ordering,
  `removeprefix` used instead of `replace` for Bearer-token parsing to avoid
  mangling token values that happen to contain "Bearer ").
- **Imports**: stdlib → third-party → local, isort-style grouping. Deferred/local
  imports used deliberately in two places to break circular-import risk:
  `main.py` (router imports after app creation) and `providers/__init__.py`
  (`from providers.manifest import ManifestProvider` inside the factory function —
  as is the matching `ZAICodingProvider` import).
- **Config**: `pydantic_settings.BaseSettings`, not raw `os.environ` — see
  `config.py`. Single module-level singleton `settings = Settings()`.
- **Dependency injection**: `verify_auth` is used consistently via
  `Depends(verify_auth)` (result ignored: `_auth=Depends(...)`) on every
  protected route. `_get_db(request)` in `routes/analytics.py` is a plain
  helper called directly rather than via `Depends` — an inconsistency to be
  aware of, not a convention to copy for new endpoints without considering it.
- **Adding a provider**: the still-valid shape from `docs/code-standards.md`
  (ignore its stale `MODEL_PRICING` cost step): subclass
  `OpenAICompatibleProvider` with `base_url`/`default_model`, register in
  `providers/__init__.py`'s factory, add `MODEL_ROUTING` entries, add an
  optional per-provider API key in `config.py`, run `make test`.

## Important Files

- `main.py` — FastAPI app factory, lifespan (DB init/close, required-env check),
  CORS, rate-limit wiring, `/health`, `/playground`, `/static` mount, router registration.
- `config.py` — `Settings(BaseSettings)` singleton `settings`; `get_api_key(provider)`
  resolves `manifest_api_key` / `zai_coding_api_key`, each with `llm_api_key` fallback.
- `rate_limiter.py` — single shared `slowapi.Limiter` instance (exists as its
  own module specifically to avoid circular imports between `main.py` and `routes/chat.py`).
- `routes/chat.py` — `ChatRequest` model, `verify_auth`, `POST /v1/chat/completions`,
  `_tracked_stream()`.
- `routes/analytics.py` — `GET /v1/models`, `/v1/analytics/{summary,models,requests,credits}`.
- `analytics/db.py` — `AnalyticsDB` (aiosqlite, WAL mode); `request_logs` schema
  (incl. `credits_used`) + 3 indexes (`created_at`, `model`, `provider`).
- `providers/__init__.py` — `create_provider()` factory (dispatches
  `zai-coding` vs. Manifest; extension point documented above).
- `.env.example` — canonical list of required/optional env vars (mirrors
  `Settings` fields exactly): `MANIFEST_API_KEY`, `ZAI_CODING_API_KEY` (optional;
  unset keeps GLM on Manifest), `ZAI_CREDITS_5H`/`ZAI_CREDITS_WEEK` (defaults
  `28000`/`140000`), `LLM_API_KEY` (fallback),
  `APP_API_KEY` (required), `CORS_ORIGINS`, `RATE_LIMIT` (default `60/minute`),
  `ANALYTICS_DB_PATH` (default `data/analytics.db`).

## Runtime/Tooling Preferences

- **Python**: README states 3.12+; local dev artifacts (`__pycache__/*.cpython-314.pyc`)
  and `python3 --version` on this workstation confirm active development
  against **Python 3.14**. No `pyproject.toml`/`.python-version` pins a minimum
  version in the repo — treat 3.12+ (README) as the floor.
- **Package manager**: plain `pip` + `venv` (`make install`), **no lockfile**
  (no `poetry.lock`/`uv.lock`/`requirements-lock.txt`). All deps in
  `requirements.txt` are `>=`-pinned only (fastapi, uvicorn, pydantic-settings,
  openai, python-dotenv, aiosqlite, pytest, pytest-asyncio, httpx, slowapi,
  limits).
- **No linter/formatter configured** — no ruff/black/flake8 config found and
  no `lint` Makefile target exists.
- **Server**: `uvicorn main:app`, port 8000 hardcoded in `Makefile` targets.

## Testing & QA

- **Framework**: pytest (`>=8.0.0`) + `pytest-asyncio` (`>=0.24.0`) +
  `httpx.AsyncClient` over `ASGITransport` (not FastAPI's sync `TestClient`).
- **Config** (`pytest.ini`, full contents):
  ```ini
  [pytest]
  asyncio_mode = auto
  ```
  No coverage tooling configured anywhere. Every async test still carries an
  explicit `@pytest.mark.asyncio` even though `asyncio_mode = auto` makes it
  redundant — keep that decorator on new async tests for consistency.

- **Fixtures** (`tests/conftest.py`, all function-scoped):
  `auth_headers()` (returns `{"Authorization": "Bearer changeme"}`),
  `analytics_db(tmp_path)` (in-memory `AnalyticsDB(":memory:")`, init/close),
  `analytics_writer(analytics_db)` (constructs + starts a real
  `AnalyticsWriter` over the in-memory DB, injects
  `app.state.analytics_writer`, stops it on teardown),
  `client(analytics_db, analytics_writer)` (lazily imports
  `from main import app`, injects both `app.state.analytics_db` and
  `app.state.analytics_writer` — `ASGITransport` never runs the lifespan —
  and yields an `httpx.AsyncClient`).
  Note: `tests/test_analytics_db.py` declares its **own duplicate** `db(tmp_path)`
  fixture instead of reusing `analytics_db` — prefer reusing `analytics_db` for
  new DB-level tests rather than adding another copy.
- **Mocking pattern**: `unittest.mock.patch("routes.chat.create_provider", ...)`
  with `AsyncMock` whose `.chat_stream` is reassigned to a custom async
  generator (see `tests/test_chat_endpoint.py`) — no `monkeypatch`, no
  `app.dependency_overrides` usage anywhere.
- **Selection is via `-k` fixture-name matching, not markers** — no custom
  pytest markers are registered; "unit" vs "integration" split is purely
  `-k "not client"` / `-k "client"` on whether a test takes the `client` fixture.
- **Test files**: `test_chat_endpoint.py` (chat streaming + health, provider
  mocked), `test_cost.py` (cost stub `0.0` + `estimate_credits`/`is_peak`),
  `test_routing.py` (`MODEL_ROUTING`/`resolve_provider`), `test_playground.py`
  (public `/playground` + `/static` mount), `test_analytics_endpoints.py`
  (models + analytics/credits HTTP endpoints, auth required),
  `test_analytics_db.py` (`AnalyticsDB` CRUD/aggregation, no HTTP layer),
  `test_config.py` (Settings + `get_api_key` fallbacks), `test_providers.py`
  (factory dispatch), `test_openai_compatible_base.py` (shared OpenAI-wire
  behavior).
