"""Model routing table — maps model names to (provider, actual_model_id) tuples."""

# model_name -> (provider_name, actual_model_id)
# All routes go through Manifest. Unknown models are passed through as-is.
MODEL_ROUTING: dict[str, tuple[str, str]] = {
    # Auto-routing
    "auto": ("manifest", "auto"),
    # OpenAI
    "gpt-5.4": ("manifest", "gpt-5.4"),
    "gpt-4o": ("manifest", "gpt-4o"),
    "gpt-4o-mini": ("manifest", "gpt-4o-mini"),
    "o3": ("manifest", "o3"),
    # Anthropic
    "claude-sonnet": ("manifest", "claude-sonnet-4-6"),
    "claude-haiku": ("manifest", "claude-haiku-4-5-20251001"),
    # Google
    "gemini-2.5-flash": ("manifest", "gemini-2.5-flash"),
    "gemini-2.0-flash": ("manifest", "gemini-2.0-flash"),
    "gemini-2.0-flash-lite": ("manifest", "gemini-2.0-flash-lite"),
    # DeepSeek
    "deepseek-chat": ("manifest", "deepseek-chat"),
    "deepseek-reasoner": ("manifest", "deepseek-reasoner"),
    # MoonshotAI (Kimi)
    "kimi-k2.5": ("manifest", "kimi-k2.5"),
    "kimi-k2-thinking": ("manifest", "kimi-k2-thinking"),
    "moonshot-v1-128k": ("manifest", "moonshot-v1-128k"),
    # Z.AI GLM
    "glm-5.1": ("manifest", "glm-5.1"),
    "glm-5-turbo": ("manifest", "glm-5-turbo"),
    "glm-5": ("manifest", "glm-5"),
    "glm-4.7": ("manifest", "glm-4.7"),
    "glm-4.7-flash": ("manifest", "glm-4.7-flash"),
    "glm-4.7-flashx": ("manifest", "glm-4.7-flashx"),
    "glm-4.6": ("manifest", "glm-4.6"),
    "glm-4.5": ("manifest", "glm-4.5"),
    "glm-4.5-flash": ("manifest", "glm-4.5-flash"),
    # MiniMax
    "MiniMax-Text-01": ("manifest", "MiniMax-Text-01"),
    # ByteDance Doubao
    "doubao-pro-32k": ("manifest", "doubao-pro-32k"),
    "doubao-pro-128k": ("manifest", "doubao-pro-128k"),
}

AVAILABLE_MODELS: list[str] = list(MODEL_ROUTING.keys())


def resolve_provider(model: str) -> tuple[str, str]:
    """Resolve a model name to (provider_name, actual_model_id).

    Known models use the routing table. Unknown models pass through to Manifest.
    """
    entry = MODEL_ROUTING.get(model)
    if entry:
        return entry
    # Passthrough: unknown models go to Manifest as-is
    return ("manifest", model)
