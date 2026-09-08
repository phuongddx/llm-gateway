"""Unit tests for config.Settings — zai-coding key resolution."""

from config import Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_zai_coding_key_dedicated():
    s = _settings(zai_coding_api_key="zai-key", llm_api_key="fallback")
    assert s.get_api_key("zai-coding") == "zai-key"


def test_zai_coding_key_falls_back_to_llm_api_key():
    s = _settings(zai_coding_api_key="", llm_api_key="fallback")
    assert s.get_api_key("zai-coding") == "fallback"


def test_zai_coding_key_absent_everywhere():
    s = _settings(zai_coding_api_key="", llm_api_key="")
    assert s.get_api_key("zai-coding") == ""


def test_credits_defaults_are_max_plan():
    s = _settings()
    assert s.zai_credits_5h == 28000
    assert s.zai_credits_week == 140000


def test_manifest_resolution_unchanged():
    s = _settings(manifest_api_key="m", llm_api_key="f")
    assert s.get_api_key("manifest") == "m"
