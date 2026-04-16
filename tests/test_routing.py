"""Unit tests for analytics.routing — resolve_provider()."""

import pytest
from analytics.routing import MODEL_ROUTING, resolve_provider


def test_resolve_known_models():
    """Every entry in MODEL_ROUTING resolves correctly."""
    for model_name, (expected_provider, expected_model_id) in MODEL_ROUTING.items():
        provider, model_id = resolve_provider(model_name)
        assert provider == expected_provider, f"{model_name}: provider mismatch"
        assert model_id == expected_model_id, f"{model_name}: model_id mismatch"


def test_resolve_unknown_model_raises():
    """Unknown model raises ValueError listing available models."""
    with pytest.raises(ValueError, match="Unknown model"):
        resolve_provider("nonexistent-model-xyz")


def test_resolve_error_contains_available_models():
    """Error message includes list of available model names."""
    with pytest.raises(ValueError) as exc_info:
        resolve_provider("bad-model")
    error_msg = str(exc_info.value)
    assert "gpt-4o" in error_msg
    assert "deepseek-chat" in error_msg
    assert "gemini-2.5-flash" in error_msg


def test_routing_table_has_expected_models():
    """Verify key models exist in the routing table."""
    assert "gpt-4o" in MODEL_ROUTING
    assert "gpt-4o-mini" in MODEL_ROUTING
    assert "o3" in MODEL_ROUTING
    assert "deepseek-chat" in MODEL_ROUTING
    assert "deepseek-reasoner" in MODEL_ROUTING
    assert "kimi-k2.5" in MODEL_ROUTING
    assert "gemini-2.5-flash" in MODEL_ROUTING
    assert "glm-4-flash" in MODEL_ROUTING
    assert "MiniMax-Text-01" in MODEL_ROUTING
