import json
from google import genai
from config import settings
from providers.base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self):
        self.client = genai.Client(api_key=settings.llm_api_key)
        self.model = settings.llm_model or "gemini-2.0-flash"

    async def chat_stream(self, messages: list[dict], system_prompt: str):
        contents = self._to_contents(messages)
        config = {"system_instruction": system_prompt} if system_prompt else {}

        response = await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        )

        async for chunk in response:
            if chunk.text:
                yield chunk.text

    def _to_contents(self, messages: list[dict]) -> list[dict]:
        """Convert OpenAI-style messages to Gemini contents format."""
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        return contents
