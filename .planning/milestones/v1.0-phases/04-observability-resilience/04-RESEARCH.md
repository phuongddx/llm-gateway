# Phase 4: Observability & Resilience - Research

**Researched:** 2026-09-08
**Domain:** Hand-rolled Prometheus metrics, dual-key-func slowapi rate limiting, tenacity retry around a streaming OpenAI-compatible client, FastAPI liveness/readiness split
**Confidence:** HIGH

## Summary

Phase 4 adds three independent, narrowly-scoped capabilities to an already-shipped FastAPI gateway: a hand-rolled `/metrics` endpoint (no `prometheus_client` dependency), a second slowapi rate limit keyed on the Bearer token (stacked alongside the existing per-IP limit on the same route), and a `tenacity`-driven retry wrapped **only** around the initial upstream `create()` call inside `OpenAICompatibleProvider.chat_stream()` — never around the token-streaming loop itself. All three integrate into existing, small files (`main.py`, `rate_limiter.py`, `routes/chat.py`, `providers/openai_compatible_base.py`) with no new architectural layers.

The single most important finding, uncovered by reading the installed `openai==2.32.0` SDK source rather than assuming: **`AsyncOpenAI` already retries HTTP 429 and 5xx internally, up to `DEFAULT_MAX_RETRIES=2`, before any exception reaches application code** (`_base_client.py:778-811`, `_constants.py:10`). Today, `OpenAICompatibleProvider.__init__` constructs `AsyncOpenAI(api_key=..., base_url=...)` with no `max_retries` override, so **z.ai quota-exhaustion errors (HTTP 429) are already being silently retried twice by the SDK itself** before the application's ZAI-3 "never retry quota" logic ever sees them — a pre-existing, undocumented violation of the spirit of ZAI-3 that predates this phase. Phase 4 must set `max_retries=0` on the `AsyncOpenAI` construction so tenacity becomes the **only** retry layer, with a predicate that is an **allow-list** (`APIConnectionError`, `APITimeoutError`, `openai.InternalServerError` — i.e. only connection/timeout/5xx) rather than a deny-list — because the existing z.ai "1113" balance-exhaustion detection matches on substring in the exception message at **any** status code (test fixtures use `status_code = 402` for it), so a deny-list keyed on `RateLimitError`/`AuthenticationError` classes alone would not reliably exclude it. An allow-list closes that gap by construction.

The second key finding: `chat_stream` is an async generator, and tenacity's `@retry` decorator cannot correctly wrap an async generator function (calling it returns a generator object immediately, without awaiting anything — nothing gets retried). The correct, idiomatic tenacity pattern verified against the installed `tenacity==9.1.4` source is to construct an `AsyncRetrying` instance and call it directly on the one coroutine that should be retried: `stream = await retryer(self.client.chat.completions.create, **kwargs)`. This also matches the empirical behavior of the openai SDK: the HTTP request (headers + status code) is fully resolved inside `create()` before it returns — `raise_for_status()` and exception mapping happen there (`_base_client.py:1677-1698`) — so failures that happen **after** the first token has already been yielded to the client (a dropped connection mid-stream) are a `StopAsyncIteration`/read-error surfaced from the `async for` loop, not from `create()`, and are correctly **not** retried (retrying there would require replaying already-sent tokens to the client, which nothing in this design does or should do).

Third: slowapi's `Limiter.limit()` decorator accepts a **per-call `key_func` override** (`extension.py:783-821`). Stacking two `@limiter.limit(...)` decorators on the same route — one with the default `key_func=get_remote_address`, one with a new Bearer-token-extracting `key_func` — is the correct, already-supported mechanism for "both apply" (locked decision). No second `Limiter` instance, no custom middleware, and no dual-storage-backend concern is needed; slowapi accumulates both `Limit` objects under the same route-registration key (by `func.__module__.__qualname__`, preserved across `functools.wraps` layers) and evaluates them together in one `__evaluate_limits()` pass per request, short-circuiting with a 429 on whichever limit is hit first — always before the route body (and therefore before any provider call) executes.

**Primary recommendation:** Implement all three capabilities as small, additive changes to the four files CONTEXT.md already names — a new `metrics.py` module (in-memory counters, safe without locks because this is a single-process asyncio app with `uvicorn main:app` and no worker forking), a new `extract_bearer_key` function in `rate_limiter.py` stacked as a second `@limiter.limit()` decorator in `routes/chat.py`, and an `AsyncRetrying`-based wrapper around the `create()` call in `providers/openai_compatible_base.py` with `max_retries=0` on the `AsyncOpenAI` client construction.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| `/metrics` exposition | API / Backend (`main.py` route) | — | In-process counters; single-container target has no separate metrics-aggregation tier |
| Metrics recording | API / Backend (`routes/chat.py` `_tracked_stream` finally block) | — | Same code path that already computes `latency_ms`/`status` for analytics; metrics recording is a second, independent sink from the same measurement, not a new measurement |
| Per-key rate limiting | API / Backend (`rate_limiter.py` + route decorator) | — | Enforced before the route body runs, in-process; no external rate-limit store (`memory://` storage, matching existing `Limiter`) |
| Health liveness | API / Backend (`main.py` route, no dependencies) | — | Process-up check; must never depend on DB/writer state |
| Health readiness | API / Backend (`main.py` route, reads `app.state`) | Database / Storage (via `AnalyticsDB`/`AnalyticsWriter` state) | Readiness is a read of already-existing lifespan-owned state, not a new subsystem |
| Retry policy | API / Backend (`providers/openai_compatible_base.py`) | — | Same-provider only; must stay below the `LLMProvider` ABC boundary so `ZAICodingProvider`/`ManifestProvider` get it for free with zero code |
| Compose Prometheus profile | Deployment / Infra (`docker-compose.yml`, new `prometheus/prometheus.yml`) | — | Optional sidecar scraping `/metrics`; no code-level coupling |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---|---|---|---|
| `tenacity` | `9.1.4` (installed; add to `requirements.txt` per locked decision) | Retry with exponential backoff + jitter | Locked user decision (explicit NFR-02 deviation); de facto standard async-aware Python retry library (10 years old, Apache-2.0, `jd/tenacity`) |

No other new runtime dependencies. `slowapi`/`limits` (already in `requirements.txt`) cover per-key rate limiting via a second `key_func`; the metrics endpoint is hand-rolled text per the locked NFR-02 preference — `prometheus_client` is explicitly not added.

**Installation:**
```bash
pip install tenacity==9.1.4   # add "tenacity>=9.0" to requirements.txt (repo convention: floor-only >= pins)
```

**Version verification:** `tenacity==9.1.4` confirmed installed in `.venv` via `pip show tenacity` [VERIFIED: local `.venv/lib/python3.14/site-packages/tenacity` — read this session]; PyPI metadata confirms `requires_python = ">=3.10"` (compatible with the repo's 3.12+ floor and the CI matrix's 3.12/3.14) and lists Python 3.14 as a supported classifier [VERIFIED: pypi.org/pypi/tenacity/json — fetched this session]. `slowapi==0.1.9` / `limits==5.8.0` confirmed installed [VERIFIED: `.venv` `pip show slowapi limits` — run this session]; `openai==2.32.0` confirmed installed [VERIFIED: `.venv` `python -c "import openai; print(openai.__version__)"` — run this session].

### Supporting

| Library | Version | Purpose | When to Use |
|---|---|---|---|
| `prom/prometheus` (Docker image, not a Python dep) | latest | Optional Compose profile scraping `/metrics` | Only if the operator opts into the `observability` Compose profile |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| Hand-rolled text exposition | `prometheus_client` | Rejected — locked NFR-02 preference; hand-rolled also sidesteps `prometheus_client`'s multiprocess-mode complexity, which this single-process `uvicorn` deployment doesn't need anyway |
| Two `slowapi.Limiter` instances (one per key scheme) | One `Limiter`, two stacked `@limiter.limit()` decorators with different `key_func` | Two instances would double the storage backend surface and exception-handler wiring for no benefit — slowapi already supports multiple limits per route natively |
| `tenacity.retry` decorator on `chat_stream` | `AsyncRetrying` instance called inline on the `create()` coroutine only | Decorating an async generator function with `@retry` does not retry anything meaningful — see Pitfall 1 |

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---|---|---|---|---|---|---|
| `tenacity` | PyPI | ~10 years (first release 2016-08-25, per PyPI release history) | Extremely high (dependency of `boto3`/AWS SDKs, `langchain`, `huggingface_hub`, etc. — common transitive dep; exact download count not machine-fetched but ownership/age/activity are unambiguous) | `github.com/jd/tenacity` (owner: Julien Danjou, co-owner `sileht`) | OK | Approved |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

`tenacity` metadata (author, license Apache-2.0, `requires_python`, classifiers through Python 3.14, active current release `9.1.4`) verified directly against `pypi.org/pypi/tenacity/json` this session [VERIFIED: pypi.org/pypi/tenacity/json]. No cross-ecosystem confusion risk (single well-known name, not confusable with an npm/crates package of the same name in this context).

## Architecture Patterns

### System Architecture Diagram

```
Client
  │  POST /v1/chat/completions  (Authorization: Bearer <key>)
  ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI route "chat" (routes/chat.py)                       │
│  1. verify_auth()              — 401 if key wrong            │
│  2. @limiter.limit(RATE_LIMIT)          — per-IP  (existing) │
│  3. @limiter.limit(RATE_LIMIT_PER_KEY)  — per-key (NEW)      │──429──▶ client (no provider call made)
│     both evaluated together, in decorator order, before      │
│     the route body runs                                      │
└─────────────────────────────────────────────────────────────┘
  │ (within limits)
  ▼
resolve_provider(model) → create_provider(provider_name, model_id)
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ OpenAICompatibleProvider.chat_stream()                       │
│   AsyncRetrying(stop=stop_after_attempt(3),                   │
│                 wait=wait_exponential_jitter(...),            │
│                 retry=retry_if_exception_type(                │
│                     APIConnectionError, APITimeoutError,      │
│                     openai.InternalServerError))               │
│   stream = await retryer(client.chat.completions.create, …)  │──(quota/auth/4xx: reraise immediately, no retry)
│   async for chunk in stream:   ← NEVER retried past this point│
│       yield tokens                                            │
└─────────────────────────────────────────────────────────────┘
  │ tokens                                  │ exception (after retry exhaustion, if transient;
  ▼                                          │ or immediately, if quota/auth/other)
_tracked_stream() (routes/chat.py)           ▼
  - emits SSE token frames                existing provider-distinct error mapping
  - records metrics.record_request(...)   (unchanged — reused as-is)
    → in-process counters (metrics.py)
  - enqueues analytics row (unchanged)
  │
  ▼
GET /metrics  (unauthenticated, text/plain; version=0.0.4)
  ← scraped by optional Compose "prometheus" profile service

GET /health/live   → {"status": "ok"}  (no dependencies — process-up check)
GET /health/ready  → 200 iff app.state.analytics_db + app.state.analytics_writer
                     were set by a successful lifespan startup; else 503
                     ← Dockerfile HEALTHCHECK repoints here
```

### Recommended Project Structure

No new top-level directories. New files:
```
metrics.py                     # module-level counters/histogram + text-exposition renderer
prometheus/prometheus.yml       # scrape config for the optional Compose profile (new dir, deployment-only)
```
Modified files (per CONTEXT.md's own inventory — confirmed accurate by reading each):
```
main.py                         # /metrics, /health/live, /health/ready (replaces /health)
rate_limiter.py                 # + extract_bearer_key(request) -> str
routes/chat.py                  # + second @limiter.limit() decorator; + metrics.record_request() call
providers/openai_compatible_base.py   # + max_retries=0, + AsyncRetrying wrapper around create()
config.py                       # + rate_limit_per_key: str field + validator
requirements.txt                # + tenacity
docker-compose.yml              # + optional "prometheus" profile service
Dockerfile                      # HEALTHCHECK CMD repoints from /health to /health/ready
Makefile                        # `make health` target — recommend repointing to /health/ready (see Open Questions)
.env.example, README.md         # + RATE_LIMIT_PER_KEY row/section
```

### Pattern 1: Hand-rolled Prometheus text exposition (format 0.0.4)

**What:** A plain-text response conforming to the Prometheus text exposition format, built by string formatting over in-memory counters — no client library.
**When to use:** `GET /metrics`, unauthenticated, per locked decision.

Verified format rules (fetched from the canonical spec this session) [CITED: prometheus.io/docs/instrumenting/exposition_formats/]:
- One `# HELP <name> <docstring>` and one `# TYPE <name> <counter|gauge|histogram|summary|untyped>` line per metric name, appearing **before** the first sample line for that name; `HELP`/`TYPE` lines are optional but recommended and each may appear **at most once** per metric name.
- Sample line syntax: `metric_name{label="value",...} value [timestamp]` — labels double-quoted, `\`, `"`, and `\n` in label values must be escaped as `\\`, `\"`, `\n`.
- **Histogram** representation (must-follow, not optional): for a histogram named `x`, emit `x_bucket{le="<upper-bound>"} <cumulative-count>` per bucket in **increasing numerical order** of `le`, a mandatory final bucket `x_bucket{le="+Inf"} <value>` whose value **must equal** `x_count`, plus separate `x_sum <total>` and `x_count <count>` lines (not labeled with `le`).
- Content-Type: `text/plain` with parameter `version=0.0.4`; **as of Prometheus 3.0, scrape targets must return a valid, parseable `Content-Type` header or the scrape fails outright** — this is not optional/cosmetic.

Confirmed via reading the installed Starlette version this session [VERIFIED: `.venv/lib/python3.14/site-packages/starlette/responses.py:75-79`]: passing `media_type="text/plain; version=0.0.4"` to a `Response`/`PlainTextResponse` causes Starlette to append `; charset=utf-8` automatically (media types starting `text/` without an existing `charset=` get one appended), producing a final header of `text/plain; version=0.0.4; charset=utf-8` — this matches `prometheus_client`'s own `CONTENT_TYPE_LATEST` convention and is safe to rely on rather than building the header string manually.

```python
# metrics.py — new module
"""In-process Prometheus text-exposition metrics (hand-rolled, no prometheus_client)."""

from collections import defaultdict

# Standard latency buckets (seconds) — same defaults prometheus_client ships;
# [ASSUMED] a reasonable choice, not a requirement — adjust if request latency
# profile differs materially.
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)

# Safe without locks: single-process asyncio event loop (uvicorn main:app,
# no worker forking per Dockerfile CMD) — no preemptive thread interleaving
# between a dict increment and its read.
_requests_total: dict[tuple[str, str, str], int] = defaultdict(int)
_duration_bucket_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * len(_BUCKETS))
_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
_duration_count: dict[tuple[str, str], int] = defaultdict(int)


def record_request(provider: str, model: str, status: str, duration_s: float) -> None:
    _requests_total[(provider, model, status)] += 1
    key = (provider, model)
    _duration_sum[key] += duration_s
    _duration_count[key] += 1
    buckets = _duration_bucket_counts[key]
    for i, upper in enumerate(_BUCKETS):
        if duration_s <= upper:
            buckets[i] += 1


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render() -> str:
    lines = [
        "# HELP gateway_requests_total Total chat completion requests.",
        "# TYPE gateway_requests_total counter",
    ]
    for (provider, model, status), count in sorted(_requests_total.items()):
        lines.append(
            f'gateway_requests_total{{provider="{_escape(provider)}",'
            f'model="{_escape(model)}",status="{_escape(status)}"}} {count}'
        )
    lines += [
        "# HELP gateway_request_duration_seconds Request latency in seconds.",
        "# TYPE gateway_request_duration_seconds histogram",
    ]
    for (provider, model) in sorted(_duration_count):
        key = (provider, model)
        cumulative = 0
        for i, upper in enumerate(_BUCKETS):
            cumulative += _duration_bucket_counts[key][i]
            lines.append(
                f'gateway_request_duration_seconds_bucket{{provider="{_escape(provider)}",'
                f'model="{_escape(model)}",le="{upper}"}} {cumulative}'
            )
        lines.append(
            f'gateway_request_duration_seconds_bucket{{provider="{_escape(provider)}",'
            f'model="{_escape(model)}",le="+Inf"}} {_duration_count[key]}'
        )
        lines.append(
            f'gateway_request_duration_seconds_sum{{provider="{_escape(provider)}",'
            f'model="{_escape(model)}"}} {_duration_sum[key]}'
        )
        lines.append(
            f'gateway_request_duration_seconds_count{{provider="{_escape(provider)}",'
            f'model="{_escape(model)}"}} {_duration_count[key]}'
        )
    return "\n".join(lines) + "\n"
```

```python
# main.py addition
from fastapi import Response
import metrics as gateway_metrics

@app.get("/metrics")
async def get_metrics():
    return Response(content=gateway_metrics.render(), media_type="text/plain; version=0.0.4")
```

Error rate is **derived**, not a fourth metric — `gateway_requests_total{status="error"}` divided by the same series summed over all `status` values is a PromQL-side computation (`sum(rate(gateway_requests_total{status="error"}[5m])) / sum(rate(gateway_requests_total[5m]))`), matching CONTEXT.md's "error rate derived from counts."

### Pattern 2: Retry only the pre-first-token upstream call, never the stream body

**What:** `AsyncRetrying`, constructed per-call, invoked directly on the coroutine that performs the network handshake — not a decorator on the async generator method.
**When to use:** `OpenAICompatibleProvider.chat_stream()`, wrapping `client.chat.completions.create(**kwargs)`.

Verified empirically by reading the installed SDK source this session, not assumed: `AsyncOpenAI.chat.completions.create(stream=True, ...)` internally calls `await self._send_request(...)` (an `httpx` request with `stream=True` for the response **body**, but the request is still fully sent and the response **status line + headers** are received before `create()` returns) then `response.raise_for_status()` — a 4xx/5xx here raises the mapped exception (`RateLimitError`/`AuthenticationError`/`PermissionDeniedError`/`InternalServerError`/generic `APIStatusError`) **before** `create()` returns anything to the caller [VERIFIED: `.venv/lib/python3.14/site-packages/openai/_base_client.py:1584-1700`, `.venv/lib/python3.14/site-packages/openai/_client.py:485-516,913-944`]. Only after a 2xx status is `create()`'s return value (the `AsyncStream` wrapper) handed back, and the `async for chunk in stream:` loop begins consuming server-sent chunks. A failure once that loop has started (dropped connection mid-stream, after some tokens have already been forwarded to the client via SSE) surfaces as an exception raised from inside the `async for`, not from `create()` — retrying at that point would require re-sending the whole prompt and would duplicate already-delivered tokens on the client's SSE stream, which nothing in this design does. **Only the pre-first-token failure path is safely retriable**; this matches the "verify empirically" instruction in scope and is the reason the retry wrapper must sit around `create()` alone.

```python
# providers/openai_compatible_base.py — modified
import logging
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, InternalServerError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from providers.base import LLMProvider, StreamChunk, UsageData

logger = logging.getLogger(__name__)

# Allow-list, not a deny-list: only affirmatively-transient exception types are
# retried. z.ai quota (429 -> RateLimitError) and auth (401/403 ->
# AuthenticationError/PermissionDeniedError) are excluded BY OMISSION, which
# also safely excludes the z.ai "1113" balance-exhaustion error even though it
# can arrive under a non-429 status code (existing test fixtures model it as
# status_code=402) -- an allow-list can't accidentally retry an exception type
# it was never told to retry, whereas a deny-list keyed on RateLimitError/
# AuthenticationError specifically would miss that case.
_RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError)


class OpenAICompatibleProvider(LLMProvider):
    base_url: str = ""
    default_model: str = ""

    def __init__(self, api_key: str, model: str | None = None):
        # max_retries=0: openai's own client retries 429/5xx internally by
        # default (up to DEFAULT_MAX_RETRIES=2) BEFORE raising -- left at its
        # default, z.ai quota-exhaustion (429) would be silently retried by
        # the SDK layer before this provider's tenacity policy (or ZAI-3's
        # never-retry-quota rule) ever sees the exception. Disabling it here
        # makes tenacity, below, the single source of retry truth.
        self.client = AsyncOpenAI(api_key=api_key, base_url=self.base_url, max_retries=0)
        self.model = model or self.default_model

    async def chat_stream(
        self, messages: list[dict], system_prompt: str, params=None
    ) -> AsyncGenerator[StreamChunk, None]:
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        kwargs = {"model": self.model, "messages": all_messages, "stream": True,
                  "stream_options": {"include_usage": True}}
        if params:
            for k in ("temperature", "max_tokens", "top_p"):
                if k in params:
                    kwargs[k] = params[k]

        retryer = AsyncRetrying(
            stop=stop_after_attempt(3),  # locked "max 2 retries" == 3 total attempts
            wait=wait_exponential_jitter(initial=0.5, max=8.0),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,  # exhausted retries re-raise the ORIGINAL exception,
                           # so routes/chat.py's existing getattr(e, "status_code")
                           # error-mapping code keeps working unmodified
        )
        stream = await retryer(self.client.chat.completions.create, **kwargs)

        async for chunk in stream:   # NOT retried past this point
            if chunk.usage:
                usage = UsageData(prompt_tokens=chunk.usage.prompt_tokens,
                                   completion_tokens=chunk.usage.completion_tokens,
                                   total_tokens=chunk.usage.total_tokens)
                details = getattr(chunk.usage, "prompt_tokens_details", None)
                cached = getattr(details, "cached_tokens", None)
                if cached:
                    usage["cached_tokens"] = cached
                yield ("", usage)
            elif chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield (delta, None)
```

`AsyncRetrying.__call__` is `async def __call__(self, fn, *args, **kwargs)` and awaits `fn(*args, **kwargs)` directly, retrying on failure per the `retry=`/`stop=`/`wait=` predicates [VERIFIED: `.venv/lib/python3.14/site-packages/tenacity/asyncio/__init__.py:104-127`]. This is the documented, supported call form for wrapping a single coroutine invocation without decorating a whole function — no generator-decoration workaround needed.

`reraise=True` matters: without it, tenacity wraps the final failure in its own `RetryError`, losing the original exception's `.status_code` attribute that `routes/chat.py`'s existing error-mapping code (`getattr(e, "status_code", None)`) depends on — `reraise=True` re-raises the original exception on exhaustion, preserving that contract unmodified.

**Deterministic testing:** follow the repo's existing "ctor-injectable, never `time.sleep`" convention (used for `AnalyticsWriter`'s `purge_interval_s`, per STATE.md). Either make the `wait=` strategy overridable by test fixtures (e.g. a module-level default the tests can monkeypatch), or simply `unittest.mock.patch("tenacity.asyncio.asyncio.sleep")`/patch `wait_exponential_jitter` to a near-zero wait in tests — tenacity's own sleep is `asyncio.sleep` imported lazily inside `_portable_async_sleep` (`tenacity/asyncio/__init__.py:62-64`), so `patch("asyncio.sleep", ...)` scoped to the test function works without any product-code changes.

### Pattern 3: Stacked slowapi decorators, per-decorator `key_func`

**What:** Two `@limiter.limit(...)` decorators on the same route, each with its own `key_func`.
**When to use:** `routes/chat.py`'s `chat` route — existing per-IP limit stays, new per-key limit stacks alongside it.

Verified by reading the installed `slowapi==0.1.9` source this session, not assumed: `Limiter.limit(limit_value, key_func=None, ...)` accepts a per-call `key_func` override (`extension.py:783-821`, defaulting to `self._key_func` — the `Limiter`'s constructor-level `key_func` — when omitted). At decoration time, each `@limiter.limit()` application registers its `Limit` object into `self._route_limits[name]` where `name = f"{func.__module__}.{func.__name__}"` — and because `functools.wraps` propagates `__name__`/`__module__` through every layer of stacked decorators, **all** `@limiter.limit()` applications on the same original function accumulate into the **same** list under the same key, regardless of stacking order [VERIFIED: `.venv/lib/python3.14/site-packages/slowapi/extension.py:662-704`]. At request time, `_check_request_limit()` is guarded by a `request.state._rate_limiting_complete` flag (`extension.py:729-733`) so only the **first**-executing wrapper's check actually runs `__evaluate_limits()` — but that one call evaluates the **entire accumulated list** of limits together (`extension.py:482-528`), calling `self.limiter.hit(lim.limit, *args)` once per limit with **each limit's own `key_func`-derived key** and breaking with a 429 on the first one that's exceeded. Net effect: stacking is exactly the "both apply" mechanism CONTEXT.md calls for, with zero extra `Limiter` instances, zero extra storage backends, and the check happening — as it always did — before the route body (and therefore any provider call) executes.

```python
# rate_limiter.py — modified
"""Rate limiter instance — shared across modules to avoid circular imports."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


def extract_bearer_key(request: Request) -> str:
    """Per-key rate-limit identity: the Bearer token itself, falling back to
    remote IP when missing/malformed (locked decision — same removeprefix
    pattern as routes/chat.py's verify_auth, reused deliberately)."""
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").removeprefix("bearer ")
    return token or get_remote_address(request)
```

```python
# routes/chat.py — modified decorator stack
from rate_limiter import extract_bearer_key, limiter

@router.post("/v1/chat/completions")
@limiter.limit(settings.rate_limit)                                    # existing, per-IP
@limiter.limit(settings.rate_limit_per_key, key_func=extract_bearer_key)  # NEW, per-key
async def chat(request: Request, body: ChatRequest, _auth=Depends(verify_auth)):
    ...
```

### Pattern 4: Liveness vs. readiness

**What:** `/health/live` never touches application state; `/health/ready` reads the lifespan-owned `app.state` attributes that only exist after a successful startup.
**When to use:** Replaces the current single `/health` (breaking rename — locked, no back-compat alias requested by CONTEXT.md or the phase description).

`main.py`'s `lifespan()` only assigns `app.state.analytics_db = db` and `app.state.analytics_writer = writer` **after** `db.initialize()` and the mandatory `db.write_probe()` both succeed and `writer.start()` has been called [VERIFIED: `main.py:49-65` — read this session]. This means the mere **presence** of both attributes on `app.state` is itself sufficient proof of "DB initialized + writer running" — no need to reach into `AnalyticsDB._db`/`AnalyticsWriter._task` private state:

```python
# main.py additions (replaces the existing @app.get("/health"))
@app.get("/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(request: Request):
    db = getattr(request.app.state, "analytics_db", None)
    writer = getattr(request.app.state, "analytics_writer", None)
    if db is None or writer is None:
        return Response(status_code=503, content='{"status":"not_ready"}',
                         media_type="application/json")
    return {"status": "ready"}
```

This is test-fixture-compatible: the existing `client` fixture (`tests/conftest.py`) injects `app.state.analytics_db`/`app.state.analytics_writer` directly (since `ASGITransport` never runs the real `lifespan`), so `/health/ready` reads `200` under the same fixture that already exists — no fixture changes needed.

### Anti-Patterns to Avoid

- **Decorating `chat_stream` itself with `@retry`:** silently retries nothing (see Pitfall 1) — always retry the specific coroutine, not the generator function.
- **Leaving `AsyncOpenAI(max_retries=DEFAULT_MAX_RETRIES)` (the default) while adding tenacity on top:** produces up to `2 (SDK) × 3 (tenacity attempts) = 6` total upstream calls per logical request, AND silently retries z.ai 429/quota errors at the SDK layer before tenacity's (or ZAI-3's) exclusion logic ever runs. Always pair the tenacity addition with `max_retries=0`.
- **A rate-limit deny-list of the openai SDK's mapped exception classes as the retry predicate:** an allow-list of transient types is strictly safer here, because the z.ai "1113" balance error is detected by substring match in the message at an **arbitrary** status code, not guaranteed to be `429`.
- **Two separate `Limiter` instances for per-IP vs. per-key:** unnecessary — one `Limiter`, two stacked `@limiter.limit()` calls with different `key_func` is the supported, simpler mechanism.
- **Using `prometheus_client`'s multiprocess mode guidance as a design constraint:** irrelevant here — this app is single-process (`uvicorn main:app`, no `--workers`), so plain in-memory dict counters need no cross-process aggregation, no `PROMETHEUS_MULTIPROC_DIR`, and no locks (single event loop, no preemptive interleaving between an increment and a read).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Retry backoff scheduling/jitter math | A custom `asyncio.sleep`-based retry loop | `tenacity.wait_exponential_jitter` | Locked user decision; correct jitter/backoff math is easy to get subtly wrong (unbounded growth, thundering herd) and tenacity already ships it |
| Per-route multi-key rate limiting | A second `Limiter`/custom ASGI middleware | Stacked `@limiter.limit(..., key_func=...)` decorators on one `Limiter` | slowapi already supports this natively (see Pattern 3) — building a second layer duplicates the storage/backends slowapi already manages |
| Prometheus histogram bucket math / `+Inf` bucket bookkeeping | Ad hoc bucket accumulation | The exact convention in Pattern 1 (`x_bucket{le=...}` cumulative counts, final `+Inf` bucket equal to `x_count`, separate `x_sum`/`x_count`) | The exposition format has a **mandatory**, easy-to-get-wrong shape for histograms; deviating breaks Prometheus's parser, not just cosmetics |

**Key insight:** every "don't hand-roll" item above already has first-class support in a library already in `requirements.txt` (`slowapi`, `tenacity` once added) or is dictated by an external, fixed wire format (Prometheus text exposition) — none of it is genuinely novel enough to justify inventing new abstractions.

## Common Pitfalls

### Pitfall 1: Decorating `chat_stream` (an async generator) with tenacity's `@retry`

**What goes wrong:** `@retry` (or `@retryer.wraps(...)`) applied to an `async def ...() -> AsyncGenerator[...]` function does not retry the generator's body — calling the decorated function just returns an async-generator object immediately (nothing has been awaited yet), so tenacity's retry loop sees a successful "call" on the first attempt regardless of what happens once the generator is actually iterated.
**Why it happens:** tenacity's retry mechanics are built around awaiting a coroutine's *result*, not around iterating an async generator's yields; an async generator function's "call" and its "execution" are decoupled in a way a coroutine's are not.
**How to avoid:** construct an `AsyncRetrying` instance and call it directly on the specific coroutine to retry (`await retryer(self.client.chat.completions.create, **kwargs)`), inside the generator method, wrapping only the pre-iteration call — never the `async for` loop or the method itself.
**Warning signs:** retry-count metrics/logs never increment even when the mocked upstream is made to fail; a test that asserts "returns success on the 2nd attempt" using a decorated-generator design passes only because the mock's `side_effect` list is never actually consumed past the first call.

### Pitfall 2: The openai SDK's own retry silently doubling up with tenacity's

**What goes wrong:** `AsyncOpenAI(api_key=..., base_url=...)` defaults to `max_retries=2` (`DEFAULT_MAX_RETRIES`), retrying HTTP 408/409/429/5xx **internally**, inside `create()`, before any exception is raised to caller code. Left at this default while adding tenacity retry around `create()` produces compounded retries (up to 6 total upstream calls for one logical failure) and — critically — retries z.ai's 429 quota-exhaustion response at the SDK layer, which is a direct, if previously-unnoticed, breach of the spirit of locked decision ZAI-3 ("never retry quota").
**Why it happens:** the openai Python SDK's retry-on-429-by-default behavior is a reasonable default for typical API consumers, but is wrong for a gateway that has an explicit business rule against retrying one specific provider's 429s.
**How to avoid:** pass `max_retries=0` to the `AsyncOpenAI(...)` constructor in `OpenAICompatibleProvider.__init__`, making tenacity (with its allow-list predicate) the sole retry authority for both providers.
**Warning signs:** retry-count logs/metrics show fewer or more attempts than the configured tenacity `stop_after_attempt` value; z.ai quota errors take noticeably longer than one request-response round trip to surface to the client even though ZAI-3 says they should hard-fail immediately.

### Pitfall 3: A retry-exception deny-list missing the z.ai "1113" balance code

**What goes wrong:** the existing z.ai error-mapping code in `routes/chat.py` detects quota exhaustion by `status == 429 or "1113" in error_msg` — the "1113" check is a **substring match on the exception message**, independent of `status_code`. A retry predicate built as `retry_if_exception_type` excluding only `RateLimitError`/`AuthenticationError`/`PermissionDeniedError` by class would still retry an exception object that carries "1113" in its message under some other status/exception class (existing test fixtures model exactly this with a custom `status_code = 402` exception).
**Why it happens:** deny-lists only exclude what they explicitly name; z.ai's balance-exhaustion signal is not confined to one exception type or status code in this codebase's own test suite.
**How to avoid:** use an allow-list (`retry_if_exception_type((APIConnectionError, APITimeoutError, InternalServerError))`) so only affirmatively-transient types are ever retried, and everything else — including any shape the 1113 error takes — is excluded by omission.
**Warning signs:** a test that raises a 402-status "balance exhausted, code 1113" exception observes more than one upstream call attempt.

### Pitfall 4: Header/Content-Type omission on `/metrics` breaking Prometheus 3.x scraping

**What goes wrong:** Prometheus 3.0+ scrape targets **must** return a parseable `Content-Type` header or the entire scrape fails (not just falls back to a default parse) [CITED: prometheus.io/docs/instrumenting/exposition_formats/, "HTTP Content-Type requirements"].
**Why it happens:** easy to return a bare string via `PlainTextResponse` or a raw dict without setting `media_type` explicitly, relying on FastAPI's default `application/json`.
**How to avoid:** always construct the `/metrics` response with `media_type="text/plain; version=0.0.4"` explicitly (Starlette appends `; charset=utf-8` automatically — verified this session, no manual header string needed).
**Warning signs:** `curl -sI http://localhost:8000/metrics` shows `content-type: application/json` instead of `text/plain`.

## Code Examples

Full code for Patterns 1–4 above is verified against the installed dependency source in this repo's `.venv` (not training-data recollection) and is directly usable as a starting point — see each pattern's code block.

### Existing test-mocking convention for provider-level tests (reuse, don't invent a new one)

```python
# Source: tests/test_openai_compatible_base.py:22-27 (existing, read this session)
def _provider_with_chunks(chunks):
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=_aiter(chunks))))
    )
    return provider
```
For retry tests, set `create=AsyncMock(side_effect=[exc1, exc2, _aiter(chunks)])` (fails twice, succeeds third) or `side_effect=exc` (always fails, exhausts retries) — `AsyncMock` satisfies `tenacity`'s `is_coroutine_callable(fn)` check the same way the real bound method does.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| Single `/health` endpoint | Split `/health/live` + `/health/ready` | This phase | Docker/Compose orchestration convention for distinguishing "process up" from "ready to serve" — the Dockerfile `HEALTHCHECK` and (per CONTEXT.md) the Compose target repoint to `/health/ready` |
| `AsyncOpenAI` default retry (`max_retries=2`, internal) | `max_retries=0` + explicit tenacity policy | This phase | Makes retry behavior auditable and ZAI-3-compliant; previously-silent SDK retries become explicit, logged, and correctly excluded for quota/auth |

**Deprecated/outdated:** none — `openai==2.32.0`, `slowapi==0.1.9`, `tenacity==9.1.4` are all current, actively maintained releases (verified installed versions, not assumed).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | Histogram bucket boundaries `(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)` are a reasonable default for this gateway's request latencies | Pattern 1 | Wrong bucket granularity makes `histogram_quantile()` queries imprecise; not a functional break, purely an observability-quality tradeoff, and is a code-owned constant trivially adjustable later |
| A2 | `RATE_LIMIT_PER_KEY` should default to the same value as `RATE_LIMIT` (`"60/minute"`) absent a locked number in CONTEXT.md | Pattern 3 / Open Questions | If the user actually wants a stricter or looser per-key default, this is a one-line `.env.example` change, not a design change |
| A3 | Bearer-token-as-rate-limit-key is acceptable even though every client in this single-user gateway currently shares one `APP_API_KEY` (per-key limiting is effectively global until/unless multiple keys exist) | Pattern 3 | None functionally — CONTEXT.md explicitly locked this mechanism; noted only so the planner doesn't mistake "per key" for "per distinct user" in a single-key deployment |

**If empty:** not applicable — three assumptions logged above; none touch the ZAI-3 no-fallback/no-retry-on-quota constraint, which is fully `[VERIFIED]` via source-reading rather than assumed.

## Open Questions (RESOLVED)

1. **Should `Makefile`'s `make health` target repoint to `/health/ready` or `/health/live`?**
   - What we know: the Dockerfile's `HEALTHCHECK` and (per CONTEXT.md) the Compose healthcheck must repoint to `/health/ready` (readiness gates container health).
   - What's unclear: `make health` is a developer convenience command (`make start` calls it right after backgrounding the server) — `/health/ready` is arguably more useful there too (confirms the DB is actually usable, not just that the process bound the port), but CONTEXT.md doesn't explicitly mention the Makefile.
   - Recommendation: repoint `make health` to `/health/ready` for consistency; trivial one-line change, low risk either way.
   - — RESOLVED: 04-01-PLAN.md Task 1 repoints `make health` to `/health/ready`.

2. **Exact `RATE_LIMIT_PER_KEY` default value.**
   - What we know: CONTEXT.md locks the mechanism (Bearer-token key_func, new env var, both limits apply) but not a specific default number; the phase's "Claude's Discretion: None — all areas resolved" line refers to *design* areas, not this specific numeric default.
   - What's unclear: whether the per-key limit should default equal to, stricter than, or looser than the existing per-IP `RATE_LIMIT` default.
   - Recommendation: default `RATE_LIMIT_PER_KEY=60/minute` (matches existing `RATE_LIMIT` default) for a single-user gateway where the only real client population is "this one API key" — trivially overridable via `.env` per the requirement.
   - — RESOLVED: 04-03-PLAN.md Task 1 sets `RATE_LIMIT_PER_KEY` default to `60/minute`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| `tenacity` (Python package) | OBSV-03 retry | ✓ (already in `.venv`, not yet in `requirements.txt`) | 9.1.4 | — |
| `slowapi`/`limits` (Python packages) | OBSV-02 per-key limiting | ✓ | 0.1.9 / 5.8.0 | — |
| `openai` (Python package) | OBSV-03 retry (exception types, `max_retries` kwarg) | ✓ | 2.32.0 | — |
| Docker daemon | Compose Prometheus profile testing | ✓ (Rancher Desktop context) | 29.5.3-rd (client) | — |
| `prom/prometheus` Docker image | Optional Compose profile | ✓ (public, active, 2B+ pulls — verified via Docker Hub API this session) | latest (unpinned in the example above; recommend pinning a specific tag, e.g. `v3.x`, per the repo's general preference for reproducibility) | Operators without Docker/Compose can still scrape `/metrics` with any external Prometheus instance — the profile is a convenience, not a requirement |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none blocking — `tenacity` needs only a `requirements.txt` entry (already installed in the dev venv).

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest `>=8.0.0` + `pytest-asyncio>=0.24.0` (`asyncio_mode = auto`) |
| Config file | `pytest.ini` (contents: `[pytest]\nasyncio_mode = auto`) |
| Quick run command | `.venv/bin/python -m pytest tests/test_openai_compatible_base.py tests/test_config.py tests/test_startup_validation.py -v` (scoped to touched modules) |
| Full suite command | `.venv/bin/python -m pytest tests/ -v` (repo convention: always `python -m pytest`, never bare `pytest` — bare form drops repo root from `sys.path`, per `AGENTS.md`/CI notes) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| OBSV-01 | `/metrics` returns valid Prometheus text exposition (HELP/TYPE lines, counter + histogram with `+Inf` bucket, correct `Content-Type`) reflecting at least one prior request | integration (httpx client) | `pytest tests/test_metrics.py -v` | ❌ Wave 0 — new file |
| OBSV-01 | Error rate is derivable from `gateway_requests_total` label combinations (status="error" present alongside status="success") | integration | same file as above | ❌ Wave 0 |
| OBSV-02 | Request exceeding `RATE_LIMIT_PER_KEY` (same Bearer token, distinct IPs or same IP) gets 429 before any provider call; request within per-key but exceeding per-IP still gets 429 | integration (httpx client, `create_provider` mocked and asserted **not called** on the 429 path) | `pytest tests/test_chat_endpoint.py -v -k rate_limit` (extend existing file — `verify_auth`/rate-limit tests already live there) | ❌ Wave 0 — new test functions in existing file |
| OBSV-03 | Transient exception (`APIConnectionError`/`APITimeoutError`/`InternalServerError`) retried up to 2 times then succeeds; retries logged | unit (provider-level, `AsyncMock(side_effect=[...])` per existing `_provider_with_chunks` convention) | `pytest tests/test_openai_compatible_base.py -v -k retry` | ❌ Wave 0 — new test functions in existing file |
| OBSV-03 | z.ai quota (429 / message-embedded "1113") and auth (401/403) exceptions are **never** retried — exactly one upstream call attempt, original exception re-raised with `.status_code` intact | unit (same file) | same command | ❌ Wave 0 |
| OBSV-03 | After retry exhaustion (all attempts transient-failed), client sees the existing provider-distinct SSE error frame (mapped by `routes/chat.py`'s unchanged `getattr(e, "status_code")` logic) | integration | extend `tests/test_chat_endpoint.py` | ❌ Wave 0 |
| Health split (feeds Phase 3 healthcheck) | `/health/live` always 200 with no `app.state` dependency; `/health/ready` 200 when `analytics_db`/`analytics_writer` are set (existing `client` fixture), else 503 | integration | extend `tests/test_chat_endpoint.py`'s existing `test_health_endpoint` (rename/split) or new `tests/test_health.py` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** the scoped quick-run command for the file(s) touched by that task.
- **Per wave merge:** `.venv/bin/python -m pytest tests/ -v` (full suite).
- **Phase gate:** full suite green before `/gsd:verify-work`.

### Wave 0 Gaps

- [ ] `tests/test_metrics.py` — new file, covers OBSV-01
- [ ] New test functions in `tests/test_openai_compatible_base.py` — covers OBSV-03 (both retry-succeeds and never-retries-quota/auth cases); reuses the existing `_provider_with_chunks`/`AsyncMock` convention, no new fixtures needed
- [ ] New test functions in `tests/test_chat_endpoint.py` — covers OBSV-02 (per-key 429) and the health-split rename; reuses the existing `client`/`analytics_writer`/`analytics_db` fixtures, no new fixtures needed
- [ ] No new test framework/config needed — pytest + `pytest-asyncio` + `httpx.AsyncClient`/`ASGITransport` already cover every scenario above

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no change | `/metrics`, `/health/live`, `/health/ready` are intentionally unauthenticated (standard Prometheus/orchestrator scrape convention, matches existing `/health`'s exemption) — no new auth surface introduced |
| V4 Access Control | yes (rate limiting) | slowapi per-key + per-IP limiting (already-standard library, not hand-rolled) enforced **before** the route body runs, so no provider-cost/quota consumption on a rejected request |
| V5 Input Validation | yes | `RATE_LIMIT_PER_KEY` validated at Settings-construction time via `limits.parse_many` (same validator pattern as existing `RATE_LIMIT`), failing fast before any request is served — never deferred to request time |
| V7 Error Handling / Logging | yes (retry logging) | Retry attempts logged via tenacity's `before_sleep` hook at `logger.warning` — never logs the request body/messages, only provider name + attempt number + exception class, consistent with the existing "never leak internal exception text to the client" rule (client-facing behavior is unchanged; only server-side logs gain retry visibility) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| Unauthenticated `/metrics` leaking sensitive data | Information Disclosure | Metrics carry only `provider`/`model`/`status` labels and counts/latencies — no prompt content, no API keys, no user identifiers; this is the standard Prometheus scrape-endpoint threat model and is inherently low-risk here since the labels are already non-sensitive route/model names that appear in the existing (auth-required) analytics endpoints anyway |
| Rate-limit bypass via key omission | Elevation of Privilege / DoS | `extract_bearer_key`'s IP fallback (locked decision: "falls back to remote IP if missing/malformed") ensures a request with no/garbage Bearer token still gets *a* per-key-scoped limit (scoped to its IP) rather than being exempt from per-key limiting entirely |
| Retry amplification against z.ai / Manifest (accidental DoS on upstream, or accidental quota burn) | Denial of Service (self-inflicted) | Bounded `stop_after_attempt(3)` + exponential backoff with jitter, and critically `max_retries=0` on the SDK client to prevent the compounding described in Pitfall 2 — without this, a transient 5xx burst could multiply into 6x upstream load 
| ZAI-3 violation via retry (never reroute z.ai errors to Manifest; never retry quota/auth) | Tampering with a locked business rule | Retry lives entirely inside `OpenAICompatibleProvider.chat_stream()` — same class, same `self.client`, same `base_url` for every retry attempt; there is no code path by which a retry could route through a different provider. Allow-list predicate (Pitfall 3) ensures quota/auth are structurally excluded, not just excluded by naming the classes seen in today's test fixtures |

## Sources

### Primary (HIGH confidence — verified by reading installed source/official spec this session)
- `.venv/lib/python3.14/site-packages/openai/_base_client.py` — request/retry/status-error mapping mechanics
- `.venv/lib/python3.14/site-packages/openai/_client.py` — concrete `_make_status_error` status→exception-class mapping
- `.venv/lib/python3.14/site-packages/openai/_exceptions.py` — exception class hierarchy and fixed `status_code` values
- `.venv/lib/python3.14/site-packages/openai/_constants.py` — `DEFAULT_MAX_RETRIES = 2`
- `.venv/lib/python3.14/site-packages/tenacity/asyncio/__init__.py` — `AsyncRetrying.__call__` semantics
- `.venv/lib/python3.14/site-packages/tenacity/{retry,wait,stop}.py` — predicate/backoff constructor signatures
- `.venv/lib/python3.14/site-packages/slowapi/extension.py` — `Limiter.limit()`, decorator stacking/accumulation, `__evaluate_limits`
- `.venv/lib/python3.14/site-packages/slowapi/errors.py` — `RateLimitExceeded`/default 429 handler body
- `.venv/lib/python3.14/site-packages/starlette/responses.py` — `Content-Type`/charset auto-append behavior
- `pypi.org/pypi/tenacity/json` — package metadata, age, `requires_python`, current version
- `hub.docker.com/v2/repositories/prom/prometheus/` — official image confirmation
- `prometheus.io/docs/instrumenting/exposition_formats/` — canonical text-exposition format spec
- Every project file read this session: `04-CONTEXT.md`, `REQUIREMENTS.md`, `PROJECT.md`, `STATE.md`, `/tmp/gsd-phase4-desc.md`, `AGENTS.md`, `rate_limiter.py`, `routes/chat.py`, `providers/openai_compatible_base.py`, `providers/zai_coding.py`, `providers/base.py`, `main.py`, `config.py`, `docker-compose.yml`, `requirements.txt`, `Dockerfile`, `Makefile`, `.env.example`, `analytics/writer.py`, `analytics/db.py`, `.github/workflows/ci.yml`, `tests/test_chat_endpoint.py`, `tests/test_openai_compatible_base.py`, `tests/test_config.py`, `tests/test_startup_validation.py`

### Secondary (MEDIUM confidence)
- None beyond the above — every claim in this document that could be verified against installed source or an official spec was.

### Tertiary (LOW confidence)
- Histogram bucket boundary choice (Assumption A1) — a design recommendation, not a verified requirement.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — `tenacity`/`slowapi`/`openai` versions and behavior all confirmed by reading installed source this session, not recalled from training data.
- Architecture: HIGH — every integration point (decorator stacking, retry boundary, health-state reads) traced through actual library source and existing codebase files, not inferred.
- Pitfalls: HIGH — Pitfalls 1–3 were discovered, not assumed, by reading the openai SDK's own default-retry logic and tenacity's async-generator limitations; this materially changes the phase's scope (the `max_retries=0` requirement is not mentioned anywhere in CONTEXT.md and must be added by the planner).

**Research date:** 2026-09-08
**Valid until:** 30 days (stable, slow-moving dependencies — `openai`/`tenacity`/`slowapi` release cadence is not fast enough to invalidate this sooner, but re-verify `openai` SDK retry defaults if the pinned version changes materially)

## RESEARCH COMPLETE

**Phase:** 4 - Observability & Resilience
**Confidence:** HIGH

### Key Findings
- The installed `openai==2.32.0` SDK retries HTTP 429/5xx **internally** by default (`max_retries=2`) before raising — left unaddressed, this silently retries z.ai quota-exhaustion errors in violation of ZAI-3's spirit and compounds with any tenacity retry added on top. The plan **must** set `max_retries=0` on `AsyncOpenAI(...)` construction.
- `chat_stream` is an async generator; tenacity's `@retry` decorator cannot correctly wrap it. The verified, correct pattern is `stream = await AsyncRetrying(...)(self.client.chat.completions.create, **kwargs)`, retrying only the pre-first-token call — never the token-streaming loop, since a mid-stream failure cannot be retried without duplicating already-delivered tokens to the client.
- The retry predicate must be an **allow-list** of transient exception types (`APIConnectionError`, `APITimeoutError`, `openai.InternalServerError`), not a deny-list of quota/auth types — because the existing z.ai "1113" balance-error detection matches on message substring at an arbitrary status code (test fixtures model it as `status_code=402`), which a deny-list keyed on `RateLimitError`/`AuthenticationError` could miss.
- slowapi's `Limiter.limit(..., key_func=...)` supports a per-decorator key function; stacking two `@limiter.limit()` decorators (existing per-IP + new per-key) on the same route is the correct, already-supported "both apply" mechanism — no second `Limiter` instance needed.
- `/health/ready` can read pure presence of `app.state.analytics_db`/`app.state.analytics_writer` (both only ever set after a successful lifespan startup) — no need to reach into private writer/DB internals, and the existing test `client` fixture already sets both, so no fixture changes are needed for readiness tests.
- Prometheus 3.0+ scrape targets must return a parseable `Content-Type` header or the scrape fails outright; `media_type="text/plain; version=0.0.4"` on a Starlette `Response` gets `; charset=utf-8` auto-appended, matching `prometheus_client`'s own convention with no manual header string needed.

### File Created
`.planning/phases/04-observability-resilience/04-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|---|---|---|
| Standard Stack | HIGH | Versions and API surfaces confirmed by reading installed `.venv` source, not recalled |
| Architecture | HIGH | Every integration point traced through real library source + existing repo files |
| Pitfalls | HIGH | Discovered via source-reading (openai default retry, tenacity generator limitation), not assumed — materially changes required scope beyond CONTEXT.md's own inventory |

### Open Questions
1. Whether `make health` should repoint to `/health/ready` (recommended) or stay/split — low-stakes, planner's call.
2. Exact `RATE_LIMIT_PER_KEY` default value (recommend matching `RATE_LIMIT`'s `60/minute`) — not locked in CONTEXT.md, planner should confirm or let the user pick.

### Ready for Planning
Research complete. Planner can now create PLAN.md files — in particular, the planner must add a task step disabling the openai SDK's built-in retry (`max_retries=0`) alongside adding the tenacity wrapper, since this was not called out in CONTEXT.md but is required for ZAI-3 compliance and for the "max 2 retries" policy to hold as a hard ceiling rather than a compounding one.
