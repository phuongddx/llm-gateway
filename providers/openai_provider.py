"""OpenAI provider — gpt-4o, gpt-4o-mini, o3."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o"
