"""Unit tests for analytics.routing — resolve_provider()."""

from analytics.routing import MODEL_ROUTING, resolve_provider


def test_resolve_known_models():
    """Every entry in MODEL_ROUTING resolves correctly."""
    for model_name, (expected_provider, expected_model_id) in MODEL_ROUTING.items():
        provider, model_id = resolve_provider(model_name)
        assert provider == expected_provider, f"{model_name}: provider mismatch"
        assert model_id == expected_model_id, f"{model_name}: model_id mismatch"


def test_resolve_unknown_model_passthrough():
    """Unknown model passes through to manifest instead of raising."""
    provider, model_id = resolve_provider("nonexistent-model-xyz")
    assert provider == "manifest"
    assert model_id == "nonexistent-model-xyz"


def test_all_routes_use_manifest():
    """All entries in routing table route to manifest provider."""
    for model_name, (provider, _) in MODEL_ROUTING.items():
        assert provider == "manifest", f"{model_name} routes to {provider}, not manifest"


def test_routing_table_has_expected_models():
    """Verify key models exist in the routing table."""
    assert "auto" in MODEL_ROUTING
    assert "gpt-4o" in MODEL_ROUTING
    assert "gpt-4o-mini" in MODEL_ROUTING
    assert "o3" in MODEL_ROUTING
    assert "deepseek-chat" in MODEL_ROUTING
    assert "deepseek-reasoner" in MODEL_ROUTING
    assert "kimi-k2.5" in MODEL_ROUTING
    assert "gemini-2.5-flash" in MODEL_ROUTING
    assert "gemini-2.0-flash-lite" in MODEL_ROUTING
    assert "glm-4.7-flash" in MODEL_ROUTING
    assert "MiniMax-Text-01" in MODEL_ROUTING


def test_resolve_auto():
    """Auto-routing resolves to manifest with model 'auto'."""
    provider, model_id = resolve_provider("auto")
    assert provider == "manifest"
    assert model_id == "auto"
