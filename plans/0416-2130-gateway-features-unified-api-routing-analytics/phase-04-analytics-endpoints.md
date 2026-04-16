# Phase 4: Analytics REST Endpoints

## Context Links

- [Plan Overview](./plan.md)
- [Phase 3: Analytics Engine](./phase-03-analytics-engine.md) (prerequisite — queries the DB)
- Analytics DB: `analytics/db.py`

## Overview

- **Priority**: P2 (does not block Phase 5 — can be tested independently)
- **Status**: `[ ]`
- **Description**: Add REST endpoints for querying analytics data — summary stats, per-model comparison, and recent request logs.

## Key Insights

1. **Thin endpoint layer**: endpoints are just HTTP wrappers around `AnalyticsDB` query methods built in Phase 3. Minimal logic here.
2. **All endpoints behind Bearer auth**: reuse `verify_auth` dependency from routes/chat.py.
3. **Time filtering**: all endpoints accept optional `since` ISO 8601 query param for date range filtering.
4. **Pagination**: request list endpoint needs `limit` + `offset` for large datasets.

## Requirements

### Functional

- FR-4.1: `GET /v1/analytics/summary` — aggregate stats: total requests, total tokens, total cost, avg latency, avg TTFT, error rate
- FR-4.2: `GET /v1/analytics/models` — per-model breakdown: request count, token totals, cost, avg latency per model
- FR-4.3: `GET /v1/analytics/requests` — paginated list of recent requests with all fields
- FR-4.4: `GET /v1/models` — list available models from routing table (OpenAI-compatible format)
- FR-4.5: All analytics endpoints accept `since` query param (ISO 8601 datetime) for time filtering
- FR-4.6: Requests endpoint accepts `limit` (default 50, max 200) and `offset` (default 0) params
- FR-4.7: Models endpoint accepts optional `provider` filter param

### Non-Functional

- NFR-4.1: Response time under 200ms for 10K rows in DB
- NFR-4.2: No N+1 queries — single SQL query per endpoint
- NFR-4.3: File under 100 LOC

## Architecture

### Data Flow

```
GET /v1/analytics/summary?since=2026-04-01T00:00:00Z
    |
    v
verify_auth() ──> 401 if invalid
    |
    v
analytics.py route handler
    |
    v
app.state.analytics_db.get_summary(since="2026-04-01T00:00:00Z")
    |
    v
SQLite aggregate query
    |
    v
JSON response:
{
    "total_requests": 1234,
    "total_prompt_tokens": 500000,
    "total_completion_tokens": 200000,
    "total_cost_usd": 3.45,
    "avg_latency_ms": 1200,
    "avg_ttft_ms": 350,
    "error_rate": 0.02,
    "since": "2026-04-01T00:00:00Z"
}
```

### Endpoint Specs

```
GET /v1/models
  Auth: Bearer token required
  Response: { "object": "list", "data": [{ "id": "gpt-4o", "object": "model", "owned_by": "openai", ... }] }
  Source: generated from MODEL_ROUTING dict — no DB query needed

GET /v1/analytics/summary
  Query params: since (optional, ISO 8601)
  Response: { total_requests, total_prompt_tokens, total_completion_tokens,
              total_cost_usd, avg_latency_ms, avg_ttft_ms, error_rate, since }

GET /v1/analytics/models
  Query params: since (optional), provider (optional)
  Response: { models: [{ model, provider, request_count, prompt_tokens,
             completion_tokens, cost_usd, avg_latency_ms, avg_ttft_ms }], since }

GET /v1/analytics/requests
  Query params: since (optional), limit (default 50, max 200), offset (default 0)
  Response: { requests: [{ id, provider, model, prompt_tokens, completion_tokens,
             total_tokens, latency_ms, ttft_ms, cost_usd, status, error_message,
             created_at }], total, limit, offset }
```

## Related Code Files

### Modify

| File | Change |
|------|--------|
| `main.py` | Mount analytics router via `app.include_router()` |

### Create

| File | Purpose | LOC est. |
|------|---------|----------|
| `routes/analytics.py` | Analytics REST endpoints | ~90 |

### Delete

None.

## Implementation Steps

1. **Create `routes/analytics.py`** (~120 LOC):
   ```python
   from fastapi import APIRouter, Depends, Query, Request
   from routes.chat import verify_auth
   from analytics.routing import MODEL_ROUTING

   # Model listing endpoint (OpenAI-compatible format)
   @router.get("/v1/models")
   async def list_models(_auth=Depends(verify_auth)):
       models = []
       for model_name, (provider, _) in MODEL_ROUTING.items():
           models.append({
               "id": model_name,
               "object": "model",
               "owned_by": provider,
           })
       return {"object": "list", "data": models}

   # Analytics endpoints
   analytics_router = APIRouter(prefix="/v1/analytics", tags=["analytics"])

   @router.get("/summary")
   async def get_summary(
       request: Request,
       since: str | None = Query(None, description="ISO 8601 datetime"),
       _auth=Depends(verify_auth),
   ):
       db = request.app.state.analytics_db
       result = await db.get_summary(since)
       return result

   @router.get("/models")
   async def get_model_stats(
       request: Request,
       since: str | None = Query(None),
       provider: str | None = Query(None),
       _auth=Depends(verify_auth),
   ):
       db = request.app.state.analytics_db
       result = await db.get_model_stats(since, provider)
       return result

   @router.get("/requests")
   async def get_requests(
       request: Request,
       since: str | None = Query(None),
       limit: int = Query(50, ge=1, le=200),
       offset: int = Query(0, ge=0),
       _auth=Depends(verify_auth),
   ):
       db = request.app.state.analytics_db
       result = await db.get_recent(limit, offset, since)
       return result
   ```

2. **Update `main.py`** — add one line:
   ```python
   from routes.analytics import router as analytics_router
   app.include_router(analytics_router)
   ```

3. **Verify `analytics/db.py` query methods** return dicts matching the endpoint response schemas (may need minor adjustments to query result formatting from Phase 3).

## Todo Checklist

- [ ] Create `routes/analytics.py` with 4 endpoints (summary, models, requests + GET /v1/models)
- [ ] Update `main.py` to mount analytics router
- [ ] Test `GET /v1/models` returns OpenAI-compatible model list
- [ ] Test `GET /v1/analytics/summary` returns correct aggregate
- [ ] Test `GET /v1/analytics/models` groups by model correctly
- [ ] Test `GET /v1/analytics/requests` pagination works
- [ ] Test all endpoints return 401 without valid Bearer token
- [ ] Test `since` param filters correctly

## Success Criteria

- [ ] `GET /v1/analytics/summary` returns JSON with all 8 fields
- [ ] `GET /v1/analytics/models` returns array grouped by model with per-model stats
- [ ] `GET /v1/analytics/requests?limit=10&offset=0` returns paginated list
- [ ] All endpoints return 401 without auth header
- [ ] `since=2026-01-01T00:00:00Z` filters to only requests after that date
- [ ] Response time under 200ms with 10K rows
- [ ] File under 100 LOC

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| DB query slow on large dataset | Low | Medium | Indexes on created_at, model, provider (added in Phase 3) |
| Analytics endpoints leak sensitive data | Low | High | Only log metadata, never log message content |
| Missing `since` param returns entire history | Medium | Low | Default `since` to last 30 days if not provided (optional optimization) |

## Security Considerations

- All endpoints require Bearer auth (same as chat endpoint)
- No request body content is stored or returned — only metadata
- Rate limiting not in scope but recommended for production

## Next Steps

- Phase 5 validates full integration: request flow + analytics recording + endpoint querying
