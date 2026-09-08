# Requirements Intel (ingest 2026-09-08)

Source PRD: `docs/project-overview-pdr.md` (the only PRD-classified document).
28 requirements extracted verbatim in PRD order (FR-1..FR-22, NFR-1..NFR-6).

Currency annotations (applied per precedence ADR > SPEC > PRD > DOC; no ADRs in
set, so the two SPECs — `docs/system-architecture.md` and
`docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md` — are the
top-precedence current-state authority):

- SUPERSEDED (8): FR-7..FR-13, FR-19 — describe the 8-native-provider /
  pricing-table architecture replaced by the Manifest cutover (2026-04-19) and
  zai-coding routing (2026-09-07). Kept for traceability; do NOT route as
  current scope. Detail in `../INGEST-CONFLICTS.md` (INFO entries).
- AMENDED (1): FR-2 — routing table still exists, but unknown-model handling is
  passthrough, not lookup-failure.

## REQ-FR-01
- source: docs/project-overview-pdr.md
- description: Accept OpenAI-style chat completion requests via `POST /v1/chat/completions` (current — endpoint live)
- acceptance: OpenAI-style request body accepted; response streamed as SSE
- scope: chat completions API

## REQ-FR-02
- source: docs/project-overview-pdr.md
- description: Route requests to provider based on `model` field via `MODEL_ROUTING` dict. AMENDED: routing table is now a curated list over two providers (manifest, zai-coding); unknown models are passed through, not rejected (see `docs/system-architecture.md`; supersedes the PRD's strict-table semantics)
- acceptance: `model` resolves to `(provider, model_id)`; unknown non-GLM → `("manifest", name)`; unknown `glm-*` → zai-coding when effective key set, else manifest
- scope: model routing

## REQ-FR-03
- source: docs/project-overview-pdr.md
- description: Stream response tokens as SSE events (current)
- acceptance: tokens delivered as `data: {"token": "..."}\n\n` frames, terminated by `data: [DONE]\n\n`
- scope: SSE streaming

## REQ-FR-04
- source: docs/project-overview-pdr.md
- description: Support `messages` array with `user` and `assistant` roles (current)
- acceptance: multi-turn message arrays accepted and forwarded
- scope: chat completions API

## REQ-FR-05
- source: docs/project-overview-pdr.md
- description: Support optional `system_prompt` parameter (current — prepended as system message)
- acceptance: system prompt present in provider payload when supplied
- scope: chat completions API

## REQ-FR-06
- source: docs/project-overview-pdr.md
- description: Authenticate requests via Bearer token (`APP_API_KEY`) (current; `verify_auth()` — `/health` and `/playground` exempt)
- acceptance: missing/invalid token → HTTP 401 `{"detail": "Invalid API key"}`
- scope: authentication

## REQ-FR-07
- source: docs/project-overview-pdr.md
- description: SUPERSEDED (2026-04-19 Manifest cutover): Route to OpenAI provider. Original: native OpenAIProvider for gpt-4o/gpt-4o-mini/o3
- acceptance: historical only — OpenAI models now reachable via `("manifest", <model>)` passthrough; native provider file deleted (`plans/0419-2337-manifest-provider-integration/phase-03-cleanup-old-providers-and-cost.md`)
- scope: provider routing (historical)

## REQ-FR-08
- source: docs/project-overview-pdr.md
- description: SUPERSEDED (2026-04-19): Route to DeepSeek provider via native provider
- acceptance: historical only — deepseek-chat et al. route via Manifest
- scope: provider routing (historical)

## REQ-FR-09
- source: docs/project-overview-pdr.md
- description: SUPERSEDED (2026-04-19): Route to MoonshotAI (Kimi) provider via native provider
- acceptance: historical only — kimi/moonshot models route via Manifest
- scope: provider routing (historical)

## REQ-FR-10
- source: docs/project-overview-pdr.md
- description: SUPERSEDED (2026-04-19): Route to Gemini provider via `google-genai` SDK
- acceptance: historical only — Gemini models route via Manifest; `google-genai` dependency removed
- scope: provider routing (historical)

## REQ-FR-11
- source: docs/project-overview-pdr.md
- description: SUPERSEDED (2026-04-19 native cutover; GLM re-routed 2026-09-07): Route to GLM (Z.AI) provider. Current: `glm-*` → zai-coding provider (key-gated, canonicalized to glm-5.3 / glm-5.3-flash), degrading to Manifest without a key
- acceptance: current contract per zai-coding design spec §2.1 (canonicalization + effective-key gate)
- scope: provider routing (GLM)

## REQ-FR-12
- source: docs/project-overview-pdr.md
- description: SUPERSEDED (2026-04-19): Route to MiniMax provider via native provider
- acceptance: historical only — MiniMax models route via Manifest
- scope: provider routing (historical)

## REQ-FR-13
- source: docs/project-overview-pdr.md
- description: SUPERSEDED (2026-04-19): Route to ByteDance (Doubao) provider via native provider
- acceptance: historical only — ByteDance endpoint-ID models route via Manifest
- scope: provider routing (historical)

## REQ-FR-14
- source: docs/project-overview-pdr.md
- description: List available models via `GET /v1/models` (current; OpenAI-compatible format, built from `MODEL_ROUTING`)
- acceptance: `{"object": "list", "data": [{"id", "object", "owned_by"}]}`; auth required
- scope: model listing API

## REQ-FR-15
- source: docs/project-overview-pdr.md
- description: Log request analytics (tokens, latency, TTFT, cost) to SQLite (current — cost column retained but always 0.0; credits_used added 2026-09-07)
- acceptance: every request logged fire-and-forget to `request_logs` incl. provider, model, tokens, latency_ms, ttft_ms, status
- scope: analytics storage

## REQ-FR-16
- source: docs/project-overview-pdr.md
- description: Expose analytics summary via `GET /v1/analytics/summary` (current)
- acceptance: totals (requests, tokens, cost_usd, avg latency, avg TTFT, error rate), optional `since` filter; auth required
- scope: analytics API

## REQ-FR-17
- source: docs/project-overview-pdr.md
- description: Expose per-model stats via `GET /v1/analytics/models` (current)
- acceptance: per-model rows grouped by model + provider; optional `since`/`provider` filters; auth required
- scope: analytics API

## REQ-FR-18
- source: docs/project-overview-pdr.md
- description: Expose recent requests via `GET /v1/analytics/requests` (current)
- acceptance: paginated list (limit default 50 / offset default 0) with all `request_logs` fields; auth required
- scope: analytics API

## REQ-FR-19
- source: docs/project-overview-pdr.md
- description: SUPERSEDED: Calculate cost per request using model pricing table. Current: `calculate_cost()` always returns 0.0 (Manifest bills internally; signature preserved); the only monetary metric is zai-coding credit estimation (`estimate_credits()`, `GET /v1/analytics/credits`)
- acceptance: historical only — pricing table removed 2026-04-19; see `docs/system-architecture.md` usage-data flow
- scope: cost tracking (historical)

## REQ-FR-20
- source: docs/project-overview-pdr.md
- description: Extract token usage from provider responses (current — final-chunk usage via `stream_options.include_usage`; `UsageData` now also carries optional `cached_tokens`)
- acceptance: prompt/completion/total tokens recorded per request
- scope: analytics storage

## REQ-FR-21
- source: docs/project-overview-pdr.md
- description: Return structured error payloads in SSE stream on failure (current; zai-coding errors get distinct quota/auth messages; internal exception text never leaked)
- acceptance: failures yield `data: {"error": "..."}\n\n` frames; quota/auth messages distinguishable per provider
- scope: error handling

## REQ-FR-22
- source: docs/project-overview-pdr.md
- description: Per-provider API key support with `LLM_API_KEY` fallback (current, reduced surface: dedicated keys exist only for `manifest` and `zai-coding`)
- acceptance: `get_api_key(provider)` returns dedicated key or `llm_api_key` fallback; empty string when unset
- scope: configuration

## REQ-NFR-01
- source: docs/project-overview-pdr.md
- description: Response latency overhead under 50ms added by gateway (excluding LLM response time)
- acceptance: gateway overhead < 50ms per request
- scope: performance

## REQ-NFR-02
- source: docs/project-overview-pdr.md
- description: Dependencies limited to runtime essentials (FastAPI, provider SDK, pydantic-settings, aiosqlite; current set: fastapi, uvicorn, pydantic-settings, openai, python-dotenv, aiosqlite, pytest, pytest-asyncio, httpx, slowapi)
- acceptance: no non-essential runtime dependencies; zai-coding plan mandates zero new deps
- scope: dependencies

## REQ-NFR-03
- source: docs/project-overview-pdr.md
- description: Configuration via single `.env` file, no external config stores
- acceptance: all settings loadable from `.env` via pydantic BaseSettings
- scope: configuration

## REQ-NFR-04
- source: docs/project-overview-pdr.md
- description: Startup time under 3 seconds to first request readiness
- acceptance: ready to serve within 3s of process start
- scope: performance

## REQ-NFR-05
- source: docs/project-overview-pdr.md
- description: Fire-and-forget analytics logging, no blocking of response stream (`asyncio.create_task`)
- acceptance: DB write failure never breaks or delays token streaming
- scope: analytics performance

## REQ-NFR-06
- source: docs/project-overview-pdr.md
- description: SQLite WAL mode for concurrent read/write
- acceptance: WAL enabled at `AnalyticsDB.initialize()`; concurrent analytics reads during request-log writes
- scope: analytics storage
