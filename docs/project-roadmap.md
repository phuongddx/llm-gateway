# Project Roadmap

## Phase 1: Core Gateway (Complete)

Basic multi-provider proxy with streaming SSE output.

**Status:** Complete

Deliverables:
- [x] FastAPI application with CORS middleware
- [x] `POST /v1/chat/completions` endpoint with SSE streaming
- [x] `GET /health` endpoint
- [x] Bearer token authentication
- [x] Provider abstraction (abstract base class + factory)

## Phase 2: Multi-Provider Routing & Analytics (Complete)

Model-based routing, expanded provider support, analytics pipeline.

**Status:** Complete

Deliverables:
- [x] Model-based routing via `MODEL_ROUTING` dict (client specifies `model`, gateway resolves provider)
- [x] 8 providers: OpenAI, DeepSeek, MoonshotAI, Gemini, GLM, MiniMax, ByteDance
- [x] Shared `OpenAICompatibleProvider` base class (6 providers share implementation)
- [x] Per-provider API keys with `LLM_API_KEY` fallback
- [x] SQLite-backed analytics storage (aiosqlite)
- [x] Request tracking: latency, TTFT, token usage, cost
- [x] `GET /v1/models` -- OpenAI-compatible model listing
- [x] `GET /v1/analytics/summary` -- aggregate stats
- [x] `GET /v1/analytics/models` -- per-model stats
- [x] `GET /v1/analytics/requests` -- paginated request listing
- [x] Model pricing table with cost calculation
- [x] FastAPI lifespan for DB init/shutdown
- [x] Routes extracted to `routes/chat.py` and `routes/analytics.py`
- [x] Analytics package: `analytics/db.py`, `analytics/cost.py`, `analytics/routing.py`
- [x] Test suite: pytest with httpx test client

## Phase 3: Production Readiness (Planned)

Infrastructure and operational concerns for production deployment.

**Status:** Not started

| Feature | Description | Priority |
|---------|-------------|----------|
| Docker image | Multi-stage Dockerfile with non-root user | High |
| Docker Compose | Local dev and production compose configs | High |
| CI/CD pipeline | GitHub Actions: lint, test, build, push image | High |
| Prometheus metrics | Request count, latency histogram, error rate | Medium |
| Health checks | Liveness (process) and readiness (provider connectivity) | Medium |
| Rate limiting | Per-key request rate limits | Medium |
| Error retry | Automatic retry with backoff on transient provider errors | Medium |
| Secrets management | Support Vault/AWS Secrets Manager beyond .env files | Low |
| Horizontal scaling | Stateless design allows multi-instance deployment | Low |
| API versioning | Support multiple API versions simultaneously | Low |

## Success Criteria

- **Phase 1**: Three providers streaming tokens end-to-end (achieved)
- **Phase 2**: 8 providers with model-based routing and analytics pipeline (achieved)
- **Phase 3**: Docker-based deployment with CI/CD and monitoring

## Related Docs

- [Project Overview & PDR](./project-overview-pdr.md)
- [System Architecture](./system-architecture.md)
- [Deployment Guide](./deployment-guide.md)
