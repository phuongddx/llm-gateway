# Constraints Intel (ingest 2026-09-08)

Extracted from the two SPEC-classified sources (current-state authority) plus
repo engineering conventions lifted from the current zai-coding implementation
plan (DOC). Types: api-contract | schema | nfr | protocol.

## zai-coding provider contract
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: protocol
- content: `ZAICodingProvider(OpenAICompatibleProvider)` mirrors `ManifestProvider`: class attrs only — `base_url = "https://api.z.ai/api/coding/paas/v4"`, `default_model = "glm-5.3"`. No new streaming logic; the shared base already handles SSE + `stream_options.include_usage`.

## Factory dispatch: zai-coding + Manifest default
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: protocol
- content: `create_provider()` dispatches `provider_name == "zai-coding"` → `ZAICodingProvider`; every other name → `ManifestProvider` (unchanged default; unknown provider names still get Manifest, preserving passthrough semantics).

## GLM routing canonicalization
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: protocol
- content: `MODEL_ROUTING` gains canonical `glm-5.3` / `glm-5.3-flash` → `("zai-coding", canonical)`. Flash-named aliases (`glm-4.5-flash`, `glm-4.7-flash`, `glm-4.7-flashx`) → `glm-5.3-flash`; every other `glm-*` alias — including `glm-5-turbo`, which is not flash-named — → `glm-5.3` (never downgrade a request's quality tier). Unknown `glm-*` models (prefix match) also route to zai-coding with the name passed through (z.ai auto-maps or errors clearly). All other unknown models stay Manifest-passthrough. Non-GLM entries untouched.

## Effective-key gate for GLM routing
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: protocol
- content: When the effective key — `settings.get_api_key("zai-coding")`, i.e. `zai_coding_api_key or llm_api_key` — is empty, every GLM route (table entry or prefix match) resolves to `("manifest", canonical_model)` instead. Gating on the effective key (not the dedicated env var alone) keeps the `llm_api_key` fallback live. No key ⇒ behavior identical to the Manifest-only gateway; feature is opt-in via env; rollback = unset `ZAI_CODING_API_KEY`.

## zai-coding configuration contract
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: schema
- content: `zai_coding_api_key: str = ""` (env `ZAI_CODING_API_KEY`); `zai_credits_5h: int = 28000`; `zai_credits_week: int = 140000` (Max-plan defaults; adjust per tier). `get_api_key("zai-coding")` returns `zai_coding_api_key or llm_api_key` (same fallback pattern as Manifest).

## Credit estimation formula
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: api-contract
- content: `estimate_credits(provider, model, usage, ts) -> float` = `(input × I + cached_input × C + output × O) / 10,000` with multipliers glm-5.3 = 6.9/1.7/24 and glm-5.3-flash = 2.3/0.56/8, charged at 0.5× outside peak (peak = Mon–Fri 14:00–18:00 UTC+8). Returns 0.0 for non-`zai-coding` providers; `calculate_cost()` unchanged (still 0.0). Cached tokens read from the final usage chunk's `prompt_tokens_details.cached_tokens` when present, else 0 (conservative overestimate). `UsageData` (TypedDict) gains `cached_tokens: NotRequired[int]` — read via `usage.get("cached_tokens", 0)`; construction site in `openai_compatible_base.py` updated in the same change.

## request_logs.credits_used migration
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: schema
- content: `request_logs` gains `credits_used REAL NOT NULL DEFAULT 0`. Migration is idempotent, run in `AnalyticsDB.init()`: `ALTER TABLE request_logs ADD COLUMN credits_used REAL NOT NULL DEFAULT 0`, swallowing the duplicate-column error (SQLite has no `IF NOT EXISTS` for columns). Existing rows valid (0.0 = pre-feature or non-zai requests). New query `get_credits_summary()`: rolling 5-hour and rolling 7-day sums of `credits_used` (both anchored to now), grouped per model, plus off-peak share — both figures are rolling estimates, labeled as such in the API response.

## GET /v1/analytics/credits response contract
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: api-contract
- content: Auth-required (`Depends(verify_auth)`), same family as `/v1/analytics/{summary,models,requests}`. Response: `{"window_5h": {"credits_used", "quota"}, "window_7d_rolling": {"credits_used", "quota", "note": "rolling estimate; z.ai weekly reset anchored to subscription date"}, "by_model": {"<model>": {"credits_used", "requests"}}, "off_peak_share": <float>}`.

## No-fallback error handling for zai-coding
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: protocol
- content: No fallback, by design — z.ai failures never reroute to Manifest. Quota exhaustion (HTTP 429 or z.ai error code 1113) → SSE frame `{"error": "zai-coding quota exhausted — resets within the 5-hour window"}` (or HTTP 429 before the stream opens). Auth failure (401/403) → `{"error": "zai-coding authentication failed"}` / HTTP 502 pre-stream. Any other failure → existing generic internal-error frame; internal exception text is never leaked.

## zai-coding locked design decisions
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: protocol
- content: Decisions locked with user: Max plan tier; coding endpoint with ToS risk explicitly accepted (mitigations: correct endpoint, only valid canonical model IDs, no non-GLM traffic sent to z.ai, hard-fail so misuse surfaces immediately); all GLM → coding endpoint, **no fallback** (never silently pay Manifest for GLM); credit estimation included in analytics. Out of scope: Anthropic-Messages/Responses endpoints; GLM→Manifest fallback under any condition; changes to the deprecated Manifest-`auto` entry; real-time quota queries against z.ai's dashboard API.

## zai-coding testing constraints
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md
- type: protocol
- content: No live z.ai calls in the suite. Mock `create_provider` via `unittest.mock.patch`; `httpx.AsyncClient` over `ASGITransport`; `@pytest.mark.asyncio` on async tests. Coverage: routing canonicalization/prefix rule/key-gate degradation, credit math (base, cached discount, off-peak 50%, Flash multipliers, non-zai → 0.0), column migration on fresh + pre-existing schema, `get_credits_summary()` boundaries, quota/auth SSE error mapping. One manual smoke test (real key, single `glm-5.3` completion + quota-state check) at implementation time.

## Gateway API surface
- source: docs/system-architecture.md
- type: api-contract
- content: `POST /v1/chat/completions` (OpenAI-compatible, Bearer auth, SSE streaming); `GET /v1/models` (auth); `GET /v1/analytics/{summary,models,requests,credits}` (auth); `GET /playground` (no auth to load page); `GET /health` (no auth); `/static` StaticFiles mount. All `/v1/` endpoints require authentication.

## Provider abstraction contract
- source: docs/system-architecture.md
- type: schema
- content: `LLMProvider` (ABC) with `chat_stream() -> AsyncGenerator[StreamChunk, None]`; `StreamChunk = (str, UsageData | None)` — usage populated only on the final chunk; `GenParams` TypedDict (`total=False`): `temperature?`, `max_tokens?`, `top_p?`. Hierarchy: `LLMProvider` → `OpenAICompatibleProvider` (shared base; `base_url` + `default_model` class attrs; `AsyncOpenAI` client; `stream_options={"include_usage": True}`) → `ManifestProvider` (`https://app.manifest.build/v1`, default `"auto"`, 500+ models) and `ZAICodingProvider` (`https://api.z.ai/api/coding/paas/v4`, default `"glm-5.3"`). Exactly two providers.

## Routing model
- source: docs/system-architecture.md
- type: protocol
- content: `MODEL_ROUTING` (29 entries) maps names → `(provider, model_id)`. Non-GLM → `("manifest", <model_id>)`; GLM routes → `("zai-coding", <canonical_id>)` (flash-named aliases → `glm-5.3-flash`, other GLM aliases → `glm-5.3`), degrading to Manifest with canonical ids when no effective z.ai key (`ZAI_CODING_API_KEY` or `LLM_API_KEY`). Unknown `glm-*` names go to zai-coding under the same key gate; all other unknown names pass through to Manifest as-is (full 500+ catalog). `model="auto"` enables Manifest smart routing.

## Authentication contract
- source: docs/system-architecture.md
- type: protocol
- content: `verify_auth()` extracts the Bearer token from the Authorization header and compares against `settings.app_api_key`; mismatch → HTTP 401 `{"detail": "Invalid API key"}`. `GET /health` and `GET /playground` do not require authentication; all `/v1/` API endpoints do.

## request_logs schema
- source: docs/system-architecture.md
- type: schema
- content: SQLite table `request_logs`: id, provider, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, ttft_ms, cost_usd, credits_used, status, error_message, created_at. Indexes on created_at, model, provider. WAL mode for concurrent reads. `credits_used` added to pre-existing databases via idempotent `ALTER TABLE` migration.

## Analytics endpoints contracts
- source: docs/system-architecture.md
- type: api-contract
- content: `GET /v1/analytics/summary?since=ISO8601` → `{total_requests, total_tokens, total_cost_usd, avg_latency_ms, avg_ttft_ms, error_rate}`. `GET /v1/analytics/models?since=&provider=` → `{models: [{model, provider, request_count, tokens, cost, avg_latency, avg_ttft}]}`. `GET /v1/analytics/requests?since=&limit=50&offset=0` → `{requests: [...], total, limit, offset}`. `GET /v1/analytics/credits` → credits shape per zai-coding spec. All auth-required.

## Configuration layer
- source: docs/system-architecture.md
- type: schema
- content: `.env` → pydantic BaseSettings → `settings` singleton. Provider keys: `MANIFEST_API_KEY`, `ZAI_CODING_API_KEY`. Credit quotas: `ZAI_CREDITS_5H` (28000), `ZAI_CREDITS_WEEK` (140000). Legacy: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL` (still supported). Fallback: `LLM_API_KEY`. Gateway auth: `APP_API_KEY` (required). Analytics: `ANALYTICS_DB_PATH` (default `data/analytics.db`). CORS/limits: `CORS_ORIGINS`, `RATE_LIMIT`. `get_api_key(provider)` returns the dedicated key with `LLM_API_KEY` fallback.

## Lifespan and analytics write path
- source: docs/system-architecture.md
- type: protocol
- content: FastAPI `lifespan()` on startup: mkdir analytics DB parent dir, `AnalyticsDB.initialize()` (tables + WAL), store in `app.state.analytics_db`; on shutdown: `AnalyticsDB.close()`. `_tracked_stream()` measures latency/TTFT, collects final-chunk usage, computes `cost_usd = calculate_cost(...)` (always 0.0 — Manifest handles billing internally) and `credits_used = estimate_credits(provider, model, usage, now)`, logs via fire-and-forget `asyncio.create_task(db.log_request(...))` that never blocks the response stream.

## Playground contract
- source: docs/system-architecture.md
- type: protocol
- content: `GET /playground` serves `static/playground/index.html` via FileResponse — no auth required to load the page (API key entered client-side and sent as Bearer). Static HTML + vanilla JS, no build step; CDN deps marked.js, highlight.js, DOMPurify; `/static` StaticFiles mount serves `static/`. Features: model selector from `GET /v1/models`, SSE streaming chat with markdown rendering, generation params (temperature, max_tokens, top_p), conversation persistence via browser localStorage.

## Repo engineering conventions
- source: docs/superpowers/plans/2026-09-07-zai-coding-plan-support.md
- type: nfr
- content: Python 3.12+ floor (`typing.NotRequired` allowed; no 3.13-only syntax). No new dependencies — reuse installed `openai`, `aiosqlite`, `pytest`, `httpx`. Naming: snake_case functions/modules, PascalCase classes, UPPER_SNAKE constants; PEP 604 unions (`str | None`), builtin generics, TypedDict for payloads. Every async test carries `@pytest.mark.asyncio` (repo convention even with asyncio_mode=auto). Mocking via `unittest.mock.patch("routes.chat.create_provider", ...)` — no `app.dependency_overrides`. One-line module docstring on every new/changed file. Client-facing errors must not leak internal exception text. Single shared `settings` singleton from `config.py` — never construct a second one in app code. Commits after every green task.
