# System Architecture

## High-Level Architecture

```
+--------+        HTTP/SSE         +--------------+
| Client | <---------------------> | LLM Gateway  |
| (curl, |  POST /v1/chat/         | (FastAPI)    |
|  app)  |  completions            |              |
+--------+  GET  /v1/models        | config.py    |
            GET  /v1/analytics/*   | main.py      |
                                  +------+-------+
                                         |
                          resolve_provider(model_name)
                                         |
           +-------+--------+-------+----+---+--------+--------+
           |       |        |       |    |   |        |        |
           v       v        v       v    v   v        v        v
       +------+ +------+ +-----+ +----+ +--+--+ +------+ +--------+
       |OpenAI| |Deep  | |Moon | |Gem | |GLM  | |Mini  | |Byte   |
       |      | |Seek  | |shot | |ini | |     | |Max   | |Dance  |
       +------+ +------+ +-----+ +----+ +--+--+ +------+ +--------+
           |       |        |      |        |        |        |
           v       v        v      v        v        v        v
       OpenAI  DeepSeek  Moonshot Google  Z.AI     MiniMax  Volcengine
       API     API       API      AI API  API      API      API
```

## Request Flow

```
1. Client sends POST /v1/chat/completions
   with Authorization: Bearer <token>
   and JSON body {model, messages, system_prompt, stream}

2. FastAPI middleware
   +-- CORS middleware (allow all)
   +-- Lifespan: init analytics DB, store in app.state
   +-- Route to chat endpoint

3. verify_auth() dependency
   +-- Extracts token from Authorization header
   +-- Compares against settings.app_api_key
   +-- Rejects with 401 if mismatch

4. Endpoint handler
   +-- resolve_provider(request.model) -> (provider_name, model_id)
   +-- create_provider(provider_name, model_id) -> LLMProvider instance
   +-- Returns StreamingResponse with _tracked_stream() generator

5. _tracked_stream() generator
   +-- Records start time
   +-- Calls provider.chat_stream(messages, system_prompt)
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
  |
  +-- GeminiProvider
  |     Uses google-genai native SDK
  |     Role mapping: user->user, assistant->model, system->user
  |
  +-- OpenAICompatibleProvider (shared base)
        Uses openai.AsyncOpenAI client
        Subclasses set: base_url, default_model
        +-- OpenAIProvider    (api.openai.com)
        +-- DeepSeekProvider  (api.deepseek.com)
        +-- MoonshotProvider  (api.moonshot.cn)
        +-- ByteDanceProvider (ark.cn-beijing.volces.com)
        +-- GLMProvider       (api.z.ai)
        +-- MiniMaxProvider   (api.minimax.chat)
```

### Model Routing

```python
MODEL_ROUTING = {
    "gpt-4o":            ("openai",   "gpt-4o"),
    "gpt-4o-mini":       ("openai",   "gpt-4o-mini"),
    "o3":                ("openai",   "o3"),
    "deepseek-chat":     ("deepseek", "deepseek-chat"),
    "deepseek-reasoner": ("deepseek", "deepseek-reasoner"),
    "kimi-k2.5":         ("moonshot", "kimi-k2.5"),
    "gemini-2.5-flash":  ("gemini",   "gemini-2.5-flash"),
    "glm-5.1":           ("glm",      "glm-5.1"),
    "glm-4.7-flash":     ("glm",      "glm-4.7-flash"),
    "MiniMax-Text-01":   ("minimax",  "MiniMax-Text-01"),
    "doubao-pro-32k":    ("bytedance","doubao-pro-32k"),
    ...
}

def resolve_provider(model) -> (provider_name, model_id)
```

Client specifies `model` in the request body. Gateway resolves to provider via routing table. No per-request env var needed.

### Factory Dispatch

```python
def create_provider(provider_name, model, api_key) -> LLMProvider:
    key = api_key or settings.get_api_key(provider_name)
    match provider_name:
        "openai"   -> OpenAIProvider(api_key=key, model=model)
        "deepseek" -> DeepSeekProvider(...)
        "moonshot" -> MoonshotProvider(...)
        "gemini"   -> GeminiProvider(...)
        "glm"      -> GLMProvider(...)
        "minimax"  -> MiniMaxProvider(...)
        "bytedance"-> ByteDanceProvider(...)
```

Lazy imports inside match cases avoid loading unused SDKs. API keys resolved per-provider with `llm_api_key` fallback.

### Data Flow: Message Transformation

```
OpenAI format (input)
  {"role": "user", "content": "Hello"}

  +---------------+------------------------------------------+
  | Gemini        | Convert to types.Content                 |
  |               | role="user", parts=[Part.from_text()]    |
  |               | system_prompt -> GenerateContentConfig    |
  +---------------+------------------------------------------+
  | OpenAI-compat | Pass through as-is (already compatible)  |
  | (all others)  | Prepend system_prompt as system message  |
  +---------------+------------------------------------------+
```

### Usage Data Flow

```
Provider SDK
  |
  +-- OpenAI-compatible: final chunk has chunk.usage
  +-- Gemini: final chunk has usage_metadata attribute
  |
  v
StreamChunk = (token_str, UsageData | None)
  |
  v
_tracked_stream() collects UsageData on final chunk
  |
  v
calculate_cost(model, prompt_tokens, completion_tokens)
  |
  v
AnalyticsDB.log_request() -- fire-and-forget
```

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

Note: `GET /health` does not require authentication. All other endpoints require auth.

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
    Per-provider  Legacy   Gateway   Analytics   Base URL
    API keys     fallback  auth      DB path     override
    |            |         |         |           |
    openai_api_key  llm_api_key  app_api_key  analytics_db_path  llm_base_url
    deepseek_api_key
    moonshot_api_key
    bytedance_api_key
    glm_api_key
```

`get_api_key(provider)` returns provider-specific key, falls back to `llm_api_key`.

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
