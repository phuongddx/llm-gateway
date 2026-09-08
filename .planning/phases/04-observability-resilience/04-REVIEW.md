---
phase: 04-observability-resilience
reviewed: 2026-09-08T00:00:00Z
depth: deep
files_reviewed: 16
files_reviewed_list:
  - .env.example
  - Dockerfile
  - Makefile
  - README.md
  - config.py
  - docker-compose.yml
  - main.py
  - metrics.py
  - prometheus/prometheus.yml
  - providers/openai_compatible_base.py
  - rate_limiter.py
  - requirements.txt
  - routes/chat.py
  - tests/test_chat_endpoint.py
  - tests/test_metrics.py
  - tests/test_openai_compatible_base.py
  - tests/test_rate_limiting.py
  - tests/test_startup_validation.py
findings:
  critical: 1
  warning: 2
  info: 2
  total: 5
status: fixed
fixed: [CR-01, WR-01, WR-02]
---

# Phase 04: Code Review Report

**Reviewed:** 2026-09-08T00:00:00Z
**Depth:** deep
**Files Reviewed:** 16
**Status:** fixed

## Summary

Phase 04 implements Prometheus-style `/metrics`, split `/health/live` + `/health/ready`, per-key rate limiting (OBSV-02), and tenacity-driven same-provider retry with `max_retries=0` (OBSV-03). Unit-level correctness is high: 54/54 tests pass, and the ZAI-3 lock is genuinely sound at the exception-type level (verified below). However, the change introduces one container-breaking packaging bug (Dockerfile never copies the new `metrics.py` module into the runtime image), which is invisible to the pytest suite because tests run against the full repo checkout, not the built image.

**ZAI-3 verdict: PASS.** The retry allow-list in `providers/openai_compatible_base.py` is a true positive allow-list of exception *types* — `(APIConnectionError, APITimeoutError, InternalServerError)` — verified against the real `openai` SDK's exception hierarchy (see CR-01 investigation notes below). `RateLimitError` (429), `AuthenticationError` (401), and `PermissionDeniedError` (403) are siblings of `APIStatusError`, not subclasses of any allow-listed type, so no z.ai quota/auth exception can ever match `retry_if_exception_type(_RETRYABLE)` — not by status code, not by message substring, not by accident. `AsyncOpenAI(..., max_retries=0)` correctly disables the SDK's own internal 429/5xx retry layer, making tenacity the single source of retry truth. No cross-provider fallback exists anywhere in the retry or error-handling path; `routes/chat.py`'s `status == 429 or "1113" in error_msg` branch only rewrites the *client-facing error message* after the exception has already propagated past the (correctly non-matching) retry policy — it does not re-route or retry.

## Critical Issues

### CR-01: `metrics.py` is never copied into the Docker image — container crashes on startup

**File:** `Dockerfile:20`
**Issue:** `main.py` (line 13) unconditionally does `import metrics as gateway_metrics` at module load time, and `routes/chat.py` (line 13) does `import metrics`. `metrics.py` is a new top-level module introduced in this phase (commit `f0eeb79`), but the Dockerfile's runtime-stage `COPY` list was never updated to include it:

```dockerfile
COPY main.py config.py rate_limiter.py ./
COPY analytics ./analytics
COPY routes ./routes
COPY providers ./providers
COPY static ./static
```

Reproduced directly: copying exactly this file set into a clean directory with the project's dependencies installed and running `import main` raises:
```
ModuleNotFoundError: No module named 'metrics'
```
This is a full production regression — the built image (`docker compose up`, `make docker-build`) will fail to start at all, not just the `/metrics` endpoint. It is invisible to `pytest` because tests import from the repo root where `metrics.py` is present; only the Docker build path is affected.

**Fix:**
```dockerfile
COPY main.py config.py rate_limiter.py metrics.py ./
```

## Warnings

### WR-01: ZAI-3 retry-exclusion tests use fake exception classes, not the real SDK types

**File:** `tests/test_openai_compatible_base.py:122-145`
**Issue:** `test_quota_1113_shaped_exception_is_never_retried` and `test_auth_failure_shaped_exception_is_never_retried` construct bespoke `class BalanceError(Exception): status_code = 402` / `class AuthError(Exception): status_code = 401` stand-ins rather than the real `openai.RateLimitError` / `openai.AuthenticationError` / `openai.PermissionDeniedError`. Since `retry_if_exception_type` is a pure `isinstance` check, these fakes exercise the *shape* of the bug class (arbitrary `Exception` subclass with a `status_code` attribute) but not the actual production exception hierarchy. If a future `openai` SDK upgrade ever changed `RateLimitError` to subclass `InternalServerError` (unlikely, but the test as written would not catch it), this suite would keep passing green while ZAI-3 silently broke.
**Fix:** Add at least one test per excluded class using the real SDK exceptions, e.g.:
```python
from openai import RateLimitError, AuthenticationError, PermissionDeniedError

def _rate_limit_error():
    req = httpx.Request("POST", "https://api.z.ai/v4/chat/completions")
    resp = httpx.Response(429, request=req)
    return RateLimitError("quota exceeded", response=resp, body=None)

@pytest.mark.asyncio
async def test_real_ratelimiterror_is_never_retried():
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    create_mock = AsyncMock(side_effect=_rate_limit_error())
    with patch.object(provider.client.chat.completions, "create", create_mock), \
         pytest.raises(RateLimitError):
        async for _ in provider.chat_stream([{"role": "user", "content": "hi"}], ""):
            pass
    assert create_mock.await_count == 1
```

### WR-02: `/health/ready` never verifies the analytics DB connection is actually alive

**File:** `main.py:99-107`
**Issue:** `health_ready` only checks `getattr(request.app.state, "analytics_db", None)` and `analytics_writer` for presence (set once at startup and never cleared), not whether the underlying SQLite connection is still usable. If the DB file becomes unwritable/corrupted after startup (disk full, permissions changed, volume unmounted), `analytics_db`/`analytics_writer` remain non-`None` and `/health/ready` keeps reporting `200 {"status": "ready"}` even though writes are silently failing (per the `finally` block's non-blocking `enqueue`, write failures don't even surface to the request path). This weakens the readiness signal's usefulness for orchestrators that gate traffic/restarts on it.
**Fix:** Have `health_ready` perform a lightweight liveness probe against the DB (e.g., reuse the `write_probe()`/a cheap `SELECT 1` already used at startup) rather than relying solely on attribute presence, or explicitly scope-document this as a "started" check rather than a "healthy" check if that's the intended contract.

## Info

### IN-01: `record_request`'s "safe without locks" comment is accurate only under the current single-process CMD

**File:** `metrics.py:9-11`
**Issue:** The comment correctly notes the current Dockerfile CMD (`uvicorn main:app` with no `--workers`) makes the module-level `dict` counters race-free under asyncio's cooperative scheduling. This is correct today, but it is a latent trap: `docker-compose.yml`/README don't document that scaling this service (e.g., `uvicorn --workers N`, or running multiple container replicas) would silently fragment metrics across processes with no error and no warning — each process/worker would report only its own slice of traffic, and Prometheus scraping any one instance would undercount.
**Fix:** No code change required; consider a one-line note in README's `/metrics` section (or a comment near the Dockerfile `CMD`) that horizontal/worker scaling requires migrating off the hand-rolled in-process counters (e.g., to `prometheus_client` with multiprocess mode) before it's safe.

### IN-02: `key_func=extract_bearer_key` fallback silently degrades to IP-only limiting for any malformed `Authorization` header shape

**File:** `rate_limiter.py:13-17`
**Issue:** `extract_bearer_key` treats any non-Bearer-prefixed or empty `Authorization` value as "no token" and falls back to `get_remote_address(request)`, which is a deliberate, documented, locked decision per the inline comment — not a bug. Flagged as Info only because the fallback means an attacker who simply omits/mangles the `Authorization` header trades a per-key limit for a per-IP limit, effectively getting a *shared* budget with every other unauthenticated caller behind the same NAT/proxy rather than a stricter one. Since `verify_auth` (unchanged, pre-existing) already 401s any request without a valid `APP_API_KEY` bearer token before this ever matters in practice, this has no exploitable effect in the current single-shared-key auth model — noted for awareness only, no fix required now.
**Fix:** None required; would only become relevant if per-key auth (multiple distinct API keys) is introduced later.

## Dispositions

### CR-01 — fixed
`Dockerfile:20` now copies `metrics.py` into the runtime stage (`COPY main.py config.py rate_limiter.py metrics.py ./`). Verified by an actual `docker compose up -d --build`: the container reaches Docker `healthy` status, and both `GET /health/ready` and `GET /metrics` respond `200` against the built image (not just the pytest checkout). Commit `8b44a27`.

### WR-01 — fixed
`tests/test_openai_compatible_base.py` no longer constructs bespoke `BalanceError`/`AuthError` stand-ins. `test_quota_1113_shaped_exception_is_never_retried` now raises a real `openai.APIStatusError` (HTTP 402 — the SDK's status-to-exception mapping has no dedicated 402 class, so the generic `APIStatusError` *is* the real production type for z.ai's "1113" balance error) and `test_auth_failure_shaped_exception_is_never_retried` now raises a real `openai.AuthenticationError` (401). Added two new tests, `test_real_ratelimiterror_is_never_retried` (429) and `test_real_permissiondeniederror_is_never_retried` (403), covering the remaining ZAI-3-excluded siblings of `APIStatusError`. Commit `1394821`.

### WR-02 — fixed
`analytics/db.py` gained `AnalyticsDB.ping()`, a read-only `SELECT 1` liveness probe (deliberately not `write_probe()`'s CREATE/DROP TABLE, since `/health/ready` may be polled far more often than startup). `main.py`'s `health_ready` now awaits `db.ping()` and returns `503 {"status":"not_ready"}` on any exception, in addition to the existing attribute-presence check. New regression test `test_health_ready_returns_503_when_db_ping_fails` closes the real analytics DB connection and asserts the endpoint now reports not-ready instead of a stale `200`. Commit `3081cac`.

### IN-01 — accepted, deferred
No code change required per the original review's own assessment (documentation-only follow-up: note near the Dockerfile `CMD`/README that horizontal scaling requires migrating off in-process counters). Left for a future phase that actually introduces multi-worker/multi-replica deployment; not in scope for Phase 04's single-process `CMD`.

### IN-02 — accepted, no action
Reviewer's own conclusion: not exploitable under the current single-shared-key `APP_API_KEY` auth model, since `verify_auth` already 401s any request lacking a valid bearer token before the rate-limiter's fallback path matters. Revisit only if per-key auth (multiple distinct API keys) is introduced.

---

_Reviewed: 2026-09-08T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
