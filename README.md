# LLM Gateway

A FastAPI-based API gateway that routes chat completion requests to multiple LLM providers via model-based routing. Clients specify a model name, and the gateway resolves it to the correct provider. All responses stream via SSE. Request analytics (latency, TTFT, token usage, cost) are logged to SQLite.

## Features

- **Model-based routing** -- client specifies `model`, gateway resolves to provider via routing table
- **8 providers** -- OpenAI, DeepSeek, MoonshotAI (Kimi), Gemini, Z.AI (GLM), MiniMax, ByteDance (Doubao)
- **OpenAI-compatible API** -- standard `/v1/chat/completions` endpoint
- **Server-Sent Events streaming** -- real-time token delivery with usage metadata
- **Analytics pipeline** -- SQLite-backed request logging with cost tracking, TTFT, latency
- **Analytics API** -- summary stats, per-model breakdowns, recent requests
- **Bearer token authentication** -- simple API key gating
- **Per-provider API keys** -- dedicated env vars per provider with shared fallback

## Quick Start

### Prerequisites

- Python 3.12+
- API key from at least one supported provider

### Install

```bash
make install
```

Creates a `.venv` and installs dependencies.

### Configure

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# At least one provider API key
OPENAI_API_KEY=your-openai-key
DEEPSEEK_API_KEY=your-deepseek-key
MOONSHOT_API_KEY=your-moonshot-key
GLM_API_KEY=your-glm-key
LLM_API_KEY=your-gemini-or-minimax-key

# Gateway auth
APP_API_KEY=your-gateway-secret

# Analytics (optional)
ANALYTICS_DB_PATH=data/analytics.db
```

### Run

```bash
# Production (background)
make start

# Development (auto-reload)
make dev
```

Server starts at `http://0.0.0.0:8000`.

## API Reference

### POST /v1/chat/completions

Stream chat completions via SSE. The `model` field determines which provider handles the request.

**Headers:**

| Header | Value |
|--------|-------|
| `Authorization` | `Bearer <APP_API_KEY>` |
| `Content-Type` | `application/json` |

**Request Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `string` | required | Model name (see `GET /v1/models` for available models) |
| `messages` | `list[dict]` | required | OpenAI-style message array |
| `system_prompt` | `string` | `""` | System instruction |
| `stream` | `bool` | `true` | Enable streaming (always true) |

**Example:**

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer changeme" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "Hello"}],
    "system_prompt": "You are a helpful assistant"
  }'
```

**Response (SSE):**

```
data: {"token": "Hello"}

data: {"token": "!"}

data: [DONE]
```

On error:

```
data: {"error": "error message"}
```

### GET /v1/models

List all available models from the routing table.

```bash
curl -H "Authorization: Bearer changeme" http://localhost:8000/v1/models
```

Returns OpenAI-compatible model list with `id`, `object`, `owned_by` fields.

### GET /v1/analytics/summary

Aggregate stats across all requests.

| Query Param | Type | Description |
|-------------|------|-------------|
| `since` | `string` | ISO 8601 datetime filter |

```bash
curl -H "Authorization: Bearer changeme" \
  "http://localhost:8000/v1/analytics/summary?since=2025-01-01T00:00:00Z"
```

Returns: `total_requests`, `total_tokens`, `total_cost_usd`, `avg_latency_ms`, `avg_ttft_ms`, `error_rate`.

### GET /v1/analytics/models

Per-model usage stats grouped by model and provider.

| Query Param | Type | Description |
|-------------|------|-------------|
| `since` | `string` | ISO 8601 datetime filter |
| `provider` | `string` | Filter by provider name |

### GET /v1/analytics/requests

Paginated list of recent requests.

| Query Param | Type | Default | Description |
|-------------|------|---------|-------------|
| `since` | `string` | -- | ISO 8601 datetime filter |
| `limit` | `int` | 50 | Max results (1-200) |
| `offset` | `int` | 0 | Pagination offset |

### GET /health

Health check endpoint (no auth required).

```bash
curl http://localhost:8000/health
```

Returns `{"status": "ok"}`.

## Configuration

All settings via `.env` file or environment variables.

### Gateway Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_API_KEY` | Yes | `changeme` | Gateway authentication token |
| `ANALYTICS_DB_PATH` | No | `data/analytics.db` | SQLite database path for analytics |

### Provider API Keys

| Variable | Providers |
|----------|-----------|
| `OPENAI_API_KEY` | OpenAI (gpt-4o, gpt-4o-mini, o3) |
| `DEEPSEEK_API_KEY` | DeepSeek (deepseek-chat, deepseek-reasoner) |
| `MOONSHOT_API_KEY` | MoonshotAI (kimi-k2.5, moonshot-v1-128k) |
| `BYTEDANCE_API_KEY` | ByteDance Doubao (doubao-pro-*) |
| `GLM_API_KEY` | Z.AI GLM (glm-5.1, glm-4.7-flash, etc.) |
| `LLM_API_KEY` | Fallback key for Gemini, MiniMax (and any provider without a dedicated key) |

### Legacy (Single Provider Mode)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `gemini` | Legacy single-provider selection |
| `LLM_MODEL` | No | Provider default | Override model name |
| `LLM_BASE_URL` | No | Provider default | Override provider base URL |

## Supported Providers

| Provider | Default Model | Base URL | SDK |
|----------|---------------|----------|-----|
| OpenAI | `gpt-4o` | `api.openai.com/v1` | `openai` |
| DeepSeek | `deepseek-chat` | `api.deepseek.com` | `openai` (compatible) |
| MoonshotAI | `kimi-k2.5` | `api.moonshot.cn/v1` | `openai` (compatible) |
| Google Gemini | `gemini-2.5-flash` | N/A (native SDK) | `google-genai` |
| Z.AI GLM | `glm-4.7-flash` | `api.z.ai/api/paas/v4` | `openai` (compatible) |
| MiniMax | `MiniMax-Text-01` | `api.minimax.chat/v1` | `openai` (compatible) |
| ByteDance Doubao | *(endpoint ID)* | `ark.cn-beijing.volces.com/api/v3` | `openai` (compatible) |

## Architecture

```
Client --> POST /v1/chat/completions {model: "deepseek-chat", messages: [...]}
              |
              v
        Bearer Auth Check
              |
              v
        resolve_provider("deepseek-chat") --> ("deepseek", "deepseek-chat")
              |
              v
        create_provider("deepseek", "deepseek-chat") --> DeepSeekProvider
              |
              v
        _tracked_stream() --> SSE Response + analytics logging
```

- **Model routing**: `MODEL_ROUTING` dict maps model names to `(provider, model_id)` tuples
- **Provider hierarchy**: `LLMProvider` ABC, `GeminiProvider` (native SDK), `OpenAICompatibleProvider` base (6 providers)
- **Analytics**: SQLite with aiosqlite, tracks TTFT/latency/tokens/cost per request
- **Lifespan**: FastAPI lifespan initializes analytics DB on startup, closes on shutdown

See [docs/system-architecture.md](docs/system-architecture.md) for details.

## Development

```bash
make install          # Install dependencies
make dev              # Start with auto-reload
make test             # Run all tests (pytest)
make test-unit        # Unit tests only
make test-integration # Integration tests only
make health           # Health check
make stop             # Stop background server
make clean            # Remove __pycache__ and build artifacts
```

## License

Private repository. All rights reserved.
