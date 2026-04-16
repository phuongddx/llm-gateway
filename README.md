# LLM Gateway

A FastAPI-based API gateway that proxies chat completion requests to multiple LLM providers via a unified streaming SSE interface.

## Features

- **Multi-provider support** -- Gemini, GLM (ZhipuAI), MiniMax
- **OpenAI-compatible API** -- standard `/v1/chat/completions` endpoint
- **Server-Sent Events streaming** -- real-time token delivery
- **Bearer token authentication** -- simple API key gating
- **Provider factory pattern** -- swap providers via a single env var
- **Zero-config defaults** -- works out of the box with sensible model defaults

## Quick Start

### Prerequisites

- Python 3.12+
- An API key from at least one supported provider

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
LLM_PROVIDER=gemini
LLM_API_KEY=your-api-key-here
LLM_MODEL=gemini-2.5-flash
APP_API_KEY=your-gateway-secret
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

Stream chat completions via SSE.

**Headers:**

| Header | Value |
|--------|-------|
| `Authorization` | `Bearer <APP_API_KEY>` |
| `Content-Type` | `application/json` |

**Request Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `messages` | `list[dict]` | required | OpenAI-style message array |
| `system_prompt` | `string` | `""` | System instruction |
| `stream` | `bool` | `true` | Enable streaming (always true) |

**Example:**

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer changeme" \
  -H "Content-Type: application/json" \
  -d '{
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

### GET /health

Health check endpoint.

```bash
curl http://localhost:8000/health
```

Returns `{"status": "ok"}`.

## Configuration

All settings via `.env` file or environment variables.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | Yes | `gemini` | Provider: `gemini`, `glm`, `minimax` |
| `LLM_API_KEY` | Yes | -- | API key for the selected provider |
| `LLM_MODEL` | No | Provider default | Model name override |
| `APP_API_KEY` | Yes | `changeme` | Gateway authentication token |
| `LLM_BASE_URL` | No | Provider default | Override provider API base URL |

## Supported Providers

| Provider | `LLM_PROVIDER` | Default Model | SDK |
|----------|-----------------|---------------|-----|
| Google Gemini | `gemini` | `gemini-2.5-flash` | `google-genai` |
| ZhipuAI GLM | `glm` | `glm-4-flash` | `openai` (compatible) |
| MiniMax | `minimax` | `MiniMax-Text-01` | `openai` (compatible) |

## Architecture

```
Client --> POST /v1/chat/completions
              |
              v
        Bearer Auth Check
              |
              v
        create_provider() --> GeminiProvider | GLMProvider | MiniMaxProvider
              |
              v
        provider.chat_stream() --> SSE Response
```

- **Provider pattern**: Abstract `LLMProvider` base class with `chat_stream()` async generator
- **Factory dispatch**: `create_provider()` selects implementation based on `LLM_PROVIDER` env var
- **OpenAI-compatible providers** (GLM, MiniMax) share identical code via `AsyncOpenAI` client
- **Gemini** uses native `google-genai` SDK with OpenAI-to-Gemini role mapping

See [docs/system-architecture.md](docs/system-architecture.md) for details.

## Development

```bash
make install    # Install dependencies
make dev        # Start with auto-reload
make test       # Test chat endpoint (requires .env)
make health     # Health check
make stop       # Stop background server
make clean      # Remove __pycache__ and build artifacts
```

## License

Private repository. All rights reserved.
