# Phase 4: Observability & Resilience - Pattern Map

**Mapped:** 2026-09-08
**Files analyzed:** 12 (new + modified)
**Analogs found:** 12 / 12

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `metrics.py` (new) | utility/model (in-process counters) | transform (aggregate-on-write, render-on-read) | `analytics/cost.py` | role-match (pure computation module, no I/O, module-level functions) |
| `main.py` — `GET /metrics` | route | request-response | `main.py` — `GET /health` (existing) | exact (unauthenticated `@app.get` route returning a plain payload, defined before router mounting) |
| `main.py` — `GET /health/live` | route | request-response | `main.py` — `GET /health` (existing) | exact (same signature: no deps, static dict) |
| `main.py` — `GET /health/ready` | route | request-response | `main.py` lifespan `app.state.analytics_db`/`analytics_writer` assignment | role-match (reads lifespan-owned state via `getattr(request.app.state, ...)`, same accessor idiom already used in `routes/chat.py`) |
| `rate_limiter.py` — `extract_bearer_key` | utility (key_func) | request-response | `routes/chat.py` `verify_auth` (Bearer `removeprefix` extraction) | exact (same string-parsing idiom, different consumer) |
| `routes/chat.py` — second `@limiter.limit()` decorator | middleware (decorator) | request-response | `routes/chat.py` existing `@limiter.limit(settings.rate_limit)` | exact (same decorator, stacked) |
| `routes/chat.py` — `metrics.record_request()` call | service (recording side-effect) | event-driven (fire on request completion) | `routes/chat.py` `_tracked_stream`'s existing analytics-writer enqueue (`analytics_writer.log_request(...)` in the `finally`-adjacent block) | exact (same measurement point: latency/status already computed there, second sink) |
| `providers/openai_compatible_base.py` — `max_retries=0` + `AsyncRetrying` wrap | service (resilience wrapper) | request-response (single upstream call, pre-stream) | `providers/openai_compatible_base.py` `chat_stream` itself (self-analog — modifying in place) | exact (same file; only the `create()` call site changes) |
| `config.py` — `rate_limit_per_key` field + validator | config | CRUD (settings load/validate) | `config.py` `rate_limit` field + `_validate_rate_limit` | exact (identical `limits.parse_many` validator pattern, new field name) |
| `.env.example` — `RATE_LIMIT_PER_KEY` row | config | — | `.env.example` `RATE_LIMIT` row | exact |
| `requirements.txt` — `tenacity>=9.0` | config | — | `requirements.txt` `slowapi>=0.1.9` (existing floor-only pin) | exact (same floor-only pin convention) |
| `docker-compose.yml` / `Dockerfile` — healthcheck repoint to `/health/ready` | config | — | `Dockerfile` existing `HEALTHCHECK CMD ... /health` | exact (same `urllib.request.urlopen` idiom, URL changes) |
| `Makefile` — `health` target repoint | config | — | `Makefile` existing `health:` target (`curl -sf http://localhost:8000/health`) | exact (same idiom, URL changes) |
| `tests/test_metrics.py` (new) | test | request-response (httpx assertions) | `tests/test_chat_endpoint.py` `test_health_endpoint` | role-match (unauthenticated-GET-route test shape) |
| `tests/test_openai_compatible_base.py` — new retry tests | test | unit (provider-level `AsyncMock`) | `tests/test_openai_compatible_base.py` `_provider_with_chunks`/`_aiter` helpers (existing, same file) | exact |
| `tests/test_chat_endpoint.py` — new rate-limit + health-split tests | test | integration (ASGI client) | `tests/test_chat_endpoint.py` `test_chat_without_auth_returns_401` / `test_health_endpoint` (existing, same file) | exact |

## Pattern Assignments

### `metrics.py` (new module — utility, transform)

**Analog:** `analytics/cost.py` (module-level pure functions, no class, no I/O) — read for the "small stateless computation module" convention this repo uses instead of a class wrapper.

No direct excerpt needed beyond convention: no `class`, top-level `def` functions, imported by name (`import metrics as gateway_metrics` in `main.py`, `import metrics` in `routes/chat.py`), consistent with how `analytics/cost.py`'s `calculate_cost`/`estimate_credits` are imported directly into `routes/chat.py`:
```python
# routes/chat.py:13 (existing import convention to replicate for metrics.py)
from analytics.cost import calculate_cost, estimate_credits
```
Full `metrics.py` reference implementation (counters + histogram + text-exposition `render()`) is in `04-RESEARCH.md` Pattern 1 — copy verbatim, it was verified against the installed Starlette/Prometheus spec this session, not invented.

**Safety note (from RESEARCH.md, applies here):** module-level `dict`/`defaultdict` state, no locks — safe because `uvicorn main:app` runs single-process/single-event-loop (no `--workers`, confirmed in `Dockerfile` CMD).

---

### `main.py` — `GET /metrics`, `GET /health/live`, `GET /health/ready` (route, request-response)

**Analog:** `main.py`'s own existing `/health` route (lines 87-89 — being replaced/split).

**Existing pattern to replace** (`main.py:87-89`):
```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Placement convention** (from `main.py:1-89` structure): routes are declared directly on `app` *before* the deferred router imports (`main.py:91-96` — `from routes.analytics import ...` / `from routes.chat import ...`, noted `# noqa: E402` for the deliberate deferred-import-to-avoid-circular-deps pattern). New `/metrics`, `/health/live`, `/health/ready` routes go in this same pre-router-mount block, replacing the single `/health` block at the same location.

**Imports already present in `main.py`** (reuse, no new import needed for `Response`... note FastAPI's `Response` is not currently imported — add `from fastapi import FastAPI, Request` — `Request` also not yet imported at module scope, needed for `/health/ready`'s `request.app.state` access):
```python
# main.py:6-15 (existing import block — extend, don't replace)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from analytics.db import AnalyticsDB
from analytics.writer import AnalyticsWriter
from config import settings
from rate_limiter import limiter
```

**Readiness state-read pattern** — reuse the exact `getattr(request.app.state, "X", None)` idiom already used in `routes/chat.py` (not a new idiom):
```python
# routes/chat.py:53 (existing idiom to replicate in main.py's /health/ready)
analytics_writer = getattr(request.app.state, "analytics_writer", None)
```

**Lifespan state-assignment being read** (`main.py:60-63` — proves presence-of-both-attributes is the correct readiness signal, since they're only set after `db.write_probe()` succeeds and `writer.start()` runs):
```python
    writer.start()
    app.state.analytics_db = db
    app.state.analytics_writer = writer
```

Full route bodies for all three endpoints are in `04-RESEARCH.md` Pattern 1 (`/metrics`) and Pattern 4 (`/health/live`, `/health/ready`) — copy verbatim.

---

### `rate_limiter.py` — `extract_bearer_key` (utility, request-response)

**Analog:** `routes/chat.py`'s `verify_auth` (lines 35-41) — same Bearer-stripping idiom, different destination (rate-limit key vs. auth comparison).

**Current full file** (`rate_limiter.py` — to be extended, not replaced):
```python
"""Rate limiter instance — shared across modules to avoid circular imports."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])
```

**Bearer-extraction idiom to copy** (`routes/chat.py:35-41`):
```python
def verify_auth(authorization: str = Header(...)):
    """Bearer token authentication dependency."""
    # Use removeprefix to avoid replacing "Bearer " inside the token value
    token = authorization.removeprefix("Bearer ").removeprefix("bearer ")
    if token != settings.app_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
```

**New function** (adapts the above to a slowapi `key_func(request: Request) -> str`, reading the header via `request.headers.get` since there's no FastAPI `Header(...)` dependency-injection available inside a bare `key_func`):
```python
from starlette.requests import Request

def extract_bearer_key(request: Request) -> str:
    """Per-key rate-limit identity: the Bearer token itself, falling back to
    remote IP when missing/malformed (same removeprefix idiom as verify_auth)."""
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").removeprefix("bearer ")
    return token or get_remote_address(request)
```

---

### `routes/chat.py` — stacked rate limiter + metrics recording (middleware + service, request-response/event-driven)

**Analog:** the file's own existing `@limiter.limit()` decorator and `_tracked_stream`'s measurement point (self-analog — modifying in place).

**Existing decorator to stack alongside** (`routes/chat.py:47-48`):
```python
@router.post("/v1/chat/completions")
@limiter.limit(settings.rate_limit)
async def chat(request: Request, body: ChatRequest, _auth=Depends(verify_auth)):  # noqa: B008 -- FastAPI DI convention
```
**New stacked form** (add import `extract_bearer_key` alongside the existing `limiter` import at `routes/chat.py:15`):
```python
from rate_limiter import extract_bearer_key, limiter
...
@router.post("/v1/chat/completions")
@limiter.limit(settings.rate_limit)                                       # existing, per-IP
@limiter.limit(settings.rate_limit_per_key, key_func=extract_bearer_key)   # NEW, per-key
async def chat(request: Request, body: ChatRequest, _auth=Depends(verify_auth)):  # noqa: B008
```
Decoration order does not matter for slowapi's own accumulation mechanics (per RESEARCH.md Pattern 3, verified against `slowapi/extension.py`), but keep the existing decorator first and the new one directly beneath it for readability/diff-minimality.

**Metrics-recording insertion point** — `_tracked_stream`'s existing measurement variables (`start_time`, computed status, `provider_name`, `model_id`) already exist for analytics; add one call using the same values, at the same point analytics logging happens (`routes/chat.py:46-100`, `start_time = time.monotonic()` at entry, `error_msg` set in the `except` block):
```python
# routes/chat.py:52 (existing) — read for the field names to reuse:
start_time = time.monotonic()
...
# existing except block sets error_msg; existing success path has no error_msg
# New: call metrics.record_request(provider_name, model_id, status, duration_s)
# at the same point analytics_writer.log_request(...) is already called
# (immediately before "yield 'data: [DONE]\n\n'"), reusing time.monotonic() - start_time
# and status derived exactly like the analytics row's existing "status" field.
```
No new measurement is introduced — this is a second sink off the same already-computed `latency_ms`/`status` values the analytics writer consumes (confirmed by RESEARCH.md's Architectural Responsibility Map: "same code path... independent sink from the same measurement, not a new measurement").

---

### `providers/openai_compatible_base.py` — `max_retries=0` + `AsyncRetrying` (service, request-response)

**Analog:** the file itself (self-analog, in-place modification) — full current content already read in full above (23 lines total, well under the 2,000-line large-file threshold; no `Grep`/offset needed).

**Current constructor** (to modify):
```python
class OpenAICompatibleProvider(LLMProvider):
    base_url: str = ""
    default_model: str = ""

    def __init__(self, api_key: str, model: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
        self.model = model or self.default_model
```
**New constructor** (add `max_retries=0` — required per RESEARCH.md Pitfall 2, not called out in CONTEXT.md but mandatory for ZAI-3 compliance):
```python
        self.client = AsyncOpenAI(api_key=api_key, base_url=self.base_url, max_retries=0)
```

**Current upstream call site** (to wrap, not the surrounding generator):
```python
        stream = await self.client.chat.completions.create(**kwargs)

        async for chunk in stream:
```
**New wrapped form** (construct `AsyncRetrying` inline, call it directly on the coroutine — never decorate `chat_stream` itself, per Pitfall 1):
```python
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from openai import APIConnectionError, APITimeoutError, InternalServerError

_RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError)
...
        retryer = AsyncRetrying(
            stop=stop_after_attempt(3),  # "max 2 retries" (locked) == 3 total attempts
            wait=wait_exponential_jitter(initial=0.5, max=8.0),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,  # preserves original .status_code for routes/chat.py's error mapping
        )
        stream = await retryer(self.client.chat.completions.create, **kwargs)

        async for chunk in stream:   # NEVER retried past this point
```
Full verified rationale (allow-list vs. deny-list, `reraise=True` necessity, why the generator itself must not be decorated) is in `04-RESEARCH.md` Pattern 2 and Pitfalls 1-3 — read those sections directly when planning the retry task; they document exact line numbers read in the `openai`/`tenacity` SDK source this session.

**Downstream consumer unchanged** — `routes/chat.py`'s existing error-mapping reads `getattr(e, "status_code", None)` (already excerpted in the File Classification's `_tracked_stream` analog above); `reraise=True` is what keeps this contract intact after retry exhaustion.

---

### `config.py` — `rate_limit_per_key` field + validator (config, CRUD)

**Analog:** `config.py`'s own `rate_limit` field + `_validate_rate_limit` validator (lines that follow, in the same file — self-analog).

**Existing field + validator to replicate exactly** (`config.py`):
```python
    # Rate limiting
    rate_limit: str = "60/minute"  # Max requests per window per client
...
    @model_validator(mode="after")
    def _validate_rate_limit(self) -> "Settings":
        """Fail fast on malformed RATE_LIMIT — slowapi would defer it to request time."""
        try:
            parsed = list(parse_many(self.rate_limit))
        except ValueError as e:
            raise ValueError(
                f"RATE_LIMIT is not a valid rate string (expected e.g. '60/minute'): "
                f"{self.rate_limit!r} ({e})"
            ) from e
        if not parsed:
            raise ValueError(f"RATE_LIMIT parsed to zero limits: {self.rate_limit!r}")
        return self
```
**New field + validator** (identical shape, new name; per RESEARCH.md Assumption A2, default matches existing `rate_limit`'s `"60/minute"` absent a locked number in CONTEXT.md):
```python
    rate_limit_per_key: str = "60/minute"  # Max requests per window per Bearer token
...
    @model_validator(mode="after")
    def _validate_rate_limit_per_key(self) -> "Settings":
        """Fail fast on malformed RATE_LIMIT_PER_KEY — same reasoning as _validate_rate_limit."""
        try:
            parsed = list(parse_many(self.rate_limit_per_key))
        except ValueError as e:
            raise ValueError(
                f"RATE_LIMIT_PER_KEY is not a valid rate string (expected e.g. '60/minute'): "
                f"{self.rate_limit_per_key!r} ({e})"
            ) from e
        if not parsed:
            raise ValueError(f"RATE_LIMIT_PER_KEY parsed to zero limits: {self.rate_limit_per_key!r}")
        return self
```

---

### `.env.example` — `RATE_LIMIT_PER_KEY` row (config)

**Analog:** the existing `RATE_LIMIT` row and comment style.

```
# Rate limiting (per client IP)
RATE_LIMIT=60/minute
```
**New row directly below it:**
```
# Rate limiting (per Bearer token; both this and RATE_LIMIT apply)
RATE_LIMIT_PER_KEY=60/minute
```

---

### `requirements.txt` — `tenacity` (config)

**Analog:** the existing floor-only pin convention (every line uses `>=`, no upper bound, no pinned patch version):
```
slowapi>=0.1.9
limits>=3.5
```
**New line** (append at end, matching convention exactly):
```
tenacity>=9.0
```

---

### `Dockerfile` / `docker-compose.yml` — healthcheck repoint (config)

**Analog:** the existing `Dockerfile` `HEALTHCHECK` (self-analog, in-place edit — `docker-compose.yml` currently has no explicit `healthcheck:` block, only relies on the Dockerfile's `HEALTHCHECK`, confirmed by reading the full `docker-compose.yml` above: no `healthcheck` key present).

**Existing (`Dockerfile`):**
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
```
**New (URL changes only, same idiom, same `urllib.request` no-new-dependency approach):**
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)" || exit 1
```
`docker-compose.yml` needs no change unless CONTEXT.md's Compose-repoint note is interpreted as adding an explicit `healthcheck:` override — current file has none, so the Dockerfile-level change alone satisfies "Compose healthcheck repoints to `/health/ready`" (Compose inherits the image's `HEALTHCHECK` when no service-level override exists). If the planner adds a `prometheus` profile service (RESEARCH.md's optional Compose addition), place it as a new top-level `services:` entry alongside `gateway:`, following the existing single-service file's flat structure (no `depends_on`/network config currently present to extend).

---

### `Makefile` — `health` target repoint (config)

**Analog:** the existing `health:` target (self-analog).

**Existing:**
```makefile
# Health check
health:
	@curl -sf http://localhost:8000/health && echo "" || echo "Server not responding"
```
**New (per RESEARCH.md Open Question 1's recommendation — repoint to `/health/ready` for consistency with the Dockerfile):**
```makefile
# Health check
health:
	@curl -sf http://localhost:8000/health/ready && echo "" || echo "Server not responding"
```
Note: `make start` calls `make health` right after backgrounding the server (`Makefile` `start:` target) — `/health/ready` requires the lifespan's DB init + writer start to have completed, which is consistent with `start:`'s existing `sleep 1` grace period before invoking `make health`.

---

### Tests

**`tests/test_metrics.py` (new)** — analog `tests/test_chat_endpoint.py::test_health_endpoint`:
```python
@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health check returns 200 with ok status."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```
Same shape (unauthenticated GET via the `client` fixture, no `auth_headers`) applies to `/metrics`, `/health/live`, `/health/ready` — reuse the `client` fixture from `tests/conftest.py` unmodified; `/health/ready` is testable as `200` under the existing fixture because `client` already injects `app.state.analytics_db`/`analytics_writer` directly (see conftest excerpt below).

**`tests/test_openai_compatible_base.py` — new retry tests** — analog: the file's own existing helpers (already excerpted above in full, `_provider_with_chunks`/`_aiter`/`_chunk`/`_usage`). For retry-succeeds-on-2nd-attempt and retry-exhaustion tests, set:
```python
provider.client = SimpleNamespace(
    chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(side_effect=[exc1, exc2, _aiter(chunks)])  # fails twice, succeeds 3rd
    ))
)
```
or `side_effect=exc` (always fails → exhausts retries, re-raises `exc` with `reraise=True`). This is the exact convention from RESEARCH.md's "Existing test-mocking convention" section — `AsyncMock` satisfies tenacity's coroutine-callable check identically to the real bound method.

**`tests/test_chat_endpoint.py` — new rate-limit + health-split tests** — analog: existing `test_chat_without_auth_returns_401` (429-before-provider-call shape) and the `patch("routes.chat.create_provider", ...)` convention from `test_chat_with_model`:
```python
# tests/test_chat_endpoint.py:1-6 (existing imports — reuse, no new imports needed for rate-limit tests)
from unittest.mock import AsyncMock, patch
import pytest
```
For "429 before any provider call," assert on a mocked `create_provider` the same way `test_chat_with_model` does, but assert it was **not called** when the per-key limit is exceeded — `patch("routes.chat.create_provider", ...)` is the existing, only mocking seam for provider construction in this file.

**`tests/conftest.py` fixtures — no changes needed** — the existing `client` fixture already injects `app.state.analytics_db`/`app.state.analytics_writer` directly (since `ASGITransport` never runs the real `lifespan`):
```python
@pytest_asyncio.fixture
async def client(analytics_db, analytics_writer, monkeypatch):
    """Async test client with analytics DB + writer injected."""
    from main import app
    monkeypatch.setattr(settings, "app_api_key", "changeme")
    app.state.analytics_db = analytics_db
    app.state.analytics_writer = analytics_writer
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```
This is why `/health/ready` returns `200` under the existing fixture with zero fixture changes — both `app.state` attributes are already present by the time any test runs.

## Shared Patterns

### Bearer-token extraction (removeprefix idiom)
**Source:** `routes/chat.py:35-41` (`verify_auth`)
**Apply to:** `rate_limiter.py`'s new `extract_bearer_key` — same `.removeprefix("Bearer ").removeprefix("bearer ")` chain, different consumer (rate-limit key vs. auth comparison).

### `getattr(request.app.state, "X", None)` lifespan-state read
**Source:** `routes/chat.py:53` (`analytics_writer = getattr(request.app.state, "analytics_writer", None)`)
**Apply to:** `main.py`'s new `/health/ready` route — reads both `analytics_db` and `analytics_writer` off `app.state` the same defensive-`getattr` way, never assuming lifespan ran (matches how `routes/chat.py` already defends against `ASGITransport`-under-test not running the lifespan).

### `limits.parse_many` fail-fast validator
**Source:** `config.py` `_validate_rate_limit`
**Apply to:** new `_validate_rate_limit_per_key` — identical try/except/raise shape, new field name substituted throughout the error messages.

### Floor-only dependency pins (`>=`, no upper bound)
**Source:** `requirements.txt` (every existing line)
**Apply to:** new `tenacity>=9.0` line.

### `AsyncMock(side_effect=[...])` provider-level test seam
**Source:** `tests/test_openai_compatible_base.py` `_provider_with_chunks` (existing helper, unmodified)
**Apply to:** new retry-behavior tests in the same file — swap `return_value=_aiter(chunks)` for `side_effect=[exc, exc, _aiter(chunks)]` or `side_effect=exc`; no new fixture/helper needed.

### `patch("routes.chat.create_provider", ...)` route-level test seam
**Source:** `tests/test_chat_endpoint.py::test_chat_with_model`
**Apply to:** new per-key-rate-limit integration test — assert `create_provider` not called when the 429 path is hit.

## No Analog Found

None — every file in the expected surface (CONTEXT.md's inventory plus RESEARCH.md's `metrics.py`/`prometheus/prometheus.yml` additions) has a direct in-repo analog, either an existing sibling pattern or itself (in-place modification). The only genuinely new architectural surface is `metrics.py`, which has no prior in-process-counters module in this codebase — its closest analog is `analytics/cost.py` for *module shape* (stateless-function-module convention), not for its content (which is fully specified by the external, fixed Prometheus text-exposition wire format documented in RESEARCH.md Pattern 1, not by codebase precedent).

## Metadata

**Analog search scope:** repo root (`main.py`, `rate_limiter.py`, `config.py`, `.env.example`, `docker-compose.yml`, `Dockerfile`, `Makefile`, `requirements.txt`), `routes/`, `providers/`, `analytics/`, `tests/`
**Files scanned:** `main.py`, `rate_limiter.py`, `routes/chat.py`, `providers/openai_compatible_base.py`, `config.py`, `.env.example`, `docker-compose.yml`, `Dockerfile`, `Makefile`, `requirements.txt`, `tests/conftest.py`, `tests/test_chat_endpoint.py`, `tests/test_openai_compatible_base.py`, `analytics/cost.py` (referenced for module-shape convention)
**Tracked-source gate:** all analog paths above verified via `git ls-files` — none are gitignored mirrors (no `.gsd/capabilities/` or similar sync paths involved; this repo has no submodule/capability-mirror structure).
**Pattern extraction date:** 2026-09-08

## PATTERN MAPPING COMPLETE

**Phase:** 4 - Observability & Resilience
**Files classified:** 16 (12 source/config files + 4 test targets, counting `main.py`'s three new routes as one file)
**Analogs found:** 16 / 16

### Coverage
- Files with exact analog: 13
- Files with role-match analog: 3 (`metrics.py`, `main.py::/health/ready`, `tests/test_metrics.py`)
- Files with no analog: 0

### Key Patterns Identified
- Every new route (`/metrics`, `/health/live`, `/health/ready`) follows the existing bare `@app.get(...)` + no-auth `/health` convention already in `main.py`, placed in the same pre-router-mount block.
- Retry wraps only the single pre-stream `create()` coroutine via a manually-constructed `AsyncRetrying(...)` call — never a `@retry` decorator on `chat_stream` (an async generator), and must pair with `max_retries=0` on `AsyncOpenAI` construction to avoid double-retrying z.ai quota errors at the SDK layer (ZAI-3 compliance).
- Per-key rate limiting stacks a second `@limiter.limit(..., key_func=extract_bearer_key)` decorator directly beneath the existing per-IP one — same `Limiter` instance, no new storage backend, `extract_bearer_key` reuses `verify_auth`'s exact `removeprefix` idiom.
- Every config addition (`config.py` field+validator, `.env.example` row, `requirements.txt` pin) copies an existing sibling line-for-line, substituting only the name.

### File Created
`/Users/ddphuong/Projects/next-labs/llm-gateway/.planning/phases/04-observability-resilience/04-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog patterns in PLAN.md files.
