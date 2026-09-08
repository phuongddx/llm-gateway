"""Chat completions endpoint with tracked streaming analytics."""

import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from analytics.cost import calculate_cost, estimate_credits
from analytics.routing import resolve_provider
from config import settings
from providers import create_provider
from rate_limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    model: str = "auto"
    messages: list[dict]
    system_prompt: str = ""
    stream: bool = True
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None


def verify_auth(authorization: str = Header(...)):
    """Bearer token authentication dependency."""
    # Use removeprefix to avoid replacing "Bearer " inside the token value
    token = authorization.removeprefix("Bearer ").removeprefix("bearer ")
    if token != settings.app_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/v1/chat/completions")
@limiter.limit(settings.rate_limit)
async def chat(request: Request, body: ChatRequest, _auth=Depends(verify_auth)):  # noqa: B008 -- FastAPI DI convention
    # Resolve model name to (provider, actual_model_id) — passthrough for unknown models
    provider_name, model_id = resolve_provider(body.model)

    provider = create_provider(provider_name, model_id)
    analytics_writer = getattr(request.app.state, "analytics_writer", None)

    gen_params = None
    if body.temperature is not None or body.max_tokens is not None or body.top_p is not None:
        gen_params = {}
        if body.temperature is not None:
            gen_params["temperature"] = body.temperature
        if body.max_tokens is not None:
            gen_params["max_tokens"] = body.max_tokens
        if body.top_p is not None:
            gen_params["top_p"] = body.top_p

    return StreamingResponse(
        _tracked_stream(provider, body, provider_name, model_id, analytics_writer, gen_params),
        media_type="text/event-stream",
    )


async def _tracked_stream(
    provider, request: ChatRequest, provider_name: str, model_id: str, analytics_writer, gen_params=None
):
    """Wrap provider.chat_stream() with analytics tracking."""
    request_id = str(uuid4())
    start_time = time.monotonic()
    first_token_time: float | None = None
    usage_data = None
    token_count = 0
    error_msg: str | None = None

    try:
        async for token, usage in provider.chat_stream(request.messages, request.system_prompt, gen_params):
            if usage:
                usage_data = usage
            elif token:
                if first_token_time is None:
                    first_token_time = time.monotonic()
                token_count += len(token) // 4  # Approximate token count
                yield f"data: {json.dumps({'token': token})}\n\n"

    except Exception as e:  # noqa: BLE001 -- must never crash the request; see AGENTS.md Error handling
        error_msg = str(e)
        logger.error("Provider stream error: %s", error_msg)
        client_msg = "Internal error processing request"
        err_type, err_code = "server_error", None
        if provider_name == "zai-coding":
            status = getattr(e, "status_code", None)
            if status == 429 or "1113" in error_msg:
                client_msg = "zai-coding quota exhausted — resets within the 5-hour window"
                err_type, err_code = "rate_limit_error", "zai_quota_exhausted"
            elif status in (401, 403):
                client_msg = "zai-coding authentication failed"
                err_type, err_code = "authentication_error", "zai_auth_failed"
        error_obj = {"message": client_msg, "type": err_type}
        if err_code is not None:
            error_obj["code"] = err_code
        yield f"data: {json.dumps({'error': error_obj})}\n\n"

    finally:
        # Calculate metrics
        latency_ms = int((time.monotonic() - start_time) * 1000)
        ttft_ms = int((first_token_time - start_time) * 1000) if first_token_time else 0

        prompt_tokens = usage_data["prompt_tokens"] if usage_data else 0
        completion_tokens = usage_data["completion_tokens"] if usage_data else token_count
        total_tokens = usage_data["total_tokens"] if usage_data else (prompt_tokens + completion_tokens)
        cost_usd = calculate_cost(model_id, prompt_tokens, completion_tokens)
        credits_used = estimate_credits(
            provider_name, model_id, usage_data or {}, datetime.now(timezone.utc)
        )

        # Enqueue the log row — non-blocking on the bounded analytics queue
        # (the finally runs exactly once per generator, incl. client disconnect)
        if analytics_writer:
            analytics_writer.enqueue({
                "id": request_id,
                "provider": provider_name,
                "model": model_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": latency_ms,
                "ttft_ms": ttft_ms,
                "cost_usd": cost_usd,
                "credits_used": credits_used,
                "status": "error" if error_msg else "success",
                "error_message": error_msg,
            })

    yield "data: [DONE]\n\n"

