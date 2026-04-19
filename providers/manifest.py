"""Manifest smart model router provider."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class ManifestProvider(OpenAICompatibleProvider):
    """Manifest.build — smart model routing across 500+ models."""

    base_url = "https://app.manifest.build/v1"
    default_model = "auto"
