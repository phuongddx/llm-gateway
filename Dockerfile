# syntax=docker/dockerfile:1
# ^ keeps BuildKit on latest stable frontend [CITED: docs.docker.com/reference/dockerfile §syntax]

FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
# --system users via Debian useradd (passwd pkg is required-pack in slim) [ASSUMED: A2 — smoke-verifiable]
RUN groupadd --system gateway && useradd --system --gid gateway gateway \
    && mkdir -p /app/data && chown gateway:gateway /app/data
COPY --from=builder /opt/venv /opt/venv
COPY main.py config.py rate_limiter.py ./
COPY analytics ./analytics
COPY routes ./routes
COPY providers ./providers
COPY static ./static
USER gateway
EXPOSE 8000
# exit 0 = healthy, 1 = unhealthy; defaults: interval 30s, timeout 30s, retries 3
# [CITED: docs.docker.com/reference/dockerfile §HEALTHCHECK]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)" || exit 1
# exec form → uvicorn is PID 1, receives SIGTERM directly (verified graceful)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
