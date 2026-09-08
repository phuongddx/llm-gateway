"""Unit tests for providers.create_provider factory dispatch."""

from providers import create_provider
from providers.manifest import ManifestProvider
from providers.zai_coding import ZAICodingProvider


def test_factory_returns_zai_coding_provider():
    p = create_provider("zai-coding", "glm-5.3", api_key="test-key")
    assert isinstance(p, ZAICodingProvider)
    assert p.model == "glm-5.3"


def test_factory_falls_back_to_manifest_for_other_names():
    p = create_provider("anything-else", "gpt-4o", api_key="test-key")
    assert isinstance(p, ManifestProvider)


def test_zai_coding_endpoint_config():
    assert ZAICodingProvider.base_url == "https://api.z.ai/api/coding/paas/v4"
    assert ZAICodingProvider.default_model == "glm-5.3"
