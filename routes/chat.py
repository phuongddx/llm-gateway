"""Chat completions endpoint with tracked streaming analytics."""

import asyncio
import json
import logging
import os
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from analytics.cost import calculate_cost
from analytics.routing import resolve_provider
from config import settings
from rate_limiter import limiter
from providers import create_provider

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    model: str  # Required — gateway resolves to provider via routing table
    messages: list[dict]
    system_prompt: str = ""
    stream: bool = True


def verify_auth(authorization: str = Header(...)):
    """Bearer token authentication dependency."""
    # Use removeprefix to avoid replacing "Bearer " inside the token value
    token = authorization.removeprefix("Bearer ").removeprefix("bearer ")
    if token != settings.app_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/v1/chat/completions")
@limiter.limit(settings.rate_limit)
async def chat(request: Request, body: ChatRequest, _auth=Depends(verify_auth)):
    # Resolve model name to (provider, actual_model_id)
    try:
        provider_name, model_id = resolve_provider(body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    provider = create_provider(provider_name, model_id)
    analytics_db = getattr(request.app.state, "analytics_db", None)
    return StreamingResponse(
        _tracked_stream(provider, body, provider_name, model_id, analytics_db),
        media_type="text/event-stream",
    )


async def _tracked_stream(
    provider, request: ChatRequest, provider_name: str, model_id: str, analytics_db
):
    """Wrap provider.chat_stream() with analytics tracking."""
    request_id = str(uuid4())
    start_time = time.monotonic()
    first_token_time: float | None = None
    usage_data = None
    token_count = 0
    error_msg: str | None = None

    try:
        async for token, usage in provider.chat_stream(request.messages, request.system_prompt):
            if usage:
                usage_data = usage
            elif token:
                if first_token_time is None:
                    first_token_time = time.monotonic()
                token_count += len(token) // 4  # Approximate token count
                yield f"data: {json.dumps({'token': token})}\n\n"

    except Exception as e:
        error_msg = str(e)
        logger.error("Provider stream error: %s", error_msg)
        yield f"data: {json.dumps({'error': 'Internal error processing request'})}\n\n"

    finally:
        # Calculate metrics
        latency_ms = int((time.monotonic() - start_time) * 1000)
        ttft_ms = int((first_token_time - start_time) * 1000) if first_token_time else 0

        prompt_tokens = usage_data["prompt_tokens"] if usage_data else 0
        completion_tokens = usage_data["completion_tokens"] if usage_data else token_count
        total_tokens = usage_data["total_tokens"] if usage_data else (prompt_tokens + completion_tokens)
        cost_usd = calculate_cost(model_id, prompt_tokens, completion_tokens)

        # Fire-and-forget DB log with reference held to prevent GC
        if analytics_db:
            try:
                task = asyncio.create_task(analytics_db.log_request({
                    "id": request_id,
                    "provider": provider_name,
                    "model": model_id,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": latency_ms,
                    "ttft_ms": ttft_ms,
                    "cost_usd": cost_usd,
                    "status": "error" if error_msg else "success",
                    "error_message": error_msg,
                }))
                task.add_done_callback(_on_log_task_done)
            except Exception:
                logger.exception("Failed to queue analytics log")

    yield "data: [DONE]\n\n"


def _on_log_task_done(task: asyncio.Task):
    """Handle errors from fire-and-forget analytics log tasks."""
    if task.cancelled():
        return
    if exc := task.exception():
        logger.error("Analytics log task failed: %s", exc)
