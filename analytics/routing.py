"""Model routing table — maps model names to (provider, actual_model_id) tuples."""

from config import settings

# Canonical models served by the z.ai GLM Coding Plan endpoint
GLM_CANONICAL = "glm-5.3"
GLM_CANONICAL_FLASH = "glm-5.3-flash"


def _zai_key_present() -> bool:
    """Effective key check so the llm_api_key fallback stays live (spec §2.1)."""
    return bool(settings.get_api_key("zai-coding"))


# model_name -> (provider_name, actual_model_id)
# Non-GLM models route through Manifest. GLM entries carry their canonical z.ai
# model id; resolve_provider() downgrades them to Manifest when no key is set.
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
    # Z.AI GLM Coding Plan — canonical pair + aliases (flash-named -> flash, rest -> glm-5.3)
    GLM_CANONICAL: ("zai-coding", GLM_CANONICAL),
    GLM_CANONICAL_FLASH: ("zai-coding", GLM_CANONICAL_FLASH),
    "glm-5.1": ("zai-coding", GLM_CANONICAL),
    "glm-5-turbo": ("zai-coding", GLM_CANONICAL),
    "glm-5": ("zai-coding", GLM_CANONICAL),
    "glm-4.7": ("zai-coding", GLM_CANONICAL),
    "glm-4.7-flash": ("zai-coding", GLM_CANONICAL_FLASH),
    "glm-4.7-flashx": ("zai-coding", GLM_CANONICAL_FLASH),
    "glm-4.6": ("zai-coding", GLM_CANONICAL),
    "glm-4.5": ("zai-coding", GLM_CANONICAL),
    "glm-4.5-flash": ("zai-coding", GLM_CANONICAL_FLASH),
    # MiniMax
    "MiniMax-Text-01": ("manifest", "MiniMax-Text-01"),
    # ByteDance Doubao
    "doubao-pro-32k": ("manifest", "doubao-pro-32k"),
    "doubao-pro-128k": ("manifest", "doubao-pro-128k"),
}

AVAILABLE_MODELS: list[str] = list(MODEL_ROUTING.keys())


def resolve_provider(model: str) -> tuple[str, str]:
    """Resolve a model name to (provider_name, actual_model_id).

    GLM models go to the z.ai coding endpoint when an effective key is
    configured; without one they degrade to Manifest with canonical ids.
    Unknown glm-* names follow the same rule with the name passed through;
    all other unknown models pass through to Manifest as-is.
    """
    entry = MODEL_ROUTING.get(model)
    if entry:
        provider_name, model_id = entry
        if provider_name != "zai-coding" or _zai_key_present():
            return entry
        return ("manifest", model_id)

    if model.lower().startswith("glm-") and _zai_key_present():
        return ("zai-coding", model)

    # Passthrough: unknown models go to Manifest as-is
    return ("manifest", model)
