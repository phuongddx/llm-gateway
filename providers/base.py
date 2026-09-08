from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import NotRequired, TypedDict


class UsageData(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: NotRequired[int]


StreamChunk = tuple[str, UsageData | None]


class GenParams(TypedDict, total=False):
    temperature: float
    max_tokens: int
    top_p: float


class LLMProvider(ABC):
    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], system_prompt: str, params: GenParams | None = None
    ) -> AsyncGenerator[StreamChunk, None]:
        """Yield (token, usage_dict | None) tuples from the LLM."""
        ...
