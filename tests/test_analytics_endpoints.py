"""Integration tests for GET /v1/analytics/* and GET /v1/models endpoints."""

import pytest


@pytest.mark.asyncio
async def test_list_models(client, auth_headers):
    """GET /v1/models returns OpenAI-compatible model list."""
    response = await client.get("/v1/models", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0
    # Verify structure
    model = data["data"][0]
    assert "id" in model
    assert model["object"] == "model"
    assert "owned_by" in model


@pytest.mark.asyncio
async def test_list_models_requires_auth(client):
    """GET /v1/models returns 422/401 without auth header."""
    response = await client.get("/v1/models")
    # FastAPI returns 422 when required Header(...) is missing
    assert response.status_code in (401, 403, 422)


@pytest.mark.asyncio
async def test_analytics_summary_empty(client, auth_headers):
    """GET /v1/analytics/summary works with empty DB."""
    response = await client.get("/v1/analytics/summary", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_requests"] == 0
    assert "avg_latency_ms" in data
    assert "error_rate" in data


@pytest.mark.asyncio
async def test_analytics_summary_with_data(client, auth_headers, analytics_db):
    """GET /v1/analytics/summary returns aggregate stats."""
    await analytics_db.log_request({
        "id": "test-001",
        "provider": "openai",
        "model": "gpt-4o",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 300,
        "ttft_ms": 80,
        "cost_usd": 0.0075,
        "status": "success",
    })

    response = await client.get("/v1/analytics/summary", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_requests"] == 1
    assert data["total_prompt_tokens"] == 100


@pytest.mark.asyncio
async def test_analytics_models(client, auth_headers, analytics_db):
    """GET /v1/analytics/models returns per-model breakdown."""
    await analytics_db.log_request({
        "id": "test-001",
        "provider": "openai",
        "model": "gpt-4o",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 300,
        "ttft_ms": 80,
        "cost_usd": 0.0075,
        "status": "success",
    })

    response = await client.get("/v1/analytics/models", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["models"]) == 1
    assert data["models"][0]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_analytics_requests_pagination(client, auth_headers, analytics_db):
    """GET /v1/analytics/returns paginated results."""
    for i in range(5):
        await analytics_db.log_request({
            "id": f"test-{i:03d}",
            "provider": "openai",
            "model": "gpt-4o",
            "status": "success",
        })

    response = await client.get(
        "/v1/analytics/requests?limit=2&offset=0",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["requests"]) == 2
    assert data["total"] == 5


@pytest.mark.asyncio
async def test_analytics_endpoints_require_auth(client):
    """All analytics endpoints return 401 without auth."""
    for path in ["/v1/analytics/summary", "/v1/analytics/models", "/v1/analytics/requests"]:
        response = await client.get(path)
        # FastAPI returns 422 when required Header(...) is missing
        assert response.status_code in (401, 403, 422), f"{path} should require auth"


# --- GET /v1/analytics/credits ---


@pytest.mark.asyncio
async def test_credits_endpoint_requires_auth(client):
    # FastAPI returns 422 for a missing Authorization header (Header(...)
    # validation); an invalid token exercises verify_auth's 401 path.
    response = await client.get(
        "/v1/analytics/credits", headers={"Authorization": "Bearer invalid-token"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_credits_endpoint_empty(client, auth_headers):
    response = await client.get("/v1/analytics/credits", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["window_5h"] == {"credits_used": 0.0, "quota": 28000}
    assert body["window_7d_rolling"]["quota"] == 140000
    assert "rolling estimate" in body["window_7d_rolling"]["note"]
    assert body["by_model"] == {}
    assert body["off_peak_share"] is None


@pytest.mark.asyncio
async def test_credits_endpoint_aggregates_rows(client, auth_headers, analytics_db):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    for credits in (10.0, 25.5):
        await analytics_db.log_request({
            "id": f"c-{credits}",
            "provider": "zai-coding",
            "model": "glm-5.3",
            "credits_used": credits,
            "created_at": (now - timedelta(minutes=30)).isoformat(),
        })
    response = await client.get("/v1/analytics/credits", headers=auth_headers)
    body = response.json()
    assert body["window_5h"]["credits_used"] == pytest.approx(35.5)
    assert body["by_model"]["glm-5.3"]["requests"] == 2
