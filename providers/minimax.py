from openai import AsyncOpenAI
from config import settings
from providers.base import LLMProvider


class MiniMaxProvider(LLMProvider):
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or "https://api.minimax.chat/v1",
        )
        self.model = settings.llm_model or "MiniMax-Text-01"

    async def chat_stream(self, messages: list[dict], system_prompt: str):
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=all_messages,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
