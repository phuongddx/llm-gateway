# Deployment Guide

## Local Development

### Setup

```bash
# 1. Clone and enter project
cd llm-gateway

# 2. Create virtual environment and install dependencies
make install

# 3. Create .env from template
cp .env.example .env

# 4. Edit .env with your API keys
# Required: at least one provider API key, APP_API_KEY
# See Environment Variables section below
```

### Run

```bash
# Development (auto-reload on file changes)
make dev

# Production (background process)
make start
```

Server runs on `http://0.0.0.0:8000` by default.

### Verify

```bash
make health
# Expected: {"status": "ok"}

make test
# Expected: all pytest tests pass
```

### Stop

```bash
make stop
```

## Environment Variables Reference

### Core Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_API_KEY` | Yes | `changeme` | Bearer token for gateway authentication |
| `ANALYTICS_DB_PATH` | No | `data/analytics.db` | SQLite database path for analytics |

### Provider API Keys

| Variable | Description |
|----------|-------------|
| `LLM_API_KEY` | Legacy fallback key (used if per-provider key not set) |
| `OPENAI_API_KEY` | OpenAI API key (gpt-4o, gpt-4o-mini, o3) |
| `DEEPSEEK_API_KEY` | DeepSeek API key (deepseek-chat, deepseek-reasoner) |
| `MOONSHOT_API_KEY` | MoonshotAI API key (kimi-k2.5, moonshot-v1-128k) |
| `BYTEDANCE_API_KEY` | ByteDance Doubao API key (doubao-pro-*) |

Note: Gemini, GLM, and MiniMax use `LLM_API_KEY` as their provider key (no dedicated env var). Set `LLM_API_KEY` if using these providers.

### Legacy Settings (still supported)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `gemini` | Legacy single-provider mode |
| `LLM_MODEL` | No | Provider default | Override model name |
| `LLM_BASE_URL` | No | Provider default | Override provider API base URL |

### Default Models by Provider

| Provider | Default Model | Base URL |
|----------|---------------|----------|
| `openai` | `gpt-4o` | `https://api.openai.com/v1` |
| `deepseek` | `deepseek-chat` | `https://api.deepseek.com` |
| `moonshot` | `kimi-k2.5` | `https://api.moonshot.cn/v1` |
| `gemini` | `gemini-2.5-flash` | N/A (uses SDK default) |
| `glm` | `glm-4-flash` | `https://open.bigmodel.cn/api/paas/v4` |
| `minimax` | `MiniMax-Text-01` | `https://api.minimax.chat/v1` |
| `bytedance` | *(endpoint ID required)* | `https://ark.cn-beijing.volces.com/api/v3` |

## Production Deployment

### Direct Deployment

```bash
# 1. Install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Set environment variables (use secrets manager, not .env file in production)
export APP_API_KEY=$(cat /run/secrets/app_api_key)
export OPENAI_API_KEY=$(cat /run/secrets/openai_key)
export DEEPSEEK_API_KEY=$(cat /run/secrets/deepseek_key)
export ANALYTICS_DB_PATH=/data/analytics.db

# 3. Run with uvicorn
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Recommended Production Settings

- **Workers**: Run multiple uvicorn workers behind a reverse proxy (nginx, caddy)
- **TLS**: Terminate TLS at the reverse proxy, not in uvicorn
- **Secrets**: Use environment variables or secrets manager, never commit `.env` to version control
- **Logging**: Configure Python logging to output structured JSON
- **Health checks**: Use `GET /health` for load balancer health checks
- **Analytics DB**: Store on persistent volume, `data/` dir is auto-created on startup

### Process Manager

Use systemd, supervisord, or similar to manage the uvicorn process:

```ini
# /etc/systemd/system/llm-gateway.service
[Unit]
Description=LLM Gateway
After=network.target

[Service]
Type=simple
User=llm-gateway
WorkingDirectory=/opt/llm-gateway
EnvironmentFile=/opt/llm-gateway/.env
ExecStart=/opt/llm-gateway/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

## Docker (Future)

Not yet implemented. Planned approach:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Run:
```bash
docker build -t llm-gateway .
docker run -e APP_API_KEY=your-secret \
           -e OPENAI_API_KEY=your-key \
           -v /persistent/analytics.db:/data/analytics.db \
           -p 8000:8000 llm-gateway
```

## Troubleshooting

### Server won't start

- Check port 8000 is not in use: `lsof -i :8000`
- Verify `.env` exists: `make start` auto-creates from `.env.example` if missing
- Check analytics DB path is writable: `ANALYTICS_DB_PATH` defaults to `data/analytics.db`

### 401 Unauthorized

- Confirm `APP_API_KEY` in `.env` matches the `Authorization: Bearer <token>` header
- Default `APP_API_KEY` is `changeme` -- change it in production

### 400 Unknown model

- Check model name matches an entry in the routing table
- Use `GET /v1/models` to list all available models
- Model names are case-sensitive

### Provider errors in SSE stream

- Verify provider-specific API key is set (e.g., `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`)
- If using Gemini/GLM/MiniMax: set `LLM_API_KEY`
- Check provider API status page for outages

### Analytics not recording

- Verify `ANALYTICS_DB_PATH` is writable
- Check server logs for analytics DB errors
- Ensure `data/` directory exists (auto-created on startup)

## Related Docs

- [Project Overview & PDR](./project-overview-pdr.md)
- [System Architecture](./system-architecture.md)
- [Code Standards](./code-standards.md)
