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
- [x] Gemini provider via `google-genai` SDK
- [x] GLM (ZhipuAI) provider via OpenAI-compatible API
- [x] MiniMax provider via OpenAI-compatible API
- [x] Pydantic settings with `.env` file support
- [x] Makefile for common tasks
- [x] `.env.example` template

## Phase 2: Enhancements (Planned)

Improvements for reliability, observability, and developer experience.

**Status:** Not started

| Feature | Description | Priority |
|---------|-------------|----------|
| Rate limiting | Per-key request rate limits to prevent abuse | High |
| Request logging | Structured request/response logging with latency | High |
| Error retry | Automatic retry with backoff on transient provider errors | Medium |
| Token usage | Report token counts in SSE stream metadata | Medium |
| Model listing | `GET /v1/models` endpoint to list available models | Medium |
| Connection pooling | Reuse HTTP clients across requests instead of creating per-request | Medium |
| Additional providers | Claude, DeepSeek, Mistral, etc. | Low |
| Batched streaming | Buffer tokens for improved throughput on slow connections | Low |
| Graceful shutdown | Drain in-flight requests on SIGTERM | Low |

## Phase 3: Production Readiness (Planned)

Infrastructure and operational concerns for production deployment.

**Status:** Not started

| Feature | Description | Priority |
|---------|-------------|----------|
| Docker image | Multi-stage Dockerfile with non-root user | High |
| Docker Compose | Local dev and production compose configs | High |
| CI/CD pipeline | GitHub Actions: lint, test, build, push image | High |
| Unit tests | pytest with mocked provider SDKs | High |
| Integration tests | End-to-end tests against real providers (CI secrets) | Medium |
| Prometheus metrics | Request count, latency histogram, error rate | Medium |
| Health checks | Liveness (process) and readiness (provider connectivity) | Medium |
| Secrets management | Support Vault/AWS Secrets Manager beyond .env files | Low |
| Horizontal scaling | Stateless design allows multi-instance deployment | Low |
| API versioning | Support multiple API versions simultaneously | Low |

## Success Criteria

- **Phase 1**: Three providers streaming tokens end-to-end (achieved)
- **Phase 2**: Request logging and rate limiting operational
- **Phase 3**: Docker-based deployment with CI/CD and monitoring

## Related Docs

- [Project Overview & PDR](./project-overview-pdr.md)
- [System Architecture](./system-architecture.md)
- [Deployment Guide](./deployment-guide.md)
