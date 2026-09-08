# Requirements: LLM Gateway

**Defined:** 2026-09-08 (new-project-from-ingest)
**Core Value:** Reliable quota-backed GLM serving — zai-coding requests succeed without quota-exhaustion incidents across a full coding day, with credit burn visible via `GET /v1/analytics/credits`.

**Sourcing note:** 28 requirements were ingested from `docs/project-overview-pdr.md` (REQ-FR-01..22, REQ-NFR-01..06). Per SPEC-over-PRD precedence, 20 are **Baseline** (implemented current contracts — validated, not phase work) and 8 are **Historical/Superseded** (kept for traceability, never routed into active phases). This milestone's v1 requirements are derived from the ingest's open items (`.planning/intel/SYNTHESIS.md`) and are given fresh IDs below.

## Baseline (Implemented — Current System Contracts)

Already shipped and validated. These are invariants every phase must preserve, not work items. Detail: `.planning/intel/requirements.md` + `constraints.md`.

### Chat API

- [x] **REQ-FR-01**: `POST /v1/chat/completions` accepts OpenAI-style bodies; response streamed as SSE
- [x] **REQ-FR-02** (AMENDED): `model` resolves via `MODEL_ROUTING`; unknown non-GLM → `("manifest", name)` passthrough; unknown `glm-*` → zai-coding under the effective-key gate, else Manifest (strict-table rejection semantics superseded 2026-04-19)
- [x] **REQ-FR-03**: Tokens delivered as `data: {"token": "..."}\n\n`, terminated by `data: [DONE]\n\n`
- [x] **REQ-FR-04**: `messages` array with `user`/`assistant` roles accepted and forwarded
- [x] **REQ-FR-05**: Optional `system_prompt` prepended as system message
- [x] **REQ-FR-06**: Bearer auth (`APP_API_KEY`); missing/invalid → 401 `{"detail": "Invalid API key"}`; `/health` and `/playground` exempt
- [x] **GLM routing (current form of REQ-FR-11)**: `glm-*` → zai-coding canonicalized (`glm-5.3`/`glm-5.3-flash`; flash-named aliases → flash, never downgrade quality tier; unknown `glm-*` passthrough), degrading to Manifest canonical ids when no effective key
- [x] **REQ-FR-14**: `GET /v1/models` — OpenAI list format from `MODEL_ROUTING`, auth-required

### Analytics

- [x] **REQ-FR-15**: Every request logged fire-and-forget to `request_logs` (provider, model, tokens, latency_ms, ttft_ms, status, `credits_used`)
- [x] **REQ-FR-16**: `GET /v1/analytics/summary` — totals + optional `since`, auth-required
- [x] **REQ-FR-17**: `GET /v1/analytics/models` — per-model rows, `since`/`provider` filters, auth-required
- [x] **REQ-FR-18**: `GET /v1/analytics/requests` — paginated (limit 50/offset 0), auth-required
- [x] **REQ-FR-20**: Usage extracted from final chunk (`stream_options.include_usage`); `cached_tokens` optional on `UsageData`
- [x] **CREDITS (zai-coding spec, implemented)**: `GET /v1/analytics/credits` — rolling 5h/7d `credits_used` vs quota, per-model breakdown, off-peak share; `estimate_credits()` per locked formula

### Errors & Configuration

- [x] **REQ-FR-21**: SSE `data: {"error": "..."}` frames on failure; z.ai quota/auth messages distinct; internal exception text never leaked
- [x] **REQ-FR-22**: `get_api_key(provider)` returns dedicated key (`MANIFEST_API_KEY`/`ZAI_CODING_API_KEY`) with `LLM_API_KEY` fallback; empty string when unset

### Non-Functional (Baseline)

- [x] **REQ-NFR-01**: Gateway overhead <50ms per request (excl. LLM time)
- [x] **REQ-NFR-02**: Runtime deps limited to essentials (fastapi, uvicorn, pydantic-settings, openai, python-dotenv, aiosqlite, slowapi + test deps)
- [x] **REQ-NFR-03**: Single `.env` config via pydantic BaseSettings, no external config stores
- [x] **REQ-NFR-04**: Startup to request-readiness <3s
- [x] **REQ-NFR-05**: Fire-and-forget analytics logging never blocks/delays token streaming
- [x] **REQ-NFR-06**: SQLite WAL mode; concurrent analytics reads during request-log writes

## v1 Requirements (This Milestone)

Derived from ingest open items: production-readiness backlog, analytics retention, startup validation, SSE error alignment, `auto` deprecation decision, doc-refresh backlog. These drive the roadmap phases.

### Reliability Hardening (Phase 1)

- [x] **RELI-01**: Operator starting the gateway without `APP_API_KEY` gets an immediate, actionable startup abort naming the missing variable — never a cryptic request-time SDK error; starting with no effective z.ai key logs an explicit notice (no abort) and GLM routes degrade to Manifest per the key-gate, preserving opt-in/rollback-by-unset semantics
- [x] **RELI-02**: Under concurrent multi-stream load, every client receives its full token stream and every completed request appears exactly once in `request_logs`; pending analytics writes stay bounded (capped queue with graceful handling) even when SQLite writes lag
- [x] **RELI-03**: SSE error frames carry an OpenAI-style error object (message/type) while z.ai quota exhaustion and authentication failure remain distinctly identifiable; internal exception text never reaches clients

### Analytics Lifecycle (Phase 2)

- [x] **ANLT-01**: Operator can bound `request_logs` growth via a `.env` retention setting (TTL in days) with a documented default, applied to existing databases without manual SQL
- [x] **ANLT-02**: Rows older than the TTL are purged automatically (startup + periodic); `/v1/analytics/{summary,models,requests,credits}` serve retained data correctly; purging never blocks or delays response streaming (fire-and-forget preserved, WAL intact); on-disk growth is bounded and purged space is reclaimable

### Deployment (Phase 3)

- [x] **DEPL-01**: Gateway ships as a multi-stage, non-root Docker image that reaches request-readiness <3s from process start (NFR-04 holds in-container)
- [x] **DEPL-02**: `docker compose up` on a fresh clone with `.env` brings the gateway to a green healthcheck (`GET /health`); analytics DB persists on a volume across container recreation; all config via single-`.env` passthrough, no secrets baked into the image
- [x] **DEPL-03**: GitHub Actions runs lint + tests (and builds the image) on push/PR — broken changes are caught by CI before reaching the deployed container

### Observability & Resilience (Phase 4)

- [x] **OBSV-01**: A Prometheus-scrape endpoint exposes request count, latency histogram, and error rate (prefer zero new dependencies — hand-rolled text exposition; any new dep needs an explicit decision per NFR-02)
- [ ] **OBSV-02**: A client exceeding its configured per-key rate limit receives HTTP 429 from the gateway without provider traffic being sent; limit configurable via `.env`
- [x] **OBSV-03**: Transient provider errors (network timeouts, 5xx) retry with backoff against the same provider only; z.ai quota (429/code 1113) and auth (401/403) failures are never retried and never rerouted to Manifest (locked decision ZAI-3); after exhausted retries the client sees the provider-distinct error

### Routing & Documentation (Phase 5)

- [ ] **ROUT-01**: The `model="auto"` fate (keep, pin to an explicit model, or remove — it rides Manifest's 2026-09-01-deprecated prompt-complexity router) is decided with the user, recorded in PROJECT.md Key Decisions, and implemented with routing behavior + tests matching the recorded decision
- [ ] **DOCS-01**: `docs/project-overview-pdr.md` and `docs/project-roadmap.md` describe the current two-provider (Manifest + zai-coding) architecture; superseded provider/pricing requirements explicitly marked historical
- [ ] **DOCS-02**: `docs/deployment-guide.md` documents the Docker/Compose deployment and current env surface (no stale per-provider key/base-URL tables); `docs/code-standards.md` file tree and "Adding a New Provider" recipe match the shipped providers (no pricing step)

## v2 Requirements (Deferred — Not in Current Milestone)

### Stress-Support Chatbot (Optional Phase 6 — preconditions unmet)

- **SCB-01**: Product-specific `/v1/stress/chat` MVP on top of the gateway — self-hosted Gemma 4 E4B instruct via vLLM, local document retrieval (RAG), rule-first crisis gating; generic `/v1/chat/completions` unchanged; MVP stateless and text-only. **Blocked on preconditions**: target language, hosting target, crisis jurisdiction, source document formats (plan folder `plans/260418-1132-…` not in this ingest)

### Production Hardening (Low priority)

- **PROD-01**: Secrets management beyond `.env` — single-user single-container target makes this low value for now
- **PROD-02**: Horizontal scaling — stateless design noted; moot for the single-container target
- **PROD-03**: API versioning strategy — no external consumers beyond the owner's tooling yet

## Out of Scope

| Feature | Reason |
|---------|--------|
| Anthropic-Messages / Responses endpoints | Locked out of zai-coding design; not requested |
| GLM→Manifest fallback under any condition | Locked decision ZAI-3 |
| Real-time z.ai quota queries (dashboard API) | Locked out of zai-coding design; local estimation instead (ZAI-4) |
| Native 8-provider architecture revival | Superseded by Manifest cutover; ABC allows re-adding a direct provider if ever needed |
| Multi-tenant / accounts / public playground | Personal single-user gateway; explicit playground non-goal |

## Historical (Superseded — Traceability Only, Never Routed)

From the PRD; describe the pre-2026-04-19 architecture. Current equivalents noted.

- **REQ-FR-07**: Native OpenAIProvider (gpt-4o/gpt-4o-mini/o3) — superseded 2026-04-19; OpenAI models now via `("manifest", <model>)` passthrough; provider file deleted
- **REQ-FR-08**: Native DeepSeek provider — superseded; deepseek-chat et al. route via Manifest
- **REQ-FR-09**: Native MoonshotAI (Kimi) provider — superseded; kimi/moonshot models route via Manifest
- **REQ-FR-10**: Native Gemini provider via `google-genai` SDK — superseded; Gemini via Manifest; `google-genai` dependency removed
- **REQ-FR-11**: Native GLM (Z.AI) provider — superseded 2026-04-19, re-routed 2026-09-07; current contract = Baseline "GLM routing" above (zai-coding, key-gated, canonicalized)
- **REQ-FR-12**: Native MiniMax provider — superseded; MiniMax models route via Manifest
- **REQ-FR-13**: Native ByteDance (Doubao) provider — superseded; endpoint-ID models route via Manifest
- **REQ-FR-19**: Per-request cost from `MODEL_PRICING` table — superseded; `calculate_cost()` returns 0.0 (Manifest bills internally); only monetary metric is zai credit estimation (`estimate_credits()`, `/v1/analytics/credits`)

## Traceability

v1 (active) requirements → phases. Baseline and Historical sections are intentionally not routed (implemented / superseded respectively).

| Requirement | Phase | Status |
|-------------|-------|--------|
| RELI-01 | Phase 1 | Complete |
| RELI-02 | Phase 1 | Complete |
| RELI-03 | Phase 1 | Complete |
| ANLT-01 | Phase 2 | Complete |
| ANLT-02 | Phase 2 | Complete |
| DEPL-01 | Phase 3 | Complete |
| DEPL-02 | Phase 3 | Complete |
| DEPL-03 | Phase 3 | Complete |
| OBSV-01 | Phase 4 | Complete |
| OBSV-02 | Phase 4 | Pending |
| OBSV-03 | Phase 4 | Complete |
| ROUT-01 | Phase 5 | Pending |
| DOCS-01 | Phase 5 | Pending |
| DOCS-02 | Phase 5 | Pending |
| SCB-01 | Phase 6 (optional, v2-gated) | Deferred |

**Coverage:**

- v1 requirements: 14 total · mapped to phases: 14 · unmapped: 0 ✓
- Ingested PRD requirements: 28 total · 20 Baseline (implemented — not routed) · 8 Historical/Superseded (not routed)
- Optional Phase 6 carries v2 item SCB-01 and does not count toward v1 coverage

---
*Requirements defined: 2026-09-08*
*Last updated: 2026-09-08 after new-project-from-ingest bootstrap*
