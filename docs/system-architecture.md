# System Architecture

## High-Level Architecture

```
+--------+        HTTP/SSE         +--------------+
| Client | <---------------------> | LLM Gateway  |
| (curl, |  POST /v1/chat/         | (FastAPI)    |
|  app,  |  completions            |              |
|  web)  |  GET  /v1/models        | config.py    |
+--------+  GET  /v1/analytics/*   | main.py      |
            GET  /playground       | static/      |
                                  +------+-------+
                                         |
                          resolve_provider(model_name)
                                         |
                                         v
                                  +--------------+
                                  | Manifest     |
                                  | Provider     |
                                  | (OpenAI-compat)
                                  +------+-------+
                                         |
                                         v
                                  app.manifest.build
                                  (500+ models: OpenAI,
                                   Anthropic, Google,
                                   DeepSeek, Moonshot,
                                   GLM, MiniMax, etc.)
```

## Request Flow

```
1. Client sends POST /v1/chat/completions
   with Authorization: Bearer <token>
   and JSON body {model, messages, system_prompt, stream,
                   temperature?, max_tokens?, top_p?}

2. FastAPI middleware
   +-- CORS middleware (allow all)
   +-- Lifespan: init analytics DB, store in app.state
   +-- Route to chat endpoint

3. verify_auth() dependency
   +-- Extracts token from Authorization header
   +-- Compares against settings.app_api_key
   +-- Rejects with 401 if mismatch

4. Endpoint handler
   +-- resolve_provider(request.model) -> ("manifest", model_id)
   +-- create_provider("manifest", model_id) -> ManifestProvider instance
   +-- Builds GenParams dict from temperature/max_tokens/top_p if present
   +-- Returns StreamingResponse with _tracked_stream() generator

5. _tracked_stream() generator
   +-- Records start time
   +-- Calls provider.chat_stream(messages, system_prompt, gen_params)
   +-- Yields "data: {"token": "..."}\n\n" for each text chunk
   +-- Tracks first-token time (TTFT)
   +-- Collects usage data from final chunk
   +-- On error: yields "data: {"error": "..."}\n\n"
   +-- Logs request to analytics DB (fire-and-forget)
   +-- Final: yields "data: [DONE]\n\n"
```

## Provider Abstraction

### Inheritance Hierarchy

```
LLMProvider (ABC)
  |  chat_stream() -> AsyncGenerator[StreamChunk, None]
  |  StreamChunk = (str, UsageData | None)
  |  GenParams: {temperature?, max_tokens?, top_p?}  (TypedDict, total=False)
  |
  +-- OpenAICompatibleProvider (shared base)
  |     Uses openai.AsyncOpenAI client
  |     base_url and default_model as class attrs
  |
  +-- ManifestProvider
        base_url = "https://app.manifest.build/v1"
        default_model = "auto"
        Smart routing to 500+ models
```

### Model Routing

```python
MODEL_ROUTING = {
    "auto":              ("manifest", "auto"),
    "gpt-5.4":           ("manifest", "gpt-5.4"),
    "gpt-4o":            ("manifest", "gpt-4o"),
    "claude-sonnet":     ("manifest", "claude-sonnet-4-6"),
    "gemini-2.5-flash":  ("manifest", "gemini-2.5-flash"),
    "deepseek-chat":     ("manifest", "deepseek-chat"),
    "glm-5.1":           ("manifest", "glm-5.1"),
    ...
}

def resolve_provider(model) -> (provider_name, model_id)
```

All routes point to `("manifest", <model_id>)`. Unknown model names pass through to Manifest as-is, giving access to the full 500+ model catalog. Use `model="auto"` for Manifest smart routing.

### Factory Dispatch

```python
def create_provider(provider_name, model, api_key) -> LLMProvider:
    key = api_key or settings.get_api_key(provider_name)
    # All requests route through Manifest
    from providers.manifest import ManifestProvider
    return ManifestProvider(api_key=key, model=model)
```

Single provider. API key resolved via `settings.get_api_key("manifest")` which returns `MANIFEST_API_KEY` with `LLM_API_KEY` fallback.

### Data Flow: Message Transformation

```
OpenAI format (input)
  {"role": "user", "content": "Hello"}

  +---------------+------------------------------------------+
  | Manifest      | Pass through as-is (OpenAI-compatible)   |
  | Provider      | Prepend system_prompt as system message  |
  +---------------+------------------------------------------+
```

### Usage Data Flow

```
Manifest Provider (OpenAI-compatible)
  |
  +-- final chunk has chunk.usage
  |
  v
StreamChunk = (token_str, UsageData | None)
  |
  v
_tracked_stream() collects UsageData on final chunk
  |
  v
calculate_cost(model, prompt_tokens, completion_tokens) -> always 0.0
  |
  v
AnalyticsDB.log_request() -- fire-and-forget
```

Cost always returns `0.0` because Manifest handles billing internally. Usage data (prompt/completion tokens) is still tracked for analytics.

## Web Playground

A built-in chat UI accessible at `GET /playground`. No auth required to load the page.

```
GET /playground
  -> Serves static/playground/index.html via FileResponse

/static/ mount
  -> FastAPI StaticFiles serving static/ directory
  -> playground.js, playground.css, and CDN dependencies loaded by index.html
```

### Features

- API key auth via login overlay (key entered client-side, sent as Bearer token)
- Model selector populated from `GET /v1/models`
- SSE streaming chat with markdown rendering (marked.js) and code highlighting (highlight.js)
- Generation params: temperature, max_tokens, top_p
- Conversation persistence via browser localStorage

### Tech Stack

Static HTML + vanilla JS (no build step). CDN dependencies: marked.js, highlight.js, DOMPurify. Served by FastAPI `StaticFiles` mount.

## Authentication Flow

```
Request Header: Authorization: Bearer <token>
                    |
                    v
            verify_auth() dependency
                    |
            token == settings.app_api_key?
            /                \
          Yes                No
           |                  |
    Continue to          HTTP 401
    endpoint handler     {"detail": "Invalid API key"}
```

Note: `GET /health` and `GET /playground` do not require authentication. All `/v1/` API endpoints require auth.

## Analytics Architecture

```
Request
  |
  v
_tracked_stream()
  |-- start_time = monotonic()
  |-- first_token_time tracked on first text chunk
  |-- usage_data collected from final StreamChunk
  |-- latency_ms = now - start_time
  |-- ttft_ms = first_token_time - start_time
  |-- cost_usd = calculate_cost(model, tokens)
  |
  v
asyncio.create_task(db.log_request({...}))  # fire-and-forget
  |
  v
SQLite (request_logs table)
  |-- Columns: id, provider, model, prompt_tokens, completion_tokens,
  |            total_tokens, latency_ms, ttft_ms, cost_usd,
  |            status, error_message, created_at
  |-- Indexes: created_at, model, provider
  |-- WAL mode for concurrent reads
```

### Analytics Endpoints

```
GET /v1/analytics/summary?since=ISO8601
  -> {total_requests, total_tokens, total_cost_usd, avg_latency_ms, avg_ttft_ms, error_rate}

GET /v1/analytics/models?since=&provider=
  -> {models: [{model, provider, request_count, tokens, cost, avg_latency, avg_ttft}]}

GET /v1/analytics/requests?since=&limit=50&offset=0
  -> {requests: [...], total, limit, offset}
```

## Configuration Layer

```
.env file --> pydantic BaseSettings --> settings singleton
                    |
           +--------+--------+----------+-----------+
           |        |        |          |           |
    Manifest API  Legacy   Gateway   Analytics   Base URL
    key          fallback  auth      DB path     override
    |            |         |         |           |
    manifest_api_key  llm_api_key  app_api_key  analytics_db_path  llm_base_url
```

`get_api_key("manifest")` returns `manifest_api_key` with `llm_api_key` fallback.

## Lifespan Management

```
FastAPI startup
  |
  v
lifespan() context manager
  |-- mkdir for analytics DB parent dir
  |-- AnalyticsDB.initialize() -> create tables + WAL mode
  |-- store in app.state.analytics_db
  |
  v (yield -- app runs)
  |
FastAPI shutdown
  |
  v
  |-- AnalyticsDB.close()
```

## Related Docs

- [Codebase Summary](./codebase-summary.md)
- [Code Standards](./code-standards.md)
- [Deployment Guide](./deployment-guide.md)
