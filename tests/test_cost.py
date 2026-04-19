"""Unit tests for analytics.cost — calculate_cost()."""

from analytics.cost import calculate_cost


def test_any_model_returns_zero():
    assert calculate_cost("gpt-4o", 1000, 500) == 0.0


def test_unknown_model_returns_zero():
    assert calculate_cost("unknown-model-xyz", 1000, 500) == 0.0


def test_zero_tokens():
    assert calculate_cost("gpt-4o", 0, 0) == 0.0


def test_large_token_counts():
    assert calculate_cost("any-model", 1_000_000, 1_000_000) == 0.0
