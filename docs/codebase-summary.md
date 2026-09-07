# Codebase Summary

~1,800 LOC across ~24 Python files (incl. tests) + 3 static files.

## File Breakdown

### `config.py` (41 LOC)

Settings module using `pydantic_settings.BaseSettings`. Reads from `.env`.

**Settings fields:**

| Field | Type | Default | Source |
|-------|------|---------|--------|
| `llm_provider` | `str` | `gemini` | `LLM_PROVIDER` |
| `llm_api_key` | `str` | `""` | `LLM_API_KEY` |
| `llm_model` | `str` | `gemini-2.0-flash-lite` | `LLM_MODEL` |
| `llm_base_url` | `str \| None` | `None` | `LLM_BASE_URL` |
| `manifest_api_key` | `str` | `""` | `MANIFEST_API_KEY` |
| `zai_coding_api_key` | `str` | `""` | `ZAI_CODING_API_KEY` |
| `zai_credits_5h` | `int` | `28000` | `ZAI_CREDITS_5H` |
| `zai_credits_week` | `int` | `140000` | `ZAI_CREDITS_WEEK` |
| `app_api_key` | `str` | `""` | `APP_API_KEY` |
| `cors_origins` | `str` | `""` | `CORS_ORIGINS` |
| `rate_limit` | `str` | `60/minute` | `RATE_LIMIT` |
| `analytics_db_path` | `str` | `data/analytics.db` | `ANALYTICS_DB_PATH` |

Method `get_api_key(provider)` returns `manifest_api_key` / `zai_coding_api_key` for those providers, `llm_api_key` fallback for each and for others.

Singleton: `settings = Settings()`.

### `main.py` (72 LOC)

FastAPI app entry with `lifespan` context manager for analytics DB init/shutdown.

- `lifespan()` -- creates `AnalyticsDB` on startup, stores in `app.state.analytics_db`, closes on shutdown
- Mounts `routes/chat.router` and `routes/analytics.router` + `analytics_router`
- `GET /health` -- returns `{"status": "ok"}`
- `GET /playground` -- serves `static/playground/index.html` via `FileResponse` (no auth required)
- `StaticFiles` mount at `/static` serving `static/` directory
- CORS middleware (configurable via `CORS_ORIGINS` setting)

### `routes/chat.py` (143 LOC)

Chat completions endpoint with analytics tracking.

- `ChatRequest` model: `model` (default `"auto"`), `messages`, `system_prompt`, `stream`, `temperature`, `max_tokens`, `top_p`
- `verify_auth()` -- Bearer token dependency
- `POST /v1/chat/completions` -- resolves model to provider via `resolve_provider()`, builds `GenParams` from optional generation fields, creates provider, returns `StreamingResponse`
- `_tracked_stream()` -- wraps `provider.chat_stream()`, tracks TTFT/latency/usage, estimates credits via `estimate_credits()` for `zai-coding`, logs to analytics DB; zai-coding stream errors are mapped to friendly SSE messages (quota: "zai-coding quota exhausted — resets within the 5-hour window"; auth: "zai-coding authentication failed") instead of the generic internal-error frame

### `routes/analytics.py` (87 LOC)

Analytics REST endpoints + model listing.

- `GET /v1/models` -- lists all models from `MODEL_ROUTING` in OpenAI-compatible format
- `GET /v1/analytics/summary` -- aggregate stats (total requests, tokens, cost, latency, error rate)
- `GET /v1/analytics/models` -- per-model stats grouped by model + provider
- `GET /v1/analytics/requests` -- paginated recent requests (limit/offset)
- `GET /v1/analytics/credits` -- estimated z.ai coding-plan credit burn (rolling 5h/7d) vs `ZAI_CREDITS_5H`/`ZAI_CREDITS_WEEK` quotas, per-model breakdown, off-peak share
- All endpoints require auth via `verify_auth` dependency

### `analytics/routing.py` (81 LOC)

Maps model names to `(provider, actual_model_id)`. Non-GLM routes go through Manifest; GLM routes go to the z.ai coding endpoint when an effective key (`ZAI_CODING_API_KEY` or `LLM_API_KEY` fallback) is set, otherwise they degrade to Manifest.

`MODEL_ROUTING` dict contains 27 entries:
- Auto: auto (smart routing) -- Manifest
- OpenAI/Anthropic/DeepSeek/MoonshotAI/Google/MiniMax/ByteDance aliases -- all `("manifest", <model_id>)`
- Z.AI GLM: canonical `glm-5.3` and `glm-5.3-flash` plus 9 aliases (e.g. `glm-5.1`, `glm-5-turbo`, `glm-4.7`, `glm-4.7-flash`) canonicalized to one of the two canonical ids -- `("zai-coding", <canonical_id>)`

`resolve_provider(model)` returns the routing entry, except `zai-coding` entries are downgraded to `("manifest", model_id)` when no effective key is set. Unknown `glm-*` names go to `("zai-coding", model)` under the same key gate; all other unknown models pass through as `("manifest", model)`.

### `analytics/cost.py` (42 LOC)

`calculate_cost(model, prompt_tokens, completion_tokens)` always returns `0.0`. Manifest handles billing internally; cost tracking at the gateway level is not applicable.

`is_peak(ts)` -- True during z.ai peak: Mon-Fri 14:00-18:00 UTC+8.

`estimate_credits(provider, model, usage, ts)` -- per-request GLM Coding Plan credit estimate for `zai-coding` (`0.0` otherwise): `(fresh_input*input + cached*cached + output*output) / 10_000` using multipliers glm-5.3 = 6.9/1.7/24.0, glm-5.3-flash = 2.3/0.56/8.0; halved off-peak. `cached_tokens` comes from `UsageData`.

### `analytics/db.py` (247 LOC)

SQLite-backed async storage via `aiosqlite`.

`AnalyticsDB` class:
- `initialize()` -- creates `request_logs` table with indexes, enables WAL mode
- `log_request(record)` -- insert request log
- `get_summary(since)` -- aggregate stats with optional date filter
- `get_model_stats(since, provider)` -- per-model grouping
- `get_recent(limit, offset, since)` -- paginated request listing
- `get_credits_summary()` -- rolling 5h/7d zai-coding credit totals, per-model breakdown, off-peak request share

Table schema: `request_logs` (id, provider, model, prompt/completion/total tokens, latency_ms, ttft_ms, cost_usd, credits_used, status, error_message, created_at). `credits_used` is added to pre-existing databases via idempotent `ALTER TABLE` migration.

### `providers/__init__.py` (15 LOC)

Factory `create_provider(provider_name, model, api_key)`. Dispatches by name: `"zai-coding"` builds `ZAICodingProvider`, everything else `ManifestProvider`.

API key resolved via `settings.get_api_key(provider_name)` if not passed explicitly.

### `providers/base.py` (27 LOC)

Abstract base `LLMProvider(ABC)` with `UsageData` TypedDict, `GenParams` TypedDict (total=False), and `StreamChunk` type alias.

`chat_stream(messages, system_prompt, params: GenParams | None)` yields `(token_str, UsageData | None)` tuples. Usage populated on final chunk, None for text chunks.

### `providers/openai_compatible_base.py` (63 LOC)

Shared base `OpenAICompatibleProvider(LLMProvider)` for OpenAI-protocol providers.

Subclasses set `base_url` and `default_model` class attrs. Constructor takes `api_key` and optional `model`.

Uses `AsyncOpenAI` with `stream_options={"include_usage": True}` to get token counts from final chunk. Wires `temperature`, `max_tokens`, `top_p` from `GenParams` into API call kwargs.

### `providers/manifest.py` (11 LOC)

`ManifestProvider(OpenAICompatibleProvider)` -- base_url `https://app.manifest.build/v1`, default model `"auto"`.

Single provider connecting to Manifest for smart routing across 500+ models.

### `providers/zai_coding.py` (10 LOC)

`ZAICodingProvider(OpenAICompatibleProvider)` -- base_url `https://api.z.ai/api/coding/paas/v4`, default model `"glm-5.3"`. Serves the z.ai GLM Coding Plan; serves `glm-5.3` / `glm-5.3-flash` on plan quota.

### Deleted provider files

The following provider files were removed (replaced by `manifest.py`):
- `providers/gemini.py` (native `google-genai` SDK)
- `providers/openai_provider.py`
- `providers/deepseek.py`
- `providers/moonshot.py`
- `providers/bytedance.py`
- `providers/glm.py`
- `providers/minimax.py`

### `tests/` (9 test files + conftest)

- `conftest.py` -- shared fixtures (test client with auth override)
- `test_chat_endpoint.py` -- chat route tests
- `test_analytics_endpoints.py` -- analytics route tests
- `test_analytics_db.py` -- AnalyticsDB unit tests
- `test_cost.py` -- cost calculation tests
- `test_routing.py` -- routing resolution tests
- `test_playground.py` -- playground route and static file serving tests
- `test_config.py` -- Settings and `get_api_key` fallback tests
- `test_providers.py` -- factory dispatch tests
- `test_openai_compatible_base.py` -- shared OpenAI-wire base tests

## Supporting Files

| File | Purpose |
|------|---------|
| `requirements.txt` | 10 deps: fastapi, uvicorn, pydantic-settings, openai, python-dotenv, aiosqlite, pytest, pytest-asyncio, httpx, slowapi |
| `.env.example` | Template with MANIFEST_API_KEY, APP_API_KEY, and optional config |
| `Makefile` | Task automation: install, start, dev, stop, health, test, test-unit, test-integration, clean |
| `static/playground/index.html` | Web playground HTML — chat UI with login overlay, model selector, settings panel |
| `static/playground/playground.css` | Playground styles |
| `static/playground/playground.js` | Playground logic — SSE streaming, API auth, localStorage persistence, markdown rendering |
| `rate_limiter.py` | SlowAPI-based rate limiting configuration |

## Key Patterns

### Model-Based Routing
Client sends `model` field in request. `resolve_provider()` maps it to `(provider, model_id)` via `MODEL_ROUTING` dict: non-GLM → Manifest, `glm-*` → zai-coding (key-gated; degrades to Manifest without a key). Unknown non-GLM names pass through to Manifest as-is. `model="auto"` enables Manifest smart routing.

### Generation Params
Optional `temperature`, `max_tokens`, `top_p` fields in `ChatRequest`. Built into `GenParams` TypedDict and forwarded to Manifest. All params passed directly (OpenAI-compatible).

### Provider Inheritance Hierarchy
```
LLMProvider (ABC)
  +-- OpenAICompatibleProvider (shared base)
        +-- ManifestProvider (app.manifest.build/v1)
        +-- ZAICodingProvider (api.z.ai/api/coding/paas/v4)
```

### Tracked Streaming
`_tracked_stream()` wraps provider output: measures TTFT/latency, extracts usage data, calculates cost, logs to SQLite. Analytics logging is fire-and-forget via `asyncio.create_task`.

### Lifespan Pattern
FastAPI `lifespan` context manager initializes SQLite DB on startup, closes on shutdown. DB accessible via `request.app.state.analytics_db`.

## Related Docs

- [Code Standards](./code-standards.md)
- [System Architecture](./system-architecture.md)
- [Project Overview & PDR](./project-overview-pdr.md)
