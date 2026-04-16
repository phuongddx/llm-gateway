# Research: LLM Gateway Analytics Best Practices

**Date:** 2026-04-16 | **Scope:** Token tracking, SQLite logging, routing, cost estimation, middleware

## Current Codebase State

- 205 LOC, 7 Python files. FastAPI + provider pattern.
- `providers/base.py`: `chat_stream()` yields raw token strings.
- `main.py`: `_stream_tokens()` wraps provider output as SSE `data: {"token": "..."}\n\n`.
- No analytics, no token counting, no cost tracking, no model-based routing (single `LLM_PROVIDER` env var).
- OpenAI-compatible providers (GLM, MiniMax) use `openai.AsyncOpenAI` — gateway does NOT pass `stream_options`.

---

## 1. Token Usage Tracking in SSE Streams

### The Problem

Streaming responses don't return token counts by default. You need provider-specific strategies.

### Strategy A: `stream_options={"include_usage": True}` (OpenAI-compatible)

**Works for:** GLM, MiniMax, DeepSeek, any OpenAI-compatible endpoint.

The final chunk in the stream includes `usage` field when this param is set:

```python
stream = await self.client.chat.completions.create(
    model=self.model,
    messages=all_messages,
    stream=True,
    stream_options={"include_usage": True},  # KEY PARAM
)

usage_data = None
async for chunk in stream:
    # Check if chunk has usage data (final chunk)
    if hasattr(chunk, "usage") and chunk.usage is not None:
        usage_data = {
            "prompt_tokens": chunk.usage.prompt_tokens,
            "completion_tokens": chunk.usage.completion_tokens,
            "total_tokens": chunk.usage.total_tokens,
        }
    delta = chunk.choices[0].delta.content if chunk.choices else None
    if delta:
        yield delta, usage_data  # usage_data is None until last chunk
```

**Source:** [OpenAI Chat Completions API Reference](https://platform.openai.com/docs/api-reference/chat/create) confirms `stream_options` parameter.

### Strategy B: Gemini Usage Metadata

Gemini SDK returns `usage_metadata` on the final response chunk:

```python
async for chunk in response:
    text = getattr(chunk, "text", None)
    usage_meta = getattr(chunk, "usage_metadata", None)
    if usage_meta:
        usage_data = {
            "prompt_tokens": usage_meta.prompt_token_count,
            "completion_tokens": usage_meta.candidates_token_count,
            "total_tokens": usage_meta.total_token_count,
        }
    if text:
        yield text, usage_data
```

### Strategy C: Estimation Fallback

When provider doesn't return usage (e.g. some OpenAI-compatible APIs ignore `stream_options`):

```python
# Rough estimation: ~4 chars per token (English), ~2 chars per token (CJK)
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
```

### Recommendation

**Modify `chat_stream()` signature** to optionally yield `(token, usage_dict | None)` tuples. Each provider handles its own usage extraction. The analytics layer collects whatever is available.

```python
# Updated base class
class LLMProvider(ABC):
    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncGenerator[tuple[str, dict | None], None]:
        """Yield (token, usage_data) tuples. usage_data is None except possibly on last chunk."""
        ...
```

**Trade-off:** Breaking change to all providers. But currently only 3 providers, all small. Worth it.

---

## 2. SQLite Schema for Request Logging

### Recommended Schema

```sql
CREATE TABLE IF NOT EXISTS request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Request metadata
    provider TEXT NOT NULL,           -- "gemini", "glm", "minimax"
    model TEXT NOT NULL,              -- "gemini-2.5-flash", "glm-4-flash"
    api_key_hash TEXT NOT NULL,       -- SHA256(last 8 chars of key) for grouping

    -- Token counts (nullable — may not be available for all providers)
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,

    -- Performance
    latency_ms INTEGER,              -- Total request wall-clock time
    ttft_ms INTEGER,                 -- Time to first token

    -- Status
    is_success BOOLEAN NOT NULL DEFAULT 1,
    error_message TEXT,

    -- Cost (calculated from token counts * pricing table)
    estimated_cost_usd REAL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_request_logs_provider ON request_logs(provider);
CREATE INDEX IF NOT EXISTS idx_request_logs_model ON request_logs(model);
CREATE INDEX IF NOT EXISTS idx_request_logs_api_key_hash ON request_logs(api_key_hash);
```

### Pricing Reference Table

```sql
CREATE TABLE IF NOT EXISTS model_pricing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL UNIQUE,          -- "gpt-4o", "gemini-2.5-flash"
    provider TEXT NOT NULL,
    input_price_per_1m REAL NOT NULL,    -- USD per 1M input tokens
    output_price_per_1m REAL NOT NULL,   -- USD per 1M output tokens
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

### Why This Schema Works

- **Single table** for writes (KISS). No joins needed for insert.
- **Nullable token fields** handle providers that don't return usage.
- `api_key_hash` groups by API key without storing the actual key.
- `ttft_ms` (time to first token) is the key latency metric for streaming.
- Price table is separate — rarely updated, used for cost calculation at insert time.

### SQLite Gotchas

- Use WAL mode for concurrent reads/writes: `PRAGMA journal_mode=WAL;`
- Use a single connection with `aiosqlite` for async compatibility.
- Batch inserts if high throughput needed (unlikely for a gateway with <100 req/s).

---

## 3. Per-Request Provider Routing (Model-Based)

### Current Problem

Gateway uses single `LLM_PROVIDER` env var. No model-based routing.

### Recommended: Model-to-Provider Mapping Table

```python
# routing.py

MODEL_ROUTING: dict[str, dict] = {
    # OpenAI models
    "gpt-4o":         {"provider": "openai",   "model": "gpt-4o"},
    "gpt-4o-mini":    {"provider": "openai",   "model": "gpt-4o-mini"},
    # Anthropic models
    "claude-sonnet-4": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
    # Google models
    "gemini-2.5-flash": {"provider": "gemini", "model": "gemini-2.5-flash"},
    "gemini-2.0-flash": {"provider": "gemini", "model": "gemini-2.0-flash"},
    # Chinese providers
    "glm-4-flash":    {"provider": "glm",      "model": "glm-4-flash"},
    "minimax-text":   {"provider": "minimax",  "model": "MiniMax-Text-01"},
    "deepseek-v3":    {"provider": "deepseek", "model": "deepseek-chat"},
    "deepseek-r1":    {"provider": "deepseek", "model": "deepseek-reasoner"},
}

def resolve_provider(model_name: str) -> tuple[str, str]:
    """Returns (provider_name, actual_model_name)."""
    if model_name not in MODEL_ROUTING:
        raise ValueError(f"Unknown model: {model_name}")
    entry = MODEL_ROUTING[model_name]
    return entry["provider"], entry["model"]
```

### Updated Request Flow

```python
# Client sends: {"model": "gemini-2.5-flash", "messages": [...]}
# Gateway resolves: provider="gemini", model="gemini-2.5-flash"

class ChatRequest(BaseModel):
    model: str                        # NEW: client specifies model
    messages: list[dict]
    system_prompt: str = ""
    stream: bool = True

@app.post("/v1/chat/completions")
async def chat(request: ChatRequest, _auth=Depends(verify_auth)):
    provider_name, model_name = resolve_provider(request.model)
    provider = create_provider(provider_name, model_name)  # pass model to factory
    return StreamingResponse(
        _stream_tokens(provider, request),
        media_type="text/event-stream",
    )
```

### Key Design Decisions

- **Mapping is static config** (Python dict), not database. Simpler, faster, reload on change.
- **Fallback:** If model not in mapping, try to infer from env var (backward compat).
- **Provider factory** needs to accept `model` parameter instead of reading from `settings`.

---

## 4. Cost Estimation — Pricing Per 1M Tokens

### Current Pricing (April 2026, from official sources)

| Model | Input $/1M | Output $/1M | Source |
|-------|-----------|------------|--------|
| **GPT-4o** | $2.50 | $10.00 | [OpenAI Pricing](https://openai.com/api/pricing/) |
| **GPT-4o mini** | $0.15 | $0.60 | [OpenAI Pricing](https://openai.com/api/pricing/) |
| **GPT-5.4** | $2.50 | $15.00 | [OpenAI Pricing](https://openai.com/api/pricing/) |
| **Claude Sonnet 4** | $3.00 | $15.00 | [Anthropic Pricing](https://docs.anthropic.com/en/docs/about-claude/models) |
| **Claude Haiku 3.5** | $0.80 | $4.00 | [Anthropic Pricing](https://docs.anthropic.com/en/docs/about-claude/models) |
| **Gemini 2.0 Flash** | $0.10 | $0.40 | [Google AI Pricing](https://ai.google.dev/pricing) |
| **Gemini 1.5 Pro** | $1.25 | $5.00 | [Google AI Pricing](https://ai.google.dev/pricing) |
| **DeepSeek V3** | $0.27 | $1.10 | [DeepSeek Pricing](https://api-docs.deepseek.com/quick_start/pricing) |
| **DeepSeek R1** | $0.55 | $2.19 | [DeepSeek Pricing](https://api-docs.deepseek.com/quick_start/pricing) |
| **GLM-4-Flash** | Free tier available | — | ZhipuAI |

### Cost Calculation Function

```python
def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return 0.0
    cost = (
        prompt_tokens * pricing["input_price_per_1m"] / 1_000_000
        + completion_tokens * pricing["output_price_per_1m"] / 1_000_000
    )
    return round(cost, 8)
```

### Credibility Note

- OpenAI and Google pricing confirmed from live official pages.
- Anthropic and DeepSeek pricing from training data (web search hit rate limits). **Verify before hardcoding.**

---

## 5. FastAPI Middleware for Non-Blocking Stream Logging

### The Challenge

Standard middleware sees the `StreamingResponse` as a static object. The body is an async generator consumed after the middleware returns. You must **wrap the generator** to intercept chunks.

### Recommended Pattern: Generator Wrapper (NOT Middleware)

Avoid Starlette HTTP middleware for this. It adds complexity and breaks easily with streaming. Instead, **instrument at the generator level**:

```python
# analytics.py
import time
import uuid

async def tracked_stream(provider, request: ChatRequest, db):
    """Wraps provider.chat_stream() to collect analytics."""
    request_id = str(uuid.uuid4())
    start_time = time.monotonic()
    first_token_time = None
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    error_msg = None
    token_count = 0

    try:
        async for token, usage in provider.chat_stream(request.messages, request.system_prompt):
            if first_token_time is None:
                first_token_time = time.monotonic()
            token_count += 1
            yield token, usage

            # Capture usage from final chunk
            if usage:
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)

    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        end_time = time.monotonic()
        latency_ms = int((end_time - start_time) * 1000)
        ttft_ms = int((first_token_time - start_time) * 1000) if first_token_time else None

        # Fire-and-forget log write
        await db.log_request(
            provider=provider.name,
            model=provider.model,
            api_key_hash=hash_api_key(request.api_key),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            is_success=(error_msg is None),
            error_message=error_msg,
            estimated_cost_usd=calculate_cost(provider.model, prompt_tokens, completion_tokens),
        )
```

### Updated `_stream_tokens`

```python
async def _stream_tokens(provider, request: ChatRequest, analytics):
    async for token, usage in analytics.tracked_stream(provider, request):
        yield f"data: {json.dumps({'token': token})}\n\n"
    yield "data: [DONE]\n\n"
```

### Why NOT Middleware

| Approach | Pros | Cons |
|----------|------|------|
| **Generator wrapper** | Full control, access to provider/model context, simple | Must modify endpoint code |
| **Starlette middleware** | Framework-standard, works on all routes | Can't access request body in streaming, loses provider context, complex wrapping of `body_iterator` |
| **Background task** | Non-blocking | Can't capture streaming metrics (ttft, tokens) |

**Recommendation:** Generator wrapper. It has direct access to provider context and produces cleaner code. Middleware is overkill here — you only have one streaming endpoint.

---

## 6. DB Layer: aiosqlite Helper

```python
# db.py
import aiosqlite
from contextlib import asynccontextmanager

DB_PATH = "analytics.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.executescript(SCHEMA_SQL)  # The CREATE TABLE statements above
        await db.commit()

class AnalyticsDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def log_request(self, **kwargs):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO request_logs
                   (provider, model, api_key_hash, prompt_tokens, completion_tokens,
                    total_tokens, latency_ms, ttft_ms, is_success, error_message,
                    estimated_cost_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (kwargs["provider"], kwargs["model"], kwargs["api_key_hash"],
                 kwargs["prompt_tokens"], kwargs["completion_tokens"],
                 kwargs["total_tokens"], kwargs["latency_ms"], kwargs["ttft_ms"],
                 kwargs["is_success"], kwargs["error_message"],
                 kwargs["estimated_cost_usd"])
            )
            await db.commit()
```

### FastAPI Lifecycle Integration

```python
# main.py
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.analytics = AnalyticsDB()
    yield
    # cleanup if needed

app = FastAPI(title="LLM Gateway", lifespan=lifespan)
```

---

## Architecture Summary

```
Client POST /v1/chat/completions {"model": "gemini-2.5-flash", "messages": [...]}
  |
  v
Auth check
  |
  v
resolve_provider("gemini-2.5-flash") -> ("gemini", "gemini-2.5-flash")
  |
  v
create_provider("gemini", "gemini-2.5-flash") -> GeminiProvider(model="gemini-2.5-flash")
  |
  v
StreamingResponse(tracked_stream(provider, request, analytics))
  |
  +-- provider.chat_stream() yields (token, usage) tuples
  +-- tracked_stream() measures ttft, latency, captures usage from final chunk
  +-- SSE formatted: data: {"token": "..."}\n\n
  +-- On stream end: analytics.log_request() writes to SQLite
  |
  v
Client receives SSE stream
```

---

## Recommended File Structure (New Files)

```
llm-gateway/
├── analytics/
│   ├── __init__.py          # Exports: tracked_stream, AnalyticsDB
│   ├── db.py                # SQLite schema + AnalyticsDB class
│   ├── cost.py              # MODEL_PRICING dict + calculate_cost()
│   └── routing.py           # MODEL_ROUTING dict + resolve_provider()
├── providers/
│   ├── base.py              # Updated: yield (token, usage) tuples
│   ├── gemini.py            # Updated: extract usage_metadata
│   ├── glm.py               # Updated: stream_options + usage
│   └── minimax.py           # Updated: stream_options + usage
├── main.py                  # Updated: lifespan, model routing, tracked_stream
└── config.py                # Updated: multi-provider API keys
```

---

## Adoption Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Breaking `chat_stream()` interface | Low | Only 3 providers, all trivially updated |
| `stream_options` not supported by some OpenAI-compatible APIs | Medium | Fallback to token estimation |
| SQLite write contention at scale | Low | WAL mode handles ~100K writes/sec; gateway unlikely to exceed 100 req/s |
| Pricing data staleness | Medium | Store in separate table, update via migration or config |
| aiosqlite dependency | Low | Well-maintained, standard for async SQLite in Python |

---

## Unresolved Questions

1. **Multi-provider API key management:** Currently single `LLM_API_KEY` env var. Need per-provider keys (e.g. `GEMINI_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`). How to configure?
2. **Rate limiting:** No rate limiting in current gateway. Analytics DB could feed into rate limiter, but that's a separate feature.
3. **Analytics dashboard:** Report focuses on data collection. Visualization (e.g. `/analytics` endpoint or simple HTML page) is out of scope but should be planned.
4. **Log retention / cleanup:** SQLite will grow unbounded. Need periodic cleanup or rotation strategy.
5. **Batch insert optimization:** For high-throughput scenarios, batch inserts may be needed. Start simple, optimize later (YAGNI).

---

## Sources

- [OpenAI Chat Completions API Reference](https://platform.openai.com/docs/api-reference/chat/create) — `stream_options` parameter documentation
- [OpenAI API Pricing](https://openai.com/api/pricing/) — Live pricing as of April 2026
- [Google AI Gemini Pricing](https://ai.google.dev/pricing) — Live pricing as of April 2026
- [Anthropic Claude Models & Pricing](https://docs.anthropic.com/en/docs/about-claude/models) — Training data (not verified live)
- [DeepSeek API Pricing](https://api-docs.deepseek.com/quick_start/pricing) — Training data (not verified live)
