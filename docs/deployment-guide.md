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

All settings are read by `config.py`'s `Settings` class (pydantic `BaseSettings`, loads
from `.env`, unknown keys ignored):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_API_KEY` | Yes | none (must be set) | Bearer token for gateway authentication |
| `MANIFEST_API_KEY` | No | none | Manifest.build key -- routes to 500+ models |
| `ZAI_CODING_API_KEY` | No | none | Z.AI GLM Coding Plan key -- routes `glm-*` models to the z.ai coding endpoint; unset keeps GLM routing on Manifest |
| `ZAI_CREDITS_5H` | No | `28000` | GLM Coding Plan 5-hour credit quota (Max tier default) |
| `ZAI_CREDITS_WEEK` | No | `140000` | GLM Coding Plan weekly credit quota (Max tier default) |
| `LLM_API_KEY` | No | none | Fallback key used if `MANIFEST_API_KEY` or `ZAI_CODING_API_KEY` is not set |
| `CORS_ORIGINS` | No | empty | Comma-separated allowed origins (empty = no CORS headers) |
| `RATE_LIMIT` | No | `60/minute` | Max requests per window, per client IP |
| `RATE_LIMIT_PER_KEY` | No | `60/minute` | Max requests per window, per Bearer token -- applies independently alongside `RATE_LIMIT` |
| `ANALYTICS_DB_PATH` | No | `data/analytics.db` | SQLite database path for analytics |
| `ANALYTICS_QUEUE_SIZE` | No | `1000` | Bounded analytics write queue size (drop-newest when full) |
| `ANALYTICS_RETENTION_DAYS` | No | `90` | Analytics log retention in days (`0` = keep forever) |

## Production Deployment

### Direct Deployment

```bash
# 1. Install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Set environment variables (use secrets manager, not .env file in production)
export APP_API_KEY=$(cat /run/secrets/app_api_key)
export MANIFEST_API_KEY=$(cat /run/secrets/manifest_key)
export ZAI_CODING_API_KEY=$(cat /run/secrets/zai_coding_key)
export ANALYTICS_DB_PATH=/data/analytics.db

# 3. Run with uvicorn
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Recommended Production Settings

- **Workers**: Run multiple uvicorn workers behind a reverse proxy (nginx, caddy)
- **TLS**: Terminate TLS at the reverse proxy, not in uvicorn
- **Secrets**: Use environment variables or secrets manager, never commit `.env` to version control
- **Logging**: Configure Python logging to output structured JSON
- **Health checks**: Use `GET /health/live` for liveness and `GET /health/ready` for readiness/load-balancer health checks (the old single `/health` endpoint was removed with no back-compat alias)
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

## Docker / Compose Deployment

Build and run via Make targets, which wrap Docker/Compose directly:

```bash
# Build the image
make docker-build
# Equivalent to: docker build -t llm-gateway:latest .

# Start the gateway (builds the image and starts the container)
make docker-up
# Equivalent to: docker compose up -d --build

# Stop the gateway
make docker-down
# Equivalent to: docker compose down
```

The image is a multi-stage `python:3.12-slim` build (dependencies installed in a `builder`
stage, then copied into a slim runtime stage) that runs as a non-root `gateway` user, not
root.

`docker-compose.yml`:
- Mounts a named `gateway-data` volume at `/app/data`, matching the default
  `ANALYTICS_DB_PATH=data/analytics.db` (CWD-relative inside the container). The volume
  survives `docker compose down`; only `docker compose down -v` removes it.
- Passes configuration via `env_file: .env` (required -- the container errors loudly if
  `.env` is missing).
- Sets `restart: unless-stopped`.
- The container's `HEALTHCHECK` polls `GET /health/ready` every 30s
  (`--interval=30s --timeout=5s --start-period=10s --retries=3`).

An optional Prometheus sidecar is available behind a Compose profile -- it does not start
by default:

```bash
docker compose --profile observability up
```

This starts a pinned `prom/prometheus:v3.14.0` container, reachable at
`http://localhost:9090`, scraping the gateway's `/metrics` endpoint per
`prometheus/prometheus.yml`.

## Ngrok Tunnel (Local Expose)

Expose localhost:8000 to the internet via ngrok:

```bash
bash .ngrok/expose.sh
```

Static domain: `hyperpolysyllabically-saronic-mee.ngrok-free.app`

Requires ngrok installed and authenticated. Use for testing webhooks or remote access during development.

## Troubleshooting

### Server won't start

- Check port 8000 is not in use: `lsof -i :8000`
- Verify `.env` exists: `make start` auto-creates from `.env.example` if missing
- Check analytics DB path is writable: `ANALYTICS_DB_PATH` defaults to `data/analytics.db`

### 401 Unauthorized

- Confirm `APP_API_KEY` in `.env` matches the `Authorization: Bearer <token>` header
- `APP_API_KEY` has no default (empty) — the gateway aborts startup if unset; set it in `.env` before first run

### 400 Unknown model

- Check model name matches an entry in the routing table
- Use `GET /v1/models` to list all available models
- Model names are case-sensitive

### Provider errors in SSE stream

- Verify `MANIFEST_API_KEY` (or `LLM_API_KEY` fallback) is set for non-GLM models, and `ZAI_CODING_API_KEY` (or `LLM_API_KEY` fallback) is set for `glm-*` models to route to the z.ai coding endpoint -- without an effective z.ai key, GLM models silently degrade to Manifest with canonical ids (no error)
- Check provider API status page for outages

### Analytics not recording

- Verify `ANALYTICS_DB_PATH` is writable
- Check server logs for analytics DB errors
- Ensure `data/` directory exists (auto-created on startup)

## Related Docs

- [Project Overview & PDR](./project-overview-pdr.md)
- [System Architecture](./system-architecture.md)
- [Code Standards](./code-standards.md)
