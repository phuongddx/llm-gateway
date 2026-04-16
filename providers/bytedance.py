"""ByteDance Doubao provider — uses endpoint IDs as model names."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class ByteDanceProvider(OpenAICompatibleProvider):
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    default_model = ""  # Must provide endpoint ID as model name
