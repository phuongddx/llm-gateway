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
# Required: LLM_API_KEY, APP_API_KEY
# Optional: LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL
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
# Expected: SSE stream with tokens
```

### Stop

```bash
make stop
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | Yes | `gemini` | Which LLM provider to use. Options: `gemini`, `glm`, `minimax` |
| `LLM_API_KEY` | Yes | -- | API key for the selected LLM provider |
| `LLM_MODEL` | No | Provider default | Override the default model name |
| `APP_API_KEY` | Yes | `changeme` | Bearer token for gateway authentication |
| `LLM_BASE_URL` | No | Provider default | Override the provider API base URL |

### Default Models by Provider

| Provider | Default Model |
|----------|---------------|
| `gemini` | `gemini-2.5-flash` |
| `glm` | `glm-4-flash` |
| `minimax` | `MiniMax-Text-01` |

### Default Base URLs by Provider

| Provider | Default Base URL |
|----------|------------------|
| `gemini` | N/A (uses SDK default) |
| `glm` | `https://open.bigmodel.cn/api/paas/v4` |
| `minimax` | `https://api.minimax.chat/v1` |

## Production Deployment

### Direct Deployment

```bash
# 1. Install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Set environment variables (use secrets manager, not .env file in production)
export LLM_PROVIDER=gemini
export LLM_API_KEY=your-production-key
export APP_API_KEY=$(cat /run/secrets/app_api_key)

# 3. Run with uvicorn
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Recommended Production Settings

- **Workers**: Run multiple uvicorn workers behind a reverse proxy (nginx, caddy)
- **TLS**: Terminate TLS at the reverse proxy, not in uvicorn
- **Secrets**: Use environment variables or secrets manager, never commit `.env` to version control
- **Logging**: Configure Python logging to output structured JSON
- **Health checks**: Use `GET /health` for load balancer health checks

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
FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Run:
```bash
docker build -t llm-gateway .
docker run -e LLM_PROVIDER=gemini \
           -e LLM_API_KEY=your-key \
           -e APP_API_KEY=your-secret \
           -p 8000:8000 llm-gateway
```

## Troubleshooting

### Server won't start

- Check port 8000 is not in use: `lsof -i :8000`
- Verify `.env` exists: `make start` auto-creates from `.env.example` if missing

### 401 Unauthorized

- Confirm `APP_API_KEY` in `.env` matches the `Authorization: Bearer <token>` header
- Default `APP_API_KEY` is `changeme` -- change it in production

### Provider errors in SSE stream

- Verify `LLM_API_KEY` is valid for the selected provider
- Check `LLM_BASE_URL` is correct if overridden
- Check provider API status (Google AI, ZhipuAI, MiniMax)

### No tokens in response

- Some models require specific message formats
- Ensure `messages` array contains at least one message
- Check server logs: `cat server.log`

## Related Docs

- [Project Overview & PDR](./project-overview-pdr.md)
- [System Architecture](./system-architecture.md)
- [Code Standards](./code-standards.md)
