import logging

from google import genai
from google.genai import types

from config import settings
from providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Map OpenAI roles to Gemini roles
_ROLE_MAP = {"user": "user", "assistant": "model", "system": "user"}


class GeminiProvider(LLMProvider):
    def __init__(self):
        self.client = genai.Client(api_key=settings.llm_api_key)
        self.model = settings.llm_model or "gemini-2.5-flash"

    async def chat_stream(self, messages: list[dict], system_prompt: str):
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
            text = getattr(chunk, "text", None)
            if text:
                yield text

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
