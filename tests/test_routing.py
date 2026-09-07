"""Unit tests for analytics.routing — resolve_provider() GLM/zai-coding routing."""

import pytest

from analytics.routing import MODEL_ROUTING, resolve_provider


@pytest.fixture
def with_zai_key(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "zai_coding_api_key", "test-zai-key")


@pytest.fixture
def without_zai_key(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "zai_coding_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "")


def test_resolve_known_non_glm_models(without_zai_key):
    """Every non-GLM entry resolves exactly as the table says."""
    for model_name, (expected_provider, expected_model_id) in MODEL_ROUTING.items():
        if expected_provider != "manifest":
            continue
        provider, model_id = resolve_provider(model_name)
        assert provider == "manifest", f"{model_name}: provider mismatch"
        assert model_id == expected_model_id, f"{model_name}: model_id mismatch"


def test_glm_canonical_pair_routes_to_zai(with_zai_key):
    assert resolve_provider("glm-5.3") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-5.3-flash") == ("zai-coding", "glm-5.3-flash")


def test_glm_aliases_canonicalize(with_zai_key):
    assert resolve_provider("glm-5.1") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-5") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-5-turbo") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-4.6") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-4.5") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-4.5-flash") == ("zai-coding", "glm-5.3-flash")
    assert resolve_provider("glm-4.7") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-4.7-flash") == ("zai-coding", "glm-5.3-flash")
    assert resolve_provider("glm-4.7-flashx") == ("zai-coding", "glm-5.3-flash")


def test_glm_routes_degrade_to_manifest_without_key(without_zai_key):
    assert resolve_provider("glm-5.3") == ("manifest", "glm-5.3")
    assert resolve_provider("glm-4.5-flash") == ("manifest", "glm-5.3-flash")


def test_llm_api_key_fallback_enables_zai_routing(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "zai_coding_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "shared-key")
    assert resolve_provider("glm-5.3") == ("zai-coding", "glm-5.3")


def test_unknown_glm_prefix_routes_to_zai(with_zai_key):
    assert resolve_provider("glm-99") == ("zai-coding", "glm-99")
    assert resolve_provider("GLM-99") == ("zai-coding", "GLM-99")


def test_unknown_glm_prefix_degrades_without_key(without_zai_key):
    assert resolve_provider("glm-99") == ("manifest", "glm-99")


def test_unknown_non_glm_passthrough_unchanged(without_zai_key):
    assert resolve_provider("nonexistent-model-xyz") == ("manifest", "nonexistent-model-xyz")


def test_routing_table_has_expected_models():
    assert "auto" in MODEL_ROUTING
    assert "gpt-4o" in MODEL_ROUTING
    assert "glm-5.3" in MODEL_ROUTING
    assert "glm-5.3-flash" in MODEL_ROUTING
    assert "glm-4.7-flash" in MODEL_ROUTING
    assert "MiniMax-Text-01" in MODEL_ROUTING


def test_resolve_auto(without_zai_key):
    assert resolve_provider("auto") == ("manifest", "auto")
