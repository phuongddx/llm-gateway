"""Tests for OBSV-01: /metrics Prometheus exposition + /health/live + /health/ready."""

import pytest

import metrics


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Isolate each test from module-level counter/histogram state."""
    for name in ("_requests_total", "_duration_bucket_counts", "_duration_sum", "_duration_count"):
        obj = getattr(metrics, name, None)
        if obj is not None:
            obj.clear()
    yield


def test_render_empty_state_has_only_help_type_lines():
    """A fresh module renders valid exposition text with zero sample lines."""
    output = metrics.render()
    assert "# HELP gateway_requests_total" in output
    assert "# TYPE gateway_requests_total counter" in output
    assert "# HELP gateway_request_duration_seconds" in output
    assert "# TYPE gateway_request_duration_seconds histogram" in output
    assert "gateway_requests_total{" not in output
    assert "gateway_request_duration_seconds_bucket{" not in output


def test_render_after_record_request_includes_counter_and_histogram_samples():
    """record_request() produces a counter sample and a histogram whose +Inf
    bucket equals the total count for that provider/model pair."""
    metrics.record_request("zai-coding", "glm-5.3", "success", 0.02)

    output = metrics.render()
    assert 'gateway_requests_total{provider="zai-coding",model="glm-5.3",status="success"} 1' in output

    inf_line = (
        'gateway_request_duration_seconds_bucket{provider="zai-coding",'
        'model="glm-5.3",le="+Inf"} 1'
    )
    count_line = (
        'gateway_request_duration_seconds_count{provider="zai-coding",model="glm-5.3"} 1'
    )
    assert inf_line in output
    assert count_line in output


@pytest.mark.asyncio
async def test_health_live_returns_ok(client):
    """GET /health/live always returns 200 {"status": "ok"}."""
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_ready_returns_ready_when_state_present(client):
    """GET /health/ready returns 200 when analytics_db/analytics_writer are set
    (the `client` fixture always injects both)."""
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text(client):
    """GET /metrics is unauthenticated and returns text/plain exposition."""
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "gateway_requests_total" in response.text


@pytest.mark.asyncio
async def test_chat_request_is_recorded_in_metrics(client, auth_headers):
    """A successful chat completion shows up as a gateway_requests_total sample."""
    from unittest.mock import AsyncMock, patch

    mock_provider = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield ("Hi", None)
        yield ("", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

    mock_provider.chat_stream = mock_stream

    with patch("routes.chat.create_provider", return_value=mock_provider):
        await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            headers=auth_headers,
        )

    metrics_response = await client.get("/metrics")
    assert 'gateway_requests_total{provider="manifest",model="gpt-4o",status="success"}' in metrics_response.text
