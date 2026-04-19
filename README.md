# LLM Gateway

A FastAPI-based API gateway that routes chat completion requests through Manifest (app.manifest.build), providing access to 500+ LLM models via smart routing. Clients specify a model name (or `auto` for intelligent selection). All responses stream via SSE. Request analytics (latency, TTFT, token usage) are logged to SQLite.

## Features

- **Manifest provider** -- single API key routes to 500+ models via app.manifest.build
- **Smart routing** -- `model="auto"` lets Manifest pick the best model automatically
- **Model passthrough** -- unknown model names are forwarded to Manifest as-is
- **OpenAI-compatible API** -- standard `/v1/chat/completions` endpoint
- **Server-Sent Events streaming** -- real-time token delivery with usage metadata
- **Analytics pipeline** -- SQLite-backed request logging with TTFT, latency tracking
- **Analytics API** -- summary stats, per-model breakdowns, recent requests
- **Bearer token authentication** -- simple API key gating

## Quick Start

### Prerequisites

- Python 3.12+
- Manifest API key from [app.manifest.build](https://app.manifest.build)

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
# Manifest API key — routes to 500+ models
MANIFEST_API_KEY=your-manifest-api-key

# Gateway auth — REQUIRED
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
    "model": "auto",
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
| `APP_API_KEY` | Yes | -- | Gateway authentication token |
| `MANIFEST_API_KEY` | Yes | -- | Manifest API key for 500+ models |
| `LLM_API_KEY` | No | -- | Fallback if `MANIFEST_API_KEY` not set |
| `ANALYTICS_DB_PATH` | No | `data/analytics.db` | SQLite database path for analytics |
| `CORS_ORIGINS` | No | -- | Comma-separated allowed origins |
| `RATE_LIMIT` | No | `60/minute` | Rate limit per client IP |

### Legacy (Single Provider Mode)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `gemini` | Legacy single-provider selection |
| `LLM_MODEL` | No | `gemini-2.0-flash-lite` | Override model name |
| `LLM_BASE_URL` | No | Provider default | Override provider base URL |

## Supported Models

All models route through Manifest (app.manifest.build). Use `model="auto"` for smart routing, or specify any model name directly.

| Alias | Routed Model | Family |
|-------|-------------|--------|
| `auto` | Manifest smart routing | Any |
| `gpt-5.4` | `gpt-5.4` | OpenAI |
| `gpt-4o` | `gpt-4o` | OpenAI |
| `gpt-4o-mini` | `gpt-4o-mini` | OpenAI |
| `o3` | `o3` | OpenAI |
| `claude-sonnet` | `claude-sonnet-4-6` | Anthropic |
| `claude-haiku` | `claude-haiku-4-5-20251001` | Anthropic |
| `gemini-2.5-flash` | `gemini-2.5-flash` | Google |
| `gemini-2.0-flash` | `gemini-2.0-flash` | Google |
| `gemini-2.0-flash-lite` | `gemini-2.0-flash-lite` | Google |
| `deepseek-chat` | `deepseek-chat` | DeepSeek |
| `deepseek-reasoner` | `deepseek-reasoner` | DeepSeek |
| `kimi-k2.5` | `kimi-k2.5` | MoonshotAI |
| `glm-5.1` | `glm-5.1` | Z.AI |
| `MiniMax-Text-01` | `MiniMax-Text-01` | MiniMax |
| `doubao-pro-32k` | `doubao-pro-32k` | ByteDance |

Unknown model names pass through to Manifest as-is, giving access to the full 500+ model catalog.

## Architecture

```
Client --> POST /v1/chat/completions {model: "auto", messages: [...]}
              |
              v
        Bearer Auth Check
              |
              v
        resolve_provider("auto") --> ("manifest", "auto")
              |
              v
        create_provider("manifest", "auto") --> ManifestProvider
              |
              v
        _tracked_stream() --> SSE Response + analytics logging
```

- **Model routing**: `MODEL_ROUTING` dict maps model aliases to `(provider, model_id)` tuples; all point to `"manifest"`, unknown models pass through
- **Single provider**: `ManifestProvider` extends `OpenAICompatibleProvider`, connects to `app.manifest.build/v1`
- **Cost tracking**: Returns `0.0` -- Manifest handles billing internally
- **Analytics**: SQLite with aiosqlite, tracks TTFT/latency/tokens per request
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
