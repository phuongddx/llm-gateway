"""MoonshotAI (Kimi) provider — kimi-k2.5, kimi-k2-thinking, moonshot-v1-128k."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class MoonshotProvider(OpenAICompatibleProvider):
    base_url = "https://api.moonshot.cn/v1"
    default_model = "kimi-k2.5"
