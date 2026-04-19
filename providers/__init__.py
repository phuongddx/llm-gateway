from config import settings
from providers.base import LLMProvider


def create_provider(provider_name: str, model: str | None = None, api_key: str | None = None) -> LLMProvider:
    """Factory: create provider by name with optional model override and API key."""
    key = api_key or settings.get_api_key(provider_name)

    # All requests route through Manifest
    from providers.manifest import ManifestProvider
    return ManifestProvider(api_key=key, model=model)
