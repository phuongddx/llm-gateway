"""Shared base class for OpenAI-compatible API providers."""

import logging
from collections.abc import AsyncGenerator

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from providers.base import LLMProvider, StreamChunk, UsageData

logger = logging.getLogger(__name__)

# Allow-list, not a deny-list: only affirmatively-transient exception types are
# retried. z.ai quota (429 -> RateLimitError) and auth (401/403 ->
# AuthenticationError/PermissionDeniedError) are excluded BY OMISSION, which
# also safely excludes the z.ai "1113" balance-exhaustion error even though it
# arrives under a non-429 status code (existing test fixtures model it as
# status_code=402) -- an allow-list can't accidentally retry an exception type
# it was never told to retry (ZAI-3).
_RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError)


class OpenAICompatibleProvider(LLMProvider):
    """Base for providers using the OpenAI-compatible chat completions API.

    Subclasses set class-level base_url and default_model.
    """

    base_url: str = ""
    default_model: str = ""

    def __init__(self, api_key: str, model: str | None = None):
        # max_retries=0: openai's own client retries 429/5xx internally by
        # default (up to DEFAULT_MAX_RETRIES=2) BEFORE raising -- left at its
        # default, z.ai quota-exhaustion (429) would be silently retried by
        # the SDK layer before this provider's tenacity policy (or ZAI-3's
        # never-retry-quota rule) ever sees the exception. Disabling it here
        # makes tenacity, below, the single source of retry truth.
        self.client = AsyncOpenAI(api_key=api_key, base_url=self.base_url, max_retries=0)
        self.model = model or self.default_model

    async def chat_stream(
        self, messages: list[dict], system_prompt: str, params=None
    ) -> AsyncGenerator[StreamChunk, None]:
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        kwargs = {
            "model": self.model,
            "messages": all_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if params:
            if "temperature" in params:
                kwargs["temperature"] = params["temperature"]
            if "max_tokens" in params:
                kwargs["max_tokens"] = params["max_tokens"]
            if "top_p" in params:
                kwargs["top_p"] = params["top_p"]

        def _log_retry_attempt(retry_state):
            exc = retry_state.outcome.exception()
            logger.warning(
                "Transient error from %s (attempt %d): %s — retrying",
                self.base_url,
                retry_state.attempt_number,
                type(exc).__name__,
            )

        retryer = AsyncRetrying(
            stop=stop_after_attempt(3),  # "max 2 retries" (locked) == 3 total attempts
            wait=wait_exponential_jitter(initial=0.5, max=8.0),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,  # preserves original .status_code for routes/chat.py's error mapping
            before_sleep=_log_retry_attempt,
        )
        stream = await retryer(self.client.chat.completions.create, **kwargs)

        async for chunk in stream:
            # Final chunk carries usage stats
            if chunk.usage:
                usage = UsageData(
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                )
                details = getattr(chunk.usage, "prompt_tokens_details", None)
                cached = getattr(details, "cached_tokens", None)
                if cached:
                    usage["cached_tokens"] = cached
                yield ("", usage)
            # Text content chunks
            elif chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield (delta, None)
