"""Unit tests for analytics.cost — calculate_cost() + estimate_credits()."""

from datetime import datetime, timezone

import pytest

from analytics.cost import calculate_cost
from analytics.cost import estimate_credits, is_peak

# 2026-09-07 is a Monday. 07:00 UTC = 15:00 SGT (peak); 23:00 UTC = 07:00 SGT Tue (off-peak).
PEAK_TS = datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc)
OFF_PEAK_TS = datetime(2026, 9, 7, 23, 0, tzinfo=timezone.utc)


def test_any_model_returns_zero():
    assert calculate_cost("gpt-4o", 1000, 500) == 0.0


def test_unknown_model_returns_zero():
    assert calculate_cost("unknown-model-xyz", 1000, 500) == 0.0


def test_zero_tokens():
    assert calculate_cost("gpt-4o", 0, 0) == 0.0


def test_large_token_counts():
    assert calculate_cost("any-model", 1_000_000, 1_000_000) == 0.0


def test_is_peak_monday_afternoon_sgt():
    assert is_peak(PEAK_TS) is True


def test_is_not_peak_overnight_sgt():
    assert is_peak(OFF_PEAK_TS) is False


def test_is_not_peak_weekend():
    assert is_peak(datetime(2026, 9, 5, 7, 0, tzinfo=timezone.utc)) is False  # Saturday


def test_estimate_credits_glm53_peak():
    usage = {"prompt_tokens": 150000, "completion_tokens": 3000, "cached_tokens": 142500}
    # fresh 7500*6.9 + cached 142500*1.7 + 3000*24 = 366000 -> 36.6
    assert estimate_credits("zai-coding", "glm-5.3", usage, PEAK_TS) == pytest.approx(36.6)


def test_estimate_credits_off_peak_halved():
    usage = {"prompt_tokens": 150000, "completion_tokens": 3000, "cached_tokens": 142500}
    assert estimate_credits("zai-coding", "glm-5.3", usage, OFF_PEAK_TS) == pytest.approx(18.3)


def test_estimate_credits_flash_multipliers():
    usage = {"prompt_tokens": 10000, "completion_tokens": 1000}
    # 10000*2.3 + 0 + 1000*8 = 31000 -> 3.1
    assert estimate_credits("zai-coding", "glm-5.3-flash", usage, PEAK_TS) == pytest.approx(3.1)


def test_estimate_credits_no_cache_field():
    usage = {"prompt_tokens": 10000, "completion_tokens": 1000}
    assert estimate_credits("zai-coding", "glm-5.3", usage, PEAK_TS) == pytest.approx(
        (10000 * 6.9 + 1000 * 24) / 10_000
    )


def test_estimate_credits_zero_for_manifest():
    assert estimate_credits("manifest", "glm-5.3", {"prompt_tokens": 1, "completion_tokens": 1}, PEAK_TS) == 0.0


def test_estimate_credits_zero_for_unknown_model():
    assert estimate_credits("zai-coding", "glm-99", {"prompt_tokens": 1, "completion_tokens": 1}, PEAK_TS) == 0.0


def test_calculate_cost_still_zero():
    assert calculate_cost("glm-5.3", 1000, 500) == 0.0
