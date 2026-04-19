# Codebase Summary

~900 LOC across ~16 Python files + 3 static files.

## File Breakdown

### `config.py` (36 LOC)

Settings module using `pydantic_settings.BaseSettings`. Reads from `.env`.

**Settings fields:**

| Field | Type | Default | Source |
|-------|------|---------|--------|
| `llm_provider` | `str` | `gemini` | `LLM_PROVIDER` |
| `llm_api_key` | `str` | `""` | `LLM_API_KEY` |
| `llm_model` | `str` | `gemini-2.0-flash-lite` | `LLM_MODEL` |
| `llm_base_url` | `str \| None` | `None` | `LLM_BASE_URL` |
| `manifest_api_key` | `str` | `""` | `MANIFEST_API_KEY` |
| `app_api_key` | `str` | `""` | `APP_API_KEY` |
| `cors_origins` | `str` | `""` | `CORS_ORIGINS` |
| `rate_limit` | `str` | `60/minute` | `RATE_LIMIT` |
| `analytics_db_path` | `str` | `data/analytics.db` | `ANALYTICS_DB_PATH` |

Method `get_api_key(provider)` returns `manifest_api_key` for Manifest, `llm_api_key` fallback for others.

Singleton: `settings = Settings()`.

### `main.py` (72 LOC)

FastAPI app entry with `lifespan` context manager for analytics DB init/shutdown.

- `lifespan()` -- creates `AnalyticsDB` on startup, stores in `app.state.analytics_db`, closes on shutdown
- Mounts `routes/chat.router` and `routes/analytics.router` + `analytics_router`
- `GET /health` -- returns `{"status": "ok"}`
- `GET /playground` -- serves `static/playground/index.html` via `FileResponse` (no auth required)
- `StaticFiles` mount at `/static` serving `static/` directory
- CORS middleware (configurable via `CORS_ORIGINS` setting)

### `routes/chat.py` (133 LOC)

Chat completions endpoint with analytics tracking.

- `ChatRequest` model: `model` (default `"auto"`), `messages`, `system_prompt`, `stream`, `temperature`, `max_tokens`, `top_p`
- `verify_auth()` -- Bearer token dependency
- `POST /v1/chat/completions` -- resolves model to provider via `resolve_provider()`, builds `GenParams` from optional generation fields, creates provider, returns `StreamingResponse`
- `_tracked_stream()` -- wraps `provider.chat_stream()`, tracks TTFT/latency/usage, logs to analytics DB
- SSE format: `data: {"token": "..."}\n\n` per chunk, `data: [DONE]\n\n` at end

### `routes/analytics.py` (62 LOC)

Analytics REST endpoints + model listing.

- `GET /v1/models` -- lists all models from `MODEL_ROUTING` in OpenAI-compatible format
- `GET /v1/analytics/summary` -- aggregate stats (total requests, tokens, cost, latency, error rate)
- `GET /v1/analytics/models` -- per-model stats grouped by model + provider
- `GET /v1/analytics/requests` -- paginated recent requests (limit/offset)
- All endpoints require auth via `verify_auth` dependency

### `analytics/routing.py` (57 LOC)

Model routing table. Maps model name to `("manifest", actual_model_id)`. All routes go through Manifest.

`MODEL_ROUTING` dict contains 27 entries, all mapping to `("manifest", <model_id>)`:
- Auto: auto (smart routing)
- OpenAI: gpt-5.4, gpt-4o, gpt-4o-mini, o3
- Anthropic: claude-sonnet, claude-haiku
- DeepSeek: deepseek-chat, deepseek-reasoner
- MoonshotAI: kimi-k2.5, kimi-k2-thinking, moonshot-v1-128k
- Google: gemini-2.5-flash, gemini-2.0-flash, gemini-2.0-flash-lite
- Z.AI (GLM): glm-5.1, glm-5-turbo, glm-5, glm-4.7, glm-4.7-flash, glm-4.7-flashx, glm-4.6, glm-4.5, glm-4.5-flash
- MiniMax: MiniMax-Text-01
- ByteDance: doubao-pro-32k, doubao-pro-128k

`resolve_provider(model)` returns routing table entry, or `("manifest", model)` for unknown models (passthrough).

### `analytics/cost.py` (6 LOC)

`calculate_cost(model, prompt_tokens, completion_tokens)` always returns `0.0`. Manifest handles billing internally; cost tracking at the gateway level is not applicable.

### `analytics/db.py` (196 LOC)

SQLite-backed async storage via `aiosqlite`.

`AnalyticsDB` class:
- `initialize()` -- creates `request_logs` table with indexes, enables WAL mode
- `log_request(record)` -- insert request log
- `get_summary(since)` -- aggregate stats with optional date filter
- `get_model_stats(since, provider)` -- per-model grouping
- `get_recent(limit, offset, since)` -- paginated request listing

Table schema: `request_logs` (id, provider, model, prompt/completion/total tokens, latency_ms, ttft_ms, cost_usd, status, error_message, created_at).

### `providers/__init__.py` (12 LOC)

Factory `create_provider(provider_name, model, api_key)`. All requests route through Manifest.

Returns `ManifestProvider(api_key=key, model=model)` regardless of `provider_name`.

API key resolved via `settings.get_api_key("manifest")` if not passed explicitly.

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

### Deleted provider files

The following provider files were removed (replaced by `manifest.py`):
- `providers/gemini.py` (native `google-genai` SDK)
- `providers/openai_provider.py`
- `providers/deepseek.py`
- `providers/moonshot.py`
- `providers/bytedance.py`
- `providers/glm.py`
- `providers/minimax.py`

### `tests/` (6 test files + conftest)

- `conftest.py` -- shared fixtures (test client with auth override)
- `test_chat_endpoint.py` -- chat route tests
- `test_analytics_endpoints.py` -- analytics route tests
- `test_analytics_db.py` -- AnalyticsDB unit tests
- `test_cost.py` -- cost calculation tests
- `test_routing.py` -- routing resolution tests
- `test_playground.py` -- playground route and static file serving tests

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
Client sends `model` field in request. `resolve_provider()` maps it to `("manifest", model_id)` via `MODEL_ROUTING` dict. Unknown models pass through to Manifest as-is. `model="auto"` enables Manifest smart routing.

### Generation Params
Optional `temperature`, `max_tokens`, `top_p` fields in `ChatRequest`. Built into `GenParams` TypedDict and forwarded to Manifest. All params passed directly (OpenAI-compatible).

### Provider Inheritance Hierarchy
```
LLMProvider (ABC)
  +-- OpenAICompatibleProvider (shared base)
        +-- ManifestProvider (app.manifest.build/v1)
```

### Tracked Streaming
`_tracked_stream()` wraps provider output: measures TTFT/latency, extracts usage data, calculates cost, logs to SQLite. Analytics logging is fire-and-forget via `asyncio.create_task`.

### Lifespan Pattern
FastAPI `lifespan` context manager initializes SQLite DB on startup, closes on shutdown. DB accessible via `request.app.state.analytics_db`.

## Related Docs

- [Code Standards](./code-standards.md)
- [System Architecture](./system-architecture.md)
- [Project Overview & PDR](./project-overview-pdr.md)
