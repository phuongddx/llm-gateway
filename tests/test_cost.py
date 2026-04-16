"""Unit tests for analytics.cost — calculate_cost()."""

from analytics.cost import calculate_cost


def test_known_model_gpt4o():
    # 2.50 * 1000/1M + 10.00 * 500/1M = 0.0025 + 0.005 = 0.0075
    assert calculate_cost("gpt-4o", 1000, 500) == 0.0075


def test_known_model_deepseek():
    # 0.27 * 1M/1M + 1.10 * 1M/1M = 0.27 + 1.10 = 1.37
    assert calculate_cost("deepseek-chat", 1_000_000, 1_000_000) == 1.37


def test_unknown_model_returns_zero():
    assert calculate_cost("unknown-model-xyz", 1000, 500) == 0.0


def test_zero_tokens():
    assert calculate_cost("gpt-4o", 0, 0) == 0.0


def test_gpt4o_mini():
    # 0.15 * 1000/1M + 0.60 * 500/1M
    expected = (0.15 * 1000 + 0.60 * 500) / 1_000_000
    assert calculate_cost("gpt-4o-mini", 1000, 500) == expected


def test_gemini_flash():
    # 0.15 * 10000/1M + 0.60 * 5000/1M
    expected = (0.15 * 10000 + 0.60 * 5000) / 1_000_000
    assert calculate_cost("gemini-2.5-flash", 10000, 5000) == expected
