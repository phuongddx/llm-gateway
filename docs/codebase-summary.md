# Codebase Summary

~1200 LOC across ~24 Python files.

## File Breakdown

### `config.py` (36 LOC)

Settings module using `pydantic_settings.BaseSettings`. Reads from `.env`.

**Settings fields:**

| Field | Type | Default | Source |
|-------|------|---------|--------|
| `llm_provider` | `str` | `gemini` | `LLM_PROVIDER` |
| `llm_api_key` | `str` | `""` | `LLM_API_KEY` |
| `llm_model` | `str` | `""` | `LLM_MODEL` |
| `llm_base_url` | `str \| None` | `None` | `LLM_BASE_URL` |
| `openai_api_key` | `str` | `""` | `OPENAI_API_KEY` |
| `deepseek_api_key` | `str` | `""` | `DEEPSEEK_API_KEY` |
| `moonshot_api_key` | `str` | `""` | `MOONSHOT_API_KEY` |
| `bytedance_api_key` | `str` | `""` | `BYTEDANCE_API_KEY` |
| `glm_api_key` | `str` | `""` | `GLM_API_KEY` |
| `app_api_key` | `str` | `changeme` | `APP_API_KEY` |
| `analytics_db_path` | `str` | `data/analytics.db` | `ANALYTICS_DB_PATH` |

Method `get_api_key(provider)` returns per-provider key with `llm_api_key` fallback.

Singleton: `settings = Settings()`.

### `main.py` (52 LOC)

FastAPI app entry with `lifespan` context manager for analytics DB init/shutdown.

- `lifespan()` -- creates `AnalyticsDB` on startup, stores in `app.state.analytics_db`, closes on shutdown
- Mounts `routes/chat.router` and `routes/analytics.router` + `analytics_router`
- `GET /health` -- returns `{"status": "ok"}`
- CORS middleware (allow all)

### `routes/chat.py` (116 LOC)

Chat completions endpoint with analytics tracking.

- `ChatRequest` model: `model` (required), `messages`, `system_prompt`, `stream`
- `verify_auth()` -- Bearer token dependency
- `POST /v1/chat/completions` -- resolves model to provider via `resolve_provider()`, creates provider, returns `StreamingResponse`
- `_tracked_stream()` -- wraps `provider.chat_stream()`, tracks TTFT/latency/usage, logs to analytics DB
- SSE format: `data: {"token": "..."}\n\n` per chunk, `data: [DONE]\n\n` at end

### `routes/analytics.py` (62 LOC)

Analytics REST endpoints + model listing.

- `GET /v1/models` -- lists all models from `MODEL_ROUTING` in OpenAI-compatible format
- `GET /v1/analytics/summary` -- aggregate stats (total requests, tokens, cost, latency, error rate)
- `GET /v1/analytics/models` -- per-model stats grouped by model + provider
- `GET /v1/analytics/requests` -- paginated recent requests (limit/offset)
- All endpoints require auth via `verify_auth` dependency

### `analytics/routing.py` (49 LOC)

Model routing table. Maps model name to `(provider_name, actual_model_id)`.

`MODEL_ROUTING` dict contains 21 entries across 7 providers:
- OpenAI: gpt-4o, gpt-4o-mini, o3
- DeepSeek: deepseek-chat, deepseek-reasoner
- MoonshotAI: kimi-k2.5, kimi-k2-thinking, moonshot-v1-128k
- Gemini: gemini-2.5-flash
- Z.AI (GLM): glm-5.1, glm-5-turbo, glm-5, glm-4.7, glm-4.7-flash, glm-4.7-flashx, glm-4.6, glm-4.5, glm-4.5-flash
- MiniMax: MiniMax-Text-01
- ByteDance: doubao-pro-32k, doubao-pro-128k

`resolve_provider(model)` raises `ValueError` with available models list if unknown.

### `analytics/cost.py` (33 LOC)

`MODEL_PRICING` dict maps model name to `(input_per_1m, output_per_1m)` USD pricing.

`calculate_cost(model, prompt_tokens, completion_tokens)` returns USD cost or 0.0 for unknown models.

### `analytics/db.py` (196 LOC)

SQLite-backed async storage via `aiosqlite`.

`AnalyticsDB` class:
- `initialize()` -- creates `request_logs` table with indexes, enables WAL mode
- `log_request(record)` -- insert request log
- `get_summary(since)` -- aggregate stats with optional date filter
- `get_model_stats(since, provider)` -- per-model grouping
- `get_recent(limit, offset, since)` -- paginated request listing

Table schema: `request_logs` (id, provider, model, prompt/completion/total tokens, latency_ms, ttft_ms, cost_usd, status, error_message, created_at).

### `providers/__init__.py` (33 LOC)

Factory `create_provider(provider_name, model, api_key)` with lazy imports.

Supports 7 providers: `gemini`, `glm`, `minimax`, `openai`, `deepseek`, `moonshot`, `bytedance`.

API key resolved via `settings.get_api_key(provider_name)` if not passed explicitly.

### `providers/base.py` (25 LOC)

Abstract base `LLMProvider(ABC)` with `UsageData` TypedDict and `StreamChunk` type alias.

`chat_stream()` yields `(token_str, UsageData | None)` tuples. Usage populated on final chunk, None for text chunks.

### `providers/openai_compatible_base.py` (54 LOC)

Shared base `OpenAICompatibleProvider(LLMProvider)` for OpenAI-protocol providers.

Subclasses set `base_url` and `default_model` class attrs. Constructor takes `api_key` and optional `model`.

Uses `AsyncOpenAI` with `stream_options={"include_usage": True}` to get token counts from final chunk.

### `providers/gemini.py` (65 LOC)

`GeminiProvider(LLMProvider)` using native `google-genai` SDK.

- Role mapping: `{"user": "user", "assistant": "model", "system": "user"}`
- System prompt via `GenerateContentConfig(system_instruction=...)`
- Extracts `usage_metadata` from final chunk for token counts
- `_to_contents()` converts OpenAI messages to Gemini `types.Content`

### `providers/openai_provider.py` (8 LOC)

`OpenAIProvider(OpenAICompatibleProvider)` -- base_url `api.openai.com/v1`, default `gpt-4o`.

### `providers/deepseek.py` (8 LOC)

`DeepSeekProvider(OpenAICompatibleProvider)` -- base_url `api.deepseek.com`, default `deepseek-chat`.

### `providers/moonshot.py` (8 LOC)

`MoonshotProvider(OpenAICompatibleProvider)` -- base_url `api.moonshot.cn/v1`, default `kimi-k2.5`.

### `providers/bytedance.py` (8 LOC)

`ByteDanceProvider(OpenAICompatibleProvider)` -- base_url `ark.cn-beijing.volces.com/api/v3`, no default model (requires endpoint ID).

### `providers/glm.py` (8 LOC)

`GLMProvider(OpenAICompatibleProvider)` -- base_url `api.z.ai/api/paas/v4`, default `glm-4.7-flash`.

### `providers/minimax.py` (8 LOC)

`MiniMaxProvider(OpenAICompatibleProvider)` -- base_url `api.minimax.chat/v1`, default `MiniMax-Text-01`.

### `tests/` (4 test files + conftest)

- `conftest.py` -- shared fixtures (test client with auth override)
- `test_chat_endpoint.py` -- chat route tests
- `test_analytics_endpoints.py` -- analytics route tests
- `test_analytics_db.py` -- AnalyticsDB unit tests
- `test_cost.py` -- cost calculation tests
- `test_routing.py` -- routing resolution tests

## Supporting Files

| File | Purpose |
|------|---------|
| `requirements.txt` | 10 deps: fastapi, uvicorn, pydantic-settings, google-genai, openai, python-dotenv, aiosqlite, pytest, pytest-asyncio, httpx |
| `.env.example` | Template with all config vars and defaults |
| `Makefile` | Task automation: install, start, dev, stop, health, test, test-unit, test-integration, clean |

## Key Patterns

### Model-Based Routing
Client sends `model` field in request. `resolve_provider()` maps it to `(provider, model_id)` via `MODEL_ROUTING` dict. Factory creates the correct provider instance. No `LLM_PROVIDER` env var needed per request.

### Provider Inheritance Hierarchy
```
LLMProvider (ABC)
  +-- GeminiProvider (native SDK)
  +-- OpenAICompatibleProvider (shared base)
        +-- OpenAIProvider
        +-- DeepSeekProvider
        +-- MoonshotProvider
        +-- ByteDanceProvider
        +-- GLMProvider
        +-- MiniMaxProvider
```

### Tracked Streaming
`_tracked_stream()` wraps provider output: measures TTFT/latency, extracts usage data, calculates cost, logs to SQLite. Analytics logging is fire-and-forget via `asyncio.create_task`.

### Lifespan Pattern
FastAPI `lifespan` context manager initializes SQLite DB on startup, closes on shutdown. DB accessible via `request.app.state.analytics_db`.

## Related Docs

- [Code Standards](./code-standards.md)
- [System Architecture](./system-architecture.md)
- [Project Overview & PDR](./project-overview-pdr.md)
