"""Z.AI GLM Coding Plan provider — flat-rate subscription endpoint."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class ZAICodingProvider(OpenAICompatibleProvider):
    """api.z.ai coding endpoint — serves glm-5.3 / glm-5.3-flash on plan quota."""

    base_url = "https://api.z.ai/api/coding/paas/v4"
    default_model = "glm-5.3"
