# Project Overview & Product Development Requirements

## Problem Statement

Applications that integrate with LLMs face vendor lock-in when they hardcode calls to a single provider. Switching providers requires rewriting API integration code, changing message formats, and updating authentication flows. Teams need a lightweight proxy that normalizes access to multiple LLM backends through a single, consistent interface.

## Product

**LLM Gateway** is a FastAPI-based API gateway that exposes an OpenAI-compatible chat completions endpoint and routes requests to multiple LLM providers (Gemini, GLM, MiniMax). All responses stream back to the client via Server-Sent Events.

## Goals

1. Provide a single HTTP endpoint that works identically regardless of the backend LLM provider
2. Enable provider switching via a single environment variable change
3. Stream all responses via SSE for real-time token delivery
4. Require minimal configuration and zero infrastructure dependencies

## Target Users

- Developers building AI-powered features who need provider flexibility
- Teams evaluating multiple LLM providers without rewriting integration code
- Internal services that proxy LLM calls through a centralized gateway

## Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Accept OpenAI-style chat completion requests via `POST /v1/chat/completions` | Must |
| FR-2 | Stream response tokens as SSE events | Must |
| FR-3 | Support `messages` array with `user` and `assistant` roles | Must |
| FR-4 | Support optional `system_prompt` parameter | Must |
| FR-5 | Authenticate requests via Bearer token (`APP_API_KEY`) | Must |
| FR-6 | Route to Gemini provider via `google-genai` SDK | Must |
| FR-7 | Route to GLM (ZhipuAI) provider via OpenAI-compatible API | Must |
| FR-8 | Route to MiniMax provider via OpenAI-compatible API | Must |
| FR-9 | Select provider via `LLM_PROVIDER` environment variable | Must |
| FR-10 | Override model name via `LLM_MODEL` environment variable | Should |
| FR-11 | Override provider base URL via `LLM_BASE_URL` | Should |
| FR-12 | Return health status via `GET /health` | Must |
| FR-13 | Return structured error payloads in SSE stream on failure | Must |
| FR-14 | Map OpenAI `system` role to appropriate provider equivalent | Must |

## Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Response latency overhead | < 50ms added by gateway (excluding LLM response time) |
| NFR-2 | Codebase size | Minimal -- under 250 LOC total |
| NFR-3 | Dependencies | Only runtime essentials (FastAPI, provider SDKs, pydantic-settings) |
| NFR-4 | Configuration | Single `.env` file, no external config stores |
| NFR-5 | Startup time | < 3 seconds to first request readiness |

## Success Metrics

- All three providers (Gemini, GLM, MiniMax) return streamed tokens end-to-end
- Provider switch requires exactly one env var change, zero code changes
- Gateway passes through tokens with no content corruption
- Unauthorized requests are rejected with 401

## Out of Scope (Phase 1)

- Request queuing or rate limiting
- Token counting or cost tracking
- Conversation history persistence
- Multiple concurrent provider support (A/B routing)
- Docker containerization
- Structured logging or observability

## Related Docs

- [Codebase Summary](./codebase-summary.md)
- [System Architecture](./system-architecture.md)
- [Code Standards](./code-standards.md)
- [Deployment Guide](./deployment-guide.md)
- [Project Roadmap](./project-roadmap.md)
