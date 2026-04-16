from abc import ABC, abstractmethod
from typing import AsyncGenerator, TypedDict


class UsageData(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# Each yield from chat_stream is a (token_str, usage_or_none) tuple
StreamChunk = tuple[str, UsageData | None]


class LLMProvider(ABC):
    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncGenerator[StreamChunk, None]:
        """Yield (token, usage_dict | None) tuples from the LLM.

        usage_dict is None for intermediate chunks and populated on the final chunk.
        """
        ...
