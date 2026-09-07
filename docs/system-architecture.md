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
                          resolve_provider(model_name)
                                         |
                    glm-* & z.ai key set | everything else
                        +----------------+----------------+
                        v                                 v
              +------------------+              +------------------+
              | Z.AI Coding      |              | Manifest         |
              | Provider         |              | Provider         |
              | (OpenAI-compat)  |              | (OpenAI-compat)  |
              +--------+---------+              +--------+---------+
                       |                                 |
                       v                                 v
             api.z.ai/api/coding/paas/v4       app.manifest.build
             (glm-5.3, glm-5.3-flash)          (500+ models: OpenAI,
                                               Anthropic, Google,
                                               DeepSeek, Moonshot, etc.)
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
   +-- resolve_provider(request.model) -> (provider_name, model_id)
   |     (glm-* -> "zai-coding" when an effective z.ai key is set; else "manifest")
   +-- create_provider(provider_name, model_id) -> provider instance
   +-- Builds GenParams dict from temperature/max_tokens/top_p if present
   +-- Returns StreamingResponse with _tracked_stream() generator

5. _tracked_stream() generator
   +-- Records start time
   +-- Calls provider.chat_stream(messages, system_prompt, gen_params)
   +-- Yields "data: {"token": "..."}\n\n" for each text chunk
   +-- Tracks first-token time (TTFT)
   +-- Collects usage data from final chunk
   +-- On error: yields "data: {"error": "..."}\n\n"
   |     (zai-coding: quota -> "zai-coding quota exhausted — resets within
   |      the 5-hour window"; auth -> "zai-coding authentication failed")
   +-- Logs request to analytics DB (fire-and-forget, incl. credits_used)
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
  |     base_url = "https://app.manifest.build/v1"
  |     default_model = "auto"
  |     Smart routing to 500+ models
  |
  +-- ZAICodingProvider
        base_url = "https://api.z.ai/api/coding/paas/v4"
        default_model = "glm-5.3"
        GLM Coding Plan: glm-5.3 / glm-5.3-flash on plan quota
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
    "glm-5.1":           ("zai-coding", "glm-5.3"),  # aliases canonicalized
    ...
}

def resolve_provider(model) -> (provider_name, model_id)
```

Non-GLM routes point to `("manifest", <model_id>)`. GLM routes point to `("zai-coding", <canonical_id>)` — flash-named aliases to `glm-5.3-flash`, other GLM aliases to `glm-5.3` — and degrade to Manifest with canonical ids when no effective z.ai key (`ZAI_CODING_API_KEY` or `LLM_API_KEY`) is set. Unknown `glm-*` names go to zai-coding under the same key gate; all other unknown names pass through to Manifest as-is (full 500+ catalog). Use `model="auto"` for Manifest smart routing.

### Factory Dispatch

```python
def create_provider(provider_name, model, api_key) -> LLMProvider:
    key = api_key or settings.get_api_key(provider_name)
    if provider_name == "zai-coding":
        from providers.zai_coding import ZAICodingProvider
        return ZAICodingProvider(api_key=key, model=model)
    from providers.manifest import ManifestProvider
    return ManifestProvider(api_key=key, model=model)
```

Two providers. `settings.get_api_key(provider)` returns the provider's dedicated
key (`MANIFEST_API_KEY` / `ZAI_CODING_API_KEY`) with `LLM_API_KEY` fallback.

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
estimate_credits(provider, model, usage, ts) -> credits (0.0 unless zai-coding)
  |
  v
AnalyticsDB.log_request() -- fire-and-forget
```

Cost always returns `0.0` because Manifest handles billing internally. For `zai-coding` requests, `estimate_credits()` computes plan-credit usage from token counts (cached tokens discounted; 50% off-peak outside Mon-Fri 14:00-18:00 UTC+8). Usage data (prompt/completion tokens) is still tracked for analytics.

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
  |-- cost_usd = calculate_cost(model, tokens)   (always 0.0)
  |-- credits_used = estimate_credits(provider, model, usage, now)
  |
  v
asyncio.create_task(db.log_request({...}))  # fire-and-forget
  |
  v
SQLite (request_logs table)
  |-- Columns: id, provider, model, prompt_tokens, completion_tokens,
  |            total_tokens, latency_ms, ttft_ms, cost_usd, credits_used,
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

GET /v1/analytics/credits
  -> {window_5h: {credits_used, quota},
      window_7d_rolling: {credits_used, quota, note},
      by_model: {<model>: {credits_used, requests}}, off_peak_share}
```

## Configuration Layer

```
.env file --> pydantic BaseSettings --> settings singleton

  Provider keys : MANIFEST_API_KEY, ZAI_CODING_API_KEY  -> manifest_api_key, zai_coding_api_key
  Credit quotas : ZAI_CREDITS_5H (28000), ZAI_CREDITS_WEEK (140000)
  Legacy        : LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL -> llm_provider, llm_model, llm_base_url
  Fallback      : LLM_API_KEY                           -> llm_api_key
  Gateway auth  : APP_API_KEY (required)                -> app_api_key
  Analytics     : ANALYTICS_DB_PATH                     -> analytics_db_path
  CORS / limits : CORS_ORIGINS, RATE_LIMIT              -> cors_origins, rate_limit
```

`get_api_key(provider)` returns the provider's dedicated key (`MANIFEST_API_KEY`
/ `ZAI_CODING_API_KEY`) with `LLM_API_KEY` fallback for each.

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
