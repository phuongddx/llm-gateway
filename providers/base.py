from abc import ABC, abstractmethod
from typing import AsyncGenerator


class LLMProvider(ABC):
    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncGenerator[str, None]:
        """Yield tokens from the LLM."""
        ...
