from config import settings
from providers.base import LLMProvider


def create_provider(provider_name: str, model: str | None = None, api_key: str | None = None) -> LLMProvider:
    """Factory: create provider by name with optional model override and API key."""
    key = api_key or settings.get_api_key(provider_name)

    match provider_name:
        case "gemini":
            from providers.gemini import GeminiProvider
            return GeminiProvider(api_key=key, model=model)
        case "glm":
            from providers.glm import GLMProvider
            return GLMProvider(api_key=key, model=model)
        case "minimax":
            from providers.minimax import MiniMaxProvider
            return MiniMaxProvider(api_key=key, model=model)
        case "openai":
            from providers.openai_provider import OpenAIProvider
            return OpenAIProvider(api_key=key, model=model)
        case "deepseek":
            from providers.deepseek import DeepSeekProvider
            return DeepSeekProvider(api_key=key, model=model)
        case "moonshot":
            from providers.moonshot import MoonshotProvider
            return MoonshotProvider(api_key=key, model=model)
        case "bytedance":
            from providers.bytedance import ByteDanceProvider
            return ByteDanceProvider(api_key=key, model=model)
        case _:
            raise ValueError(f"Unknown provider: {provider_name}")
