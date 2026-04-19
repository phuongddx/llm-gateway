"""Shared base class for OpenAI-compatible API providers."""

import logging

from openai import AsyncOpenAI

from providers.base import LLMProvider, StreamChunk, UsageData

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Base for providers using the OpenAI-compatible chat completions API.

    Subclasses set class-level base_url and default_model.
    """

    base_url: str = ""
    default_model: str = ""

    def __init__(self, api_key: str, model: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
        self.model = model or self.default_model

    async def chat_stream(
        self, messages: list[dict], system_prompt: str, params=None
    ) -> AsyncGenerator[StreamChunk, None]:
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        kwargs = dict(
            model=self.model,
            messages=all_messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        if params:
            if "temperature" in params:
                kwargs["temperature"] = params["temperature"]
            if "max_tokens" in params:
                kwargs["max_tokens"] = params["max_tokens"]
            if "top_p" in params:
                kwargs["top_p"] = params["top_p"]

        stream = await self.client.chat.completions.create(**kwargs)

        async for chunk in stream:
            # Final chunk carries usage stats
            if chunk.usage:
                usage = UsageData(
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                )
                yield ("", usage)
            # Text content chunks
            elif chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield (delta, None)
