# Phase 3: Analytics Engine — SQLite Storage + Tracked Streaming

## Context Links

- [Plan Overview](./plan.md)
- [Phase 1: Config & Routing](./phase-01-config-and-routing.md) (prerequisite)
- [Phase 2: Provider Updates](./phase-02-provider-updates.md) (prerequisite — needs UsageData from providers)
- Current streaming: `main.py` `_stream_tokens()` generator

## Overview

- **Priority**: P1 (blocks Phase 4 — endpoints query the DB)
- **Status**: `[ ]`
- **Description**: Add SQLite-backed request logging via generator wrapper pattern. Track tokens, latency, TTFT, cost per request. Extract chat route from main.py into routes/chat.py with tracked_stream wrapper.

## Key Insights

1. **Generator wrapper pattern**: `tracked_stream()` wraps `provider.chat_stream()`, records timing/usage while yielding tokens to SSE. This is simpler than middleware because we need per-token timing (TTFT) and final usage data that only the stream producer knows.
2. **SQLite with WAL mode**: single-file DB, no external service dependency. WAL mode allows concurrent reads during writes.
3. **DB init on startup**: use FastAPI lifespan to create tables on app start. No migration framework needed — single schema version.
4. **Cost calculation**: pricing dict in `analytics/cost.py`. Lookup by model name, multiply by token counts.
5. **TTFT measurement**: time from stream start to first token yield. Critical latency metric.

## Requirements

### Functional

- FR-3.1: Every chat completion request is logged to SQLite
- FR-3.2: Log record includes: request_id (UUID), provider, model, prompt/completion/total tokens, latency_ms, ttft_ms, cost_usd, status (success/error), error_message, created_at
- FR-3.3: TTFT (time to first token) measured and stored
- FR-3.4: Cost calculated from token counts and pricing table
- FR-3.5: Errors during streaming logged with status="error" and error_message
- FR-3.6: DB initialized on app startup via FastAPI lifespan
- FR-3.7: On transient provider errors (timeout, 5xx), retry with alternative provider (max 2 retries) before logging error

### Non-Functional

- NFR-3.1: Analytics write does not block token streaming (fire-and-forget via `asyncio.create_task`)
- NFR-3.2: DB write failure does not affect stream delivery to client
- NFR-3.3: SQLite file at `data/analytics.db` (configurable via `ANALYTICS_DB_PATH` env var)
- NFR-3.4: WAL mode enabled for concurrent read/write

## Architecture

### Data Flow

```
Client request
    |
    v
routes/chat.py: chat endpoint
    |
    v
resolve_provider(model)  ──>  create_provider(provider, model, api_key)
    |
    v
tracked_stream(provider, request_metadata)
    |
    ├── records start_time
    ├── try: async for (token, usage) in provider.chat_stream(...):
    │     ├── first token? → record ttft = now - start_time
    │     ├── accumulate token count (approximate from text length if no usage)
    │     └── yield SSE-formatted token to client
    ├── on transient error (timeout, 5xx):
    │     ├── retry with next provider (max 2 retries)
    │     └── if all retries fail → log error record, yield SSE error
    ├── on completion:
    │     ├── calculate latency = now - start_time
    │     ├── calculate cost from usage tokens × pricing
    │     └── asyncio.create_task(db.insert_request_log(...))
    └── on non-retryable error:
          ├── log error record
          └── yield SSE error event
```

### Schema

```sql
-- request_logs table
CREATE TABLE IF NOT EXISTS request_logs (
    id TEXT PRIMARY KEY,              -- UUID
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    ttft_ms INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'success',  -- success | error
    error_message TEXT,
    created_at TEXT NOT NULL           -- ISO 8601
);

-- model_pricing table
CREATE TABLE IF NOT EXISTS model_pricing (
    model TEXT PRIMARY KEY,
    input_price_per_1m REAL NOT NULL,   -- USD per 1M input tokens
    output_price_per_1m REAL NOT NULL,  -- USD per 1M output tokens
    updated_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_model ON request_logs(model);
CREATE INDEX IF NOT EXISTS idx_logs_provider ON request_logs(provider);
```

### Component Interactions

```
main.py (lifespan)
    └── AnalyticsDB.initialize() ──> creates tables, seeds pricing

routes/chat.py
    ├── tracked_stream() ──> wraps provider.chat_stream()
    └── on stream end ──> db.log_request(...)

analytics/db.py (AnalyticsDB)
    ├── initialize()     ──> create tables, enable WAL
    ├── log_request()    ──> INSERT into request_logs
    ├── get_summary()    ──> aggregate queries (used by Phase 4)
    ├── get_model_stats()──> per-model comparison (used by Phase 4)
    └── get_recent()     ──> paginated request list (used by Phase 4)

analytics/cost.py
    ├── MODEL_PRICING    ──> hardcoded pricing dict
    └── calculate_cost() ──> tokens × price_per_1m / 1_000_000
```

## Related Code Files

### Modify

| File | Change |
|------|--------|
| `main.py` | Add lifespan handler for DB init; extract chat route to routes/chat.py; mount route routers |
| `analytics/__init__.py` | Export AnalyticsDB |

### Create

| File | Purpose | LOC est. |
|------|---------|----------|
| `analytics/db.py` | SQLite schema + AnalyticsDB class | ~120 |
| `analytics/cost.py` | MODEL_PRICING dict + calculate_cost() | ~60 |
| `routes/__init__.py` | Package init | ~5 |
| `routes/chat.py` | Chat endpoint + tracked_stream() | ~100 |

### Delete

None.

## Implementation Steps

1. **Create `analytics/cost.py`** (~60 LOC):
   ```python
   MODEL_PRICING: dict[str, tuple[float, float]] = {
       "gpt-4o": (2.50, 10.00),
       "gpt-4o-mini": (0.15, 0.60),
       "o3": (2.00, 8.00),
       "gemini-2.5-flash": (0.15, 0.60),
       "glm-4-flash": (0.01, 0.01),
       "MiniMax-Text-01": (0.01, 0.01),
       "deepseek-chat": (0.27, 1.10),
       "deepseek-reasoner": (0.55, 2.19),
       "kimi-k2.5": (0.60, 2.50),
       "kimi-k2-thinking": (0.60, 2.50),
       "moonshot-v1-128k": (0.02, 0.02),
   }

   def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
       if model not in MODEL_PRICING:
           return 0.0
       input_price, output_price = MODEL_PRICING[model]
       return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
   ```

2. **Create `analytics/db.py`** (~120 LOC):
   - `AnalyticsDB` class with `aiosqlite` connection
   - `__init__(self, db_path: str)` — store path
   - `async def initialize(self)` — create tables, enable WAL, seed pricing data
   - `async def log_request(self, record: dict)` — INSERT into request_logs
   - `async def get_summary(self, since: str | None)` — aggregate stats
   - `async def get_model_stats(self, since: str | None)` — per-model comparison
   - `async def get_recent(self, limit: int, offset: int)` — paginated list
   - Use connection pool pattern: single connection with `aiosqlite.connect()` held open
   - All methods are async, use parameterized queries (no SQL injection)

3. **Create `routes/__init__.py`** — empty or minimal exports

4. **Create `routes/chat.py`** (~100 LOC):
   - Import `APIRouter` from FastAPI
   - Move `ChatRequest` model here
   - Move `verify_auth` dependency here
   - `tracked_stream()` async generator:
     - Accept provider, messages, system_prompt, model, provider_name
     - Record `start_time = time.monotonic()`, generate `request_id = uuid4()`
     - Iterate `provider.chat_stream(messages, system_prompt)`
     - Track `first_token_time` for TTFT
     - Accumulate token count (approximate: len(token) / 4 chars per token) when usage not provided
     - On completion: calculate cost, fire `asyncio.create_task(db.log_request(...))`
     - On exception: log error record, yield SSE error
     - **Retry logic**: wrap `provider.chat_stream()` in try/except. On transient errors (asyncio.TimeoutError, httpx 5xx), retry up to 2 times with a different provider (from MODEL_ROUTING alternatives or same provider). If no alternative available, fail after retry count exhausted.
     - Always yield `data: [DONE]\n\n` at end
   - SSE format stays same: `data: {"token": "..."}\n\n`
   - If usage data present, include in final chunk before DONE: `data: {"usage": {...}}\n\n`

5. **Update `main.py`** (~40 LOC):
   - Add `lifespan` context manager:
     - On startup: create `AnalyticsDB`, call `initialize()`, store on `app.state`
     - On shutdown: close DB connection
   - Create `APIRouter` for chat route, mount via `app.include_router()`
   - Keep `health` endpoint in main.py
   - Keep CORS middleware setup

6. **Update `analytics/__init__.py`**:
   ```python
   from analytics.db import AnalyticsDB
   from analytics.cost import calculate_cost, MODEL_PRICING
   ```

## Todo Checklist

- [ ] Create `analytics/cost.py` with MODEL_PRICING and calculate_cost()
- [ ] Create `analytics/db.py` with AnalyticsDB class (schema, log_request, query methods)
- [ ] Create `routes/__init__.py`
- [ ] Create `routes/chat.py` with tracked_stream() + ChatRequest + verify_auth
- [ ] Update `main.py` — lifespan, router mounting, remove extracted code
- [ ] Update `analytics/__init__.py` exports
- [ ] Verify SSE streaming still works end-to-end
- [ ] Verify request_logs table gets populated after a test request
- [ ] Verify TTFT and latency are recorded

## Success Criteria

- [ ] `GET /health` returns 200 (lifespan works)
- [ ] `POST /v1/chat/completions` streams tokens identically to before
- [ ] After a request, `request_logs` table has one row with correct provider, model, tokens, latency_ms, ttft_ms, cost_usd
- [ ] Error requests logged with status="error" and error_message populated
- [ ] DB write failure does not crash the stream or return error to client
- [ ] `calculate_cost("gpt-4o", 1000, 500)` returns `0.0075` (2.50*1000/1M + 10.00*500/1M)
- [ ] No file exceeds 120 LOC

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SQLite write blocks stream yield | Low | High | Use `asyncio.create_task` for fire-and-forget DB write |
| DB file permissions on deploy | Low | Medium | Configurable path via env var; log warning on init failure |
| aiosqlite connection issues under load | Low | Medium | Single connection, WAL mode; add retry logic in log_request |
| Missing pricing for new model | Medium | Low | Default cost=0.0 for unknown models; log warning |
| Approximate token count inaccurate | High | Low | Only used when provider doesn't return usage; accept inaccuracy, log note |

## Security Considerations

- DB file should not be in web-accessible path
- Request logs may contain error messages — ensure no API keys leak into error_message field
- Analytics endpoints (Phase 4) will reuse same Bearer auth

## Next Steps

- Phase 4 (Analytics Endpoints) uses `AnalyticsDB.get_summary()`, `get_model_stats()`, `get_recent()` to expose REST API
