"""Model routing table — maps model names to (provider, actual_model_id) tuples."""

# model_name -> (provider_name, actual_model_id)
MODEL_ROUTING: dict[str, tuple[str, str]] = {
    # OpenAI
    "gpt-4o": ("openai", "gpt-4o"),
    "gpt-4o-mini": ("openai", "gpt-4o-mini"),
    "o3": ("openai", "o3"),
    # DeepSeek
    "deepseek-chat": ("deepseek", "deepseek-chat"),
    "deepseek-reasoner": ("deepseek", "deepseek-reasoner"),
    # MoonshotAI (Kimi)
    "kimi-k2.5": ("moonshot", "kimi-k2.5"),
    "kimi-k2-thinking": ("moonshot", "kimi-k2-thinking"),
    "moonshot-v1-128k": ("moonshot", "moonshot-v1-128k"),
    # Google Gemini
    "gemini-2.5-flash": ("gemini", "gemini-2.5-flash"),
    "gemini-2.0-flash": ("gemini", "gemini-2.0-flash"),
    "gemini-2.0-flash-lite": ("gemini", "gemini-2.0-flash-lite"),
    # Z.AI (ZhipuAI GLM)
    "glm-5.1": ("glm", "glm-5.1"),
    "glm-5-turbo": ("glm", "glm-5-turbo"),
    "glm-5": ("glm", "glm-5"),
    "glm-4.7": ("glm", "glm-4.7"),
    "glm-4.7-flash": ("glm", "glm-4.7-flash"),
    "glm-4.7-flashx": ("glm", "glm-4.7-flashx"),
    "glm-4.6": ("glm", "glm-4.6"),
    "glm-4.5": ("glm", "glm-4.5"),
    "glm-4.5-flash": ("glm", "glm-4.5-flash"),
    # MiniMax
    "MiniMax-Text-01": ("minimax", "MiniMax-Text-01"),
    # ByteDance Doubao (endpoint IDs — use ep- prefix pattern)
    "doubao-pro-32k": ("bytedance", "doubao-pro-32k"),
    "doubao-pro-128k": ("bytedance", "doubao-pro-128k"),
}

AVAILABLE_MODELS: list[str] = list(MODEL_ROUTING.keys())


def resolve_provider(model: str) -> tuple[str, str]:
    """Resolve a model name to (provider_name, actual_model_id).

    Raises ValueError if model is not in the routing table.
    """
    entry = MODEL_ROUTING.get(model)
    if entry is None:
        raise ValueError(
            f"Unknown model: '{model}'. Available models: {', '.join(AVAILABLE_MODELS)}"
        )
    return entry
