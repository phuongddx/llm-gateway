"""Google Gemini provider — uses native google-genai SDK with usage metadata extraction."""

import logging
from typing import AsyncGenerator

from google import genai
from google.genai import types

from providers.base import LLMProvider, StreamChunk, UsageData

logger = logging.getLogger(__name__)

_ROLE_MAP = {"user": "user", "assistant": "model", "system": "user"}


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str | None = None):
        self.client = genai.Client(api_key=api_key)
        self.model = model or "gemini-2.0-flash-lite"

    async def chat_stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncGenerator[StreamChunk, None]:
        contents = self._to_contents(messages)
        config = (
            types.GenerateContentConfig(system_instruction=system_prompt)
            if system_prompt
            else None
        )

        response = await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        )

        async for chunk in response:
            # Check for usage metadata (typically on final chunk)
            usage_meta = getattr(chunk, "usage_metadata", None)
            if usage_meta:
                usage = UsageData(
                    prompt_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
                    completion_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
                    total_tokens=getattr(usage_meta, "total_token_count", 0) or 0,
                )
                yield ("", usage)

            # Text content
            text = getattr(chunk, "text", None)
            if text:
                yield (text, None)

    def _to_contents(self, messages: list[dict]) -> list[types.Content]:
        """Convert OpenAI-style messages to Gemini Content objects."""
        contents = []
        for msg in messages:
            raw_role = msg.get("role", "user")
            role = _ROLE_MAP.get(raw_role)
            if role is None:
                logger.warning("Unknown role %r, defaulting to 'user'", raw_role)
                role = "user"
            contents.append(
                types.Content(role=role, parts=[types.Part.from_text(text=msg.get("content", ""))])
            )
        return contents
