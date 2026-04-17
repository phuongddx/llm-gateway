# Project Overview & Product Development Requirements

## Problem Statement

Applications that integrate with LLMs face vendor lock-in when they hardcode calls to a single provider. Switching providers requires rewriting API integration code, changing message formats, and updating authentication flows. Teams need a lightweight proxy that normalizes access to multiple LLM backends through a single, consistent interface, with visibility into usage and cost.

## Product

**LLM Gateway** is a FastAPI-based API gateway that exposes an OpenAI-compatible chat completions endpoint and routes requests to 8 LLM providers (OpenAI, DeepSeek, MoonshotAI, Gemini, GLM, MiniMax, ByteDance, plus a shared OpenAI-compatible base). Clients specify a model name, and the gateway resolves it to the correct provider via a routing table. All responses stream back via SSE. Request analytics (latency, TTFT, token usage, cost) are logged to SQLite.

## Goals

1. Provide a single HTTP endpoint that routes to any provider based on the `model` field
2. Support 8+ providers through a shared OpenAI-compatible base and native SDK integration
3. Stream all responses via SSE for real-time token delivery
4. Track request analytics: latency, TTFT, token usage, cost per request
5. Expose analytics via REST endpoints for monitoring and cost visibility
6. Require minimal configuration and zero infrastructure dependencies

## Target Users

- Developers building AI-powered features who need provider flexibility
- Teams evaluating multiple LLM providers without rewriting integration code
- Internal services that proxy LLM calls through a centralized gateway
- Platform teams needing cost and usage visibility across LLM providers

## Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1 | Accept OpenAI-style chat completion requests via `POST /v1/chat/completions` | Must | Done |
| FR-2 | Route requests to provider based on `model` field via `MODEL_ROUTING` dict | Must | Done |
| FR-3 | Stream response tokens as SSE events | Must | Done |
| FR-4 | Support `messages` array with `user` and `assistant` roles | Must | Done |
| FR-5 | Support optional `system_prompt` parameter | Must | Done |
| FR-6 | Authenticate requests via Bearer token (`APP_API_KEY`) | Must | Done |
| FR-7 | Route to OpenAI provider | Must | Done |
| FR-8 | Route to DeepSeek provider | Must | Done |
| FR-9 | Route to MoonshotAI (Kimi) provider | Must | Done |
| FR-10 | Route to Gemini provider via `google-genai` SDK | Must | Done |
| FR-11 | Route to GLM (Z.AI) provider | Must | Done |
| FR-12 | Route to MiniMax provider | Must | Done |
| FR-13 | Route to ByteDance (Doubao) provider | Must | Done |
| FR-14 | List available models via `GET /v1/models` | Must | Done |
| FR-15 | Log request analytics (tokens, latency, TTFT, cost) to SQLite | Must | Done |
| FR-16 | Expose analytics summary via `GET /v1/analytics/summary` | Must | Done |
| FR-17 | Expose per-model stats via `GET /v1/analytics/models` | Must | Done |
| FR-18 | Expose recent requests via `GET /v1/analytics/requests` | Must | Done |
| FR-19 | Calculate cost per request using model pricing table | Must | Done |
| FR-20 | Extract token usage from provider responses | Must | Done |
| FR-21 | Return structured error payloads in SSE stream on failure | Must | Done |
| FR-22 | Per-provider API key support with `LLM_API_KEY` fallback | Should | Done |

## Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Response latency overhead | < 50ms added by gateway (excluding LLM response time) |
| NFR-2 | Dependencies | Only runtime essentials (FastAPI, provider SDKs, pydantic-settings, aiosqlite) |
| NFR-3 | Configuration | Single `.env` file, no external config stores |
| NFR-4 | Startup time | < 3 seconds to first request readiness |
| NFR-5 | Analytics performance | Fire-and-forget logging, no blocking of response stream |
| NFR-6 | DB concurrency | SQLite WAL mode for concurrent read/write |

## Success Metrics

- All 8 providers return streamed tokens end-to-end
- Model routing requires zero code changes (routing table only)
- Analytics capture latency, TTFT, tokens, and cost for every request
- Unauthorized requests rejected with 401
- Analytics endpoints return aggregated and per-model stats

## Out of Scope (Phase 2)

- Request queuing or rate limiting
- Conversation history persistence
- Docker containerization
- Structured logging or observability (Prometheus, OpenTelemetry)
- Horizontal scaling / load balancing
- API versioning

## Related Docs

- [Codebase Summary](./codebase-summary.md)
- [System Architecture](./system-architecture.md)
- [Code Standards](./code-standards.md)
- [Deployment Guide](./deployment-guide.md)
- [Project Roadmap](./project-roadmap.md)
