"""Unit tests for analytics.writer — bounded queue, drop-newest, drain/stop."""

import json
from unittest.mock import patch

import pytest


class _QuotaError(Exception):
    status_code = 429


@pytest.mark.asyncio
async def test_error_stream_delivers_nested_frame_and_logs_row(
    client, auth_headers, analytics_writer, analytics_db
):
    """Mid-stream provider failure → nested OpenAI error frame + [DONE] + one request_logs row."""
    class QuotaProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            yield ("tok", None)
            raise _QuotaError("429 too many requests")

    with patch("routes.chat.create_provider", return_value=QuotaProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_headers,
        )

    assert response.status_code == 200

    frames = [
        json.loads(line[len("data: "):])
        for line in response.text.split("\n")
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert any("token" in frame for frame in frames)
    error_frames = [frame for frame in frames if "error" in frame]
    assert len(error_frames) == 1
    assert error_frames[0]["error"] == {
        "message": "zai-coding quota exhausted — resets within the 5-hour window",
        "type": "rate_limit_error",
        "code": "zai_quota_exhausted",
    }
    assert response.text.endswith("data: [DONE]\n\n")

    await analytics_writer.wait_drained(5.0)
    recent = await analytics_db.get_recent(limit=10)
    assert recent["total"] == 1
    assert recent["requests"][0]["status"] == "error"
