"""DeepSeek provider — deepseek-chat, deepseek-reasoner."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    base_url = "https://api.deepseek.com"
    default_model = "deepseek-chat"
