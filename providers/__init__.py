from config import settings
from providers.base import LLMProvider


def create_provider() -> LLMProvider:
    """Factory: create provider based on LLM_PROVIDER env var."""
    match settings.llm_provider:
        case "gemini":
            from providers.gemini import GeminiProvider
            return GeminiProvider()
        case "glm":
            from providers.glm import GLMProvider
            return GLMProvider()
        case "minimax":
            from providers.minimax import MiniMaxProvider
            return MiniMaxProvider()
        case _:
            raise ValueError(f"Unknown provider: {settings.llm_provider}")
