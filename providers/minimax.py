"""MiniMax provider — extends OpenAICompatibleProvider."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class MiniMaxProvider(OpenAICompatibleProvider):
    base_url = "https://api.minimax.chat/v1"
    default_model = "MiniMax-Text-01"
