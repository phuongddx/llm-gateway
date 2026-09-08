# LLM Gateway

## What This Is

A FastAPI-based, OpenAI-compatible LLM gateway serving a single developer's coding workflows. Clients send a `model` name; the gateway resolves it across exactly two providers — Manifest (default, 500+ model passthrough) and the z.ai GLM Coding Plan endpoint (quota-backed, key-gated `glm-*` routing) — streams every response via SSE, and logs per-request analytics (tokens, latency, TTFT, credit burn) to SQLite. Zero infrastructure dependencies: one Python process, one `.env` file.

## Core Value

Reliable quota-backed GLM serving: zai-coding requests succeed without quota-exhaustion incidents across a full coding day, with credit burn visible at `GET /v1/analytics/credits`.

**Target runtime:** Docker/Compose single-container deployment (persistent volume for the analytics DB; all config via `.env` passthrough).

## Locked Decisions

No ADRs exist in this project (ingest 2026-09-08 classified 0 of 26 docs as ADR). The following four user-locked z.ai Coding Plan design decisions — recorded as protocol constraints in `.planning/intel/constraints.md` from the Approved spec — are promoted to locked `<decisions>` per the bootstrap directive. They constrain ALL future work; changing any of them requires explicit user decision.

<decisions locked="true" source="docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md" locked-with-user="2026-09-07" ingested="2026-09-08">
  <decision id="ZAI-1" title="z.ai GLM Coding Plan, Max tier">
    Subscribe to the GLM Coding Plan at Max tier (~$80/month billed quarterly;
    28,000 credits per rolling 5-hour window, 140,000/week, ~30 concurrent
    requests; exactly two models GLM-5.3 and GLM-5.3-Flash; quota exhaustion
    does NOT fall back to account balance — calls fail until reset).
    Quotas are env-configurable (ZAI_CREDITS_5H / ZAI_CREDITS_WEEK).
  </decision>
  <decision id="ZAI-2" title="Coding endpoint, ToS risk explicitly accepted">
    Send GLM traffic to the coding endpoint
    (https://api.z.ai/api/coding/paas/v4). The ToS risk — plan "strictly
    limited to officially supported tools", custom gateway not on the list —
    is explicitly accepted by the user. Mitigations: correct endpoint, only
    valid canonical model IDs, no non-GLM traffic sent to z.ai, hard-fail so
    misuse surfaces immediately.
  </decision>
  <decision id="ZAI-3" title="All GLM → coding endpoint, NO fallback">
    Every GLM request routes to the z.ai coding endpoint; z.ai errors NEVER
    reroute to Manifest (never silently pay Manifest for GLM). Quota
    exhaustion (HTTP 429 or z.ai error code 1113) and auth failure (401/403)
    hard-fail with distinct client-visible errors. Any retry logic added in
    the future must be same-provider, transient-errors-only (never quota,
    never auth, never a Manifest reroute).
  </decision>
  <decision id="ZAI-4" title="Credit estimation in analytics">
    z.ai credit burn is estimated locally via estimate_credits() —
    (input×I + cached×C + output×O)/10,000, glm-5.3 = 6.9/1.7/24 and
    glm-5.3-flash = 2.3/0.56/8, charged at 0.5× outside peak (Mon–Fri
    14:00–18:00 UTC+8) — and exposed via GET /v1/analytics/credits (rolling
    5h/7d windows vs quota, per-model breakdown, off-peak share).
    calculate_cost() stays 0.0 (Manifest bills internally). No real-time
    quota queries against z.ai's dashboard API.
  </decision>
</decisions>

Also locked alongside (out of scope per the same spec): Anthropic-Messages/Responses API endpoints; GLM→Manifest fallback under any condition. The spec additionally scoped "changes to the deprecated Manifest-`auto` entry" out of the zai-coding work while explicitly flagging it as a future decision — that future decision is now roadmap item ROUT-01 (Phase 5), which is the sanctioned path to revisit it.

## Requirements

### Validated

<!-- Shipped and confirmed valuable — the implemented baseline this milestone must not regress.
Full contracts: docs/system-architecture.md, zai-coding spec, .planning/intel/constraints.md -->

- ✓ OpenAI-compatible `POST /v1/chat/completions` with SSE streaming (`data: {"token": ...}` frames, `data: [DONE]` terminator); `messages` array (user/assistant roles); optional `system_prompt` prepended — REQ-FR-01/03/04/05
- ✓ Model routing with passthrough semantics: unknown non-GLM → `("manifest", name-as-given)`; `glm-*` → zai-coding canonicalized to `glm-5.3`/`glm-5.3-flash` (flash-named aliases → flash; never downgrade quality tier), degrading to Manifest canonical ids when no effective z.ai key (`ZAI_CODING_API_KEY` or `LLM_API_KEY`) — REQ-FR-02 (amended), current form of REQ-FR-11
- ✓ Bearer auth on all `/v1/` endpoints via `APP_API_KEY` (401 `{"detail": "Invalid API key"}`); `/health` and `/playground` exempt — REQ-FR-06
- ✓ `GET /v1/models` (OpenAI list format, built from `MODEL_ROUTING`) — REQ-FR-14
- ✓ SQLite analytics: fire-and-forget `request_logs` (provider, model, tokens, latency_ms, ttft_ms, status, `credits_used`), WAL mode, idempotent `credits_used` migration — REQ-FR-15/20, REQ-NFR-05/06
- ✓ Analytics API (auth-required): `/v1/analytics/summary`, `/v1/analytics/models`, `/v1/analytics/requests`, `/v1/analytics/credits` — REQ-FR-16/17/18 + zai-coding spec
- ✓ SSE error payloads with provider-distinct z.ai quota/auth messages; internal exception text never leaked — REQ-FR-21
- ✓ Config: dedicated `MANIFEST_API_KEY` / `ZAI_CODING_API_KEY` with `LLM_API_KEY` fallback (`get_api_key(provider)`); single `.env` via pydantic BaseSettings singleton — REQ-FR-22, REQ-NFR-03
- ✓ NFRs held: <50ms gateway overhead, <3s startup, minimal runtime deps — REQ-NFR-01/02/04
- ✓ Playground web UI: static HTML/vanilla JS, no build step, session-only key in JS memory, localStorage conversations — Era 2 (non-goals honored)

### Active

- [ ] RELI-01 — Startup key validation: fail fast on missing `APP_API_KEY`; explicit notice (no abort) when no effective z.ai key, preserving opt-in/rollback-by-unset semantics
- [ ] RELI-02 — Bounded analytics write path under concurrent streaming: capped queue, no dropped logs, streaming never blocked when SQLite lags
- [ ] RELI-03 — SSE error frames aligned with the OpenAI error-object shape; quota/auth messages stay distinct; no internal text leaked
- [ ] ANLT-01 — Retention setting bounds `request_logs` growth (`.env` TTL, documented default)
- [ ] ANLT-02 — Automatic purge (startup + periodic) keeps analytics endpoints correct without blocking streams
- [ ] DEPL-01 — Multi-stage non-root Docker image, request-ready <3s in-container
- [ ] DEPL-02 — Single `docker compose up` deployment: green healthcheck, persistent analytics volume, `.env` passthrough, no baked secrets
- [ ] DEPL-03 — GitHub Actions CI: lint + tests + image build on push/PR
- [ ] OBSV-01 — Prometheus metrics (request count, latency histogram, error rate) at a scrape endpoint
- [ ] OBSV-02 — Per-key rate limiting enforced (HTTP 429 before provider traffic), configurable via `.env`
- [ ] OBSV-03 — Same-provider-only transient-error retry with backoff; never retries z.ai quota/auth, never reroutes to Manifest
- [ ] ROUT-01 — `model="auto"` deprecation decision resolved (keep/pin/remove), implemented, recorded
- [ ] DOCS-01 — `project-overview-pdr.md` + `project-roadmap.md` refreshed to two-provider reality; superseded FRs marked historical
- [ ] DOCS-02 — `deployment-guide.md` (Docker/Compose + current env surface) + `code-standards.md` (file tree, provider recipe) refreshed

### Out of Scope

| Feature | Reason |
|---------|--------|
| Anthropic-Messages / Responses API endpoints | Locked out of the zai-coding design; not requested |
| GLM→Manifest fallback under any condition | Locked decision ZAI-3 — never silently pay Manifest for GLM |
| Real-time quota queries against z.ai dashboard API | Locked out of the zai-coding design — local estimation (ZAI-4) instead |
| Reviving the 8-native-provider architecture | Superseded 2026-04-19 by Manifest cutover; re-add a direct provider via the `LLMProvider` ABC only if a concrete need appears |
| Multi-tenant use / user accounts / public playground | Personal single-user gateway; playground auth is an explicit non-goal until it goes public |
| Stress-chatbot MVP (v2) | Future direction with unmet preconditions — optional Phase 6, not milestone scope |
| Secrets management beyond `.env`, horizontal scaling, API versioning | Production backlog "Low" priority; single-container single-user target makes them moot for now (v2) |

## Context

- **Architecture evolution:** Gemini-only prototype (~1200 LOC) → 2026-04-16 multi-provider router + analytics → 2026-04-17 playground UI → 2026-04-19 Manifest cutover (all native providers collapsed into ManifestProvider; cost calc stubbed to 0.0) → 2026-09-07 zai-coding (GLM → Coding Plan endpoint with credit analytics). Current: ~1,800 LOC, ~24 Python files, two providers.
- **Current-state authority:** `docs/system-architecture.md` + `docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md` (both current); `docs/codebase-summary.md` current. The PRD/deployment-guide/code-standards/project-roadmap docs are stale on the superseded architecture — refresh is roadmap Phase 5.
- **z.ai economics (why Max tier works):** heavy agentic turn ≈36.6 credits → ~3,800 heavy turns/week on quota vs ~$230/week pay-as-you-go equivalent; cache-hit coding traffic ≈5–10× cost reduction. Quota exhaustion mid-session = GLM unavailable up to 5h (mitigated by distinct quota errors + credits analytics).
- **Accepted risk:** Manifest API downtime = all non-GLM requests fail (single point of failure, acceptable for personal use). Unsetting `ZAI_CODING_API_KEY` reverts all GLM routing to Manifest pay-per-token.
- **Lessons that still govern:** generator wrapper (`_tracked_stream`) over middleware for analytics; static routing dicts in Python (auditable, git-controlled — no config DB); SQLite + WAL for single-instance analytics; `OpenAICompatibleProvider` base makes each new OpenAI-protocol provider ~8–11 lines.
- **Open engineering items** (drove this roadmap): startup key validation, concurrent-streaming load test of fire-and-forget logging, SSE error schema alignment, analytics retention, Manifest-`auto` deprecation decision, production-readiness backlog (Docker/Compose target, CI, metrics, rate limiting, retry), doc-refresh backlog.

## Constraints

- **Tech stack**: Python 3.12+ floor, FastAPI, AsyncOpenAI, pydantic-settings, aiosqlite — no 3.13-only syntax; kebab-case filenames, TypedDict payloads, PEP 604 unions
- **Dependencies**: no new runtime dependencies without an explicit decision (REQ-NFR-02; zai-coding plan mandated zero new deps — prefer hand-rolled Prometheus text exposition over `prometheus-client` unless decided otherwise)
- **Deployment**: Docker/Compose single container — multi-stage, non-root, persistent volume for SQLite, single `.env` passthrough, no secrets baked into the image
- **Protocol**: locked decisions ZAI-1..4 (above) — in particular the no-fallback rule constrains all retry/resilience work
- **Config**: single `.env`, one shared `settings` singleton from `config.py`; never construct a second one
- **Compatibility**: OpenAI-compatible API surface preserved; <50ms gateway overhead; <3s startup; WAL concurrent reads during writes
- **Security**: client-facing errors never leak internal exception text
- **Testing**: no live z.ai calls in the suite; mock `create_provider` via `unittest.mock.patch` (no dependency_overrides); `httpx.AsyncClient` over `ASGITransport`; `@pytest.mark.asyncio` on every async test; commits after every green task

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| z.ai Coding Plan, Max tier (ZAI-1) | ~3,800 heavy turns/wk vs ~$230/wk pay-as-you-go; cache hits 5–10× | ✓ Good |
| Coding endpoint, ToS risk accepted (ZAI-2) | User-accepted; mitigations confine blast radius (correct endpoint, canonical IDs only, no non-GLM traffic, hard-fail) | — Pending (watch for z.ai enforcement changes) |
| All GLM → coding endpoint, no fallback (ZAI-3) | Never silently pay Manifest for GLM; misuse surfaces immediately | ✓ Good |
| Credit estimation in analytics (ZAI-4) | Quota visibility without depending on z.ai dashboard API | ✓ Good |
| Manifest cutover to single default provider (2026-04-19) | Collapse operational surface; SPOF accepted for personal use; re-add via ABC if needed | ✓ Good |
| Static routing/config dicts in Python | Auditable, change-controlled via git; no admin UI to justify a config DB | ✓ Good |
| SQLite + WAL for analytics | Right call for single-instance; no Postgres, no migration framework | ✓ Good |
| Playground: static HTML + vanilla JS, no build step | YAGNI — playground, not product | ✓ Good |

---
*Last updated: 2026-09-08 after new-project-from-ingest bootstrap (ingest of 26 docs: 0 ADR, 2 SPEC, 1 PRD, 23 DOC)*
