"""Unit tests for startup validation — Settings validator and lifespan checks."""

import pytest
from pydantic import ValidationError

from config import Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_rate_limit_validator_rejects_garbage():
    with pytest.raises(ValidationError, match="RATE_LIMIT"):
        _settings(rate_limit="bogus/zzz")


def test_rate_limit_validator_rejects_wrong_granularity():
    with pytest.raises(ValidationError, match="RATE_LIMIT"):
        _settings(rate_limit="60/fortnight")


def test_rate_limit_validator_rejects_bare_number():
    with pytest.raises(ValidationError, match="RATE_LIMIT"):
        _settings(rate_limit="60")


def test_rate_limit_validator_accepts_multi_limit():
    s = _settings(rate_limit="60/minute, 1000/hour")
    assert s.rate_limit == "60/minute, 1000/hour"


def test_settings_default_constructs_without_app_api_key():
    s = _settings()
    assert s.rate_limit == "60/minute"
