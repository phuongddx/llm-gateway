# Phase 4: Observability & Resilience - Context

**Gathered:** 2026-09-08
**Status:** Ready for planning

<domain>
## Phase Boundary

The deployed gateway exposes operational metrics and absorbs transient provider failures — strictly within the locked no-fallback constraints (ZAI-3). Delivers OBSV-01 (metrics + health split), OBSV-02 (per-key rate limiting), OBSV-03 (same-provider-only transient retry). Depends on Phase 3 (Compose healthcheck repoint, CI gates additions).

</domain>

<decisions>
## Metrics + Health Split
- `GET /metrics` — unauthenticated (standard Prometheus scrape convention), hand-rolled text-exposition format (no `prometheus_client` dependency, per locked NFR-02 preference)
- Metrics: `gateway_requests_total{provider,model,status}` counter, `gateway_request_duration_seconds{provider,model}` histogram, error rate derived from counts
- `/health` splits into `/health/live` (process up) and `/health/ready` (analytics DB initialized + writer running); Phase-3 Compose healthcheck repoints to `/health/ready`

## Per-Key Rate Limiting
- New slowapi `key_func` extracts the Bearer token (falls back to remote IP if missing/malformed)
- `RATE_LIMIT_PER_KEY` env var (new, separate from existing `RATE_LIMIT` per-IP floor, which stays as a secondary limit — both apply)
- Exceeding the per-key limit → HTTP 429 before any provider call is made

## Transient Retry
- **Dependency decision: add `tenacity`** to `requirements.txt` (explicit deviation from the NFR-02 minimal-deps default, made knowingly by the user in place of a hand-rolled retry loop)
- Retry policy: max 2 retries, exponential backoff with jitter, applied ONLY to network timeouts/connection errors and 5xx from the CURRENT provider — never cross-provider, never a fallback
- z.ai quota (429/1113) and auth (401/403) short-circuit immediately — zero retries, ZAI-3 preserved exactly as locked
- Retry attempts logged; after retry exhaustion the client sees the existing provider-distinct error mapping (from Phase 1's OpenAI-style error frames)

### Claude's Discretion
None — all areas resolved.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `rate_limiter.py` single shared `slowapi.Limiter` instance; `routes/chat.py` `@limiter.limit(settings.rate_limit)` — key_func currently default (get_remote_address)
- `routes/chat.py` `verify_auth` Bearer extraction pattern (removeprefix) — reuse for the per-key limiter's key_func
- `main.py` `/health` endpoint (no auth) — split point; lifespan already tracks DB init + writer start/stop state
- `routes/chat.py` `_tracked_stream` provider-distinct error mapping (Phase 1) — retry exhaustion reuses these exact messages
- `providers/openai_compatible_base.py` `chat_stream` — retry wraps the upstream call site here (per-provider, not cross-provider)
- `config.py` Settings + `.env.example` pattern for the new env vars

### Established Patterns
- pytest-asyncio, `unittest.mock.patch`, fixture reuse; deterministic time-control patterns from Phase 1/2

### Integration Points
- `main.py` (new /metrics + /health/live + /health/ready routes), `rate_limiter.py` (new key_func), `routes/chat.py` (per-key limiter decorator, retry wrapping), `providers/openai_compatible_base.py` (retry decorator on the upstream call), `requirements.txt` (+tenacity), `docker-compose.yml` (Phase 3 — healthcheck repoint to /health/ready; optional Prometheus profile), `.env.example`, README

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>
