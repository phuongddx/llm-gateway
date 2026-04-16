"""ZhipuAI GLM provider — extends OpenAICompatibleProvider."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class GLMProvider(OpenAICompatibleProvider):
    base_url = "https://open.bigmodel.cn/api/paas/v4"
    default_model = "glm-4-flash"
