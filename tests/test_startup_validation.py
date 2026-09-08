"""Unit tests for startup validation — Settings validator and lifespan checks."""

import logging

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


def test_analytics_queue_size_validator_rejects_zero():
    """ANALYTICS_QUEUE_SIZE=0 would unbound asyncio.Queue — reject at construction."""
    with pytest.raises(ValidationError, match="ANALYTICS_QUEUE_SIZE"):
        _settings(analytics_queue_size=0)


def test_analytics_queue_size_validator_rejects_negative():
    with pytest.raises(ValidationError, match="ANALYTICS_QUEUE_SIZE"):
        _settings(analytics_queue_size=-3)


def test_settings_default_constructs_without_app_api_key():
    s = _settings()
    assert s.app_api_key == ""  # construction succeeds; lifespan is the abort point
    assert s.rate_limit == "60/minute"


@pytest.mark.asyncio
async def test_missing_app_api_key_aborts_naming_variable(monkeypatch, tmp_path):
    from main import app, lifespan
    from config import settings

    monkeypatch.setattr(settings, "app_api_key", "")
    monkeypatch.setattr(settings, "analytics_db_path", str(tmp_path / "a.db"))
    with pytest.raises(RuntimeError, match="APP_API_KEY"):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_no_effective_zai_key_logs_notice_no_abort(monkeypatch, tmp_path, caplog):
    from main import app, lifespan
    from config import settings

    monkeypatch.setattr(settings, "app_api_key", "k")
    monkeypatch.setattr(settings, "zai_coding_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "analytics_db_path", str(tmp_path / "a.db"))
    with caplog.at_level(logging.WARNING):
        async with lifespan(app):
            pass  # startup completes — notice, never abort
    assert any(
        "ZAI_CODING_API_KEY" in r.getMessage() and "Manifest" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_no_effective_manifest_key_logs_notice_no_abort(monkeypatch, tmp_path, caplog):
    from main import app, lifespan
    from config import settings

    monkeypatch.setattr(settings, "app_api_key", "k")
    monkeypatch.setattr(settings, "manifest_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "analytics_db_path", str(tmp_path / "a.db"))
    with caplog.at_level(logging.WARNING):
        async with lifespan(app):
            pass  # startup completes — notice, never abort
    assert any("MANIFEST_API_KEY" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_unwritable_analytics_db_path_aborts(monkeypatch, tmp_path):
    from main import app, lifespan
    from config import settings

    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o500)
    monkeypatch.setattr(settings, "app_api_key", "k")
    monkeypatch.setattr(settings, "analytics_db_path", str(readonly_dir / "a.db"))
    try:
        with pytest.raises(RuntimeError, match="ANALYTICS_DB_PATH"):
            async with lifespan(app):
                pass
    finally:
        readonly_dir.chmod(0o700)  # restore so tmp_path cleanup succeeds


@pytest.mark.asyncio
async def test_readonly_analytics_db_file_aborts_at_write_probe(monkeypatch, tmp_path):
    """Read-only DB *file* under a writable parent: mkdir/os.access/initialize
    all pass — only the post-initialize write probe catches it (IM-02)."""
    from analytics.db import AnalyticsDB
    from main import app, lifespan
    from config import settings

    db_path = tmp_path / "a.db"
    seed = AnalyticsDB(str(db_path))  # pre-existing schema, e.g. restored from backup
    await seed.initialize()
    await seed.close()
    db_path.chmod(0o444)  # parent stays writable — only the file is read-only

    monkeypatch.setattr(settings, "app_api_key", "k")
    monkeypatch.setattr(settings, "analytics_db_path", str(db_path))
    try:
        with pytest.raises(RuntimeError, match="ANALYTICS_DB_PATH"):
            async with lifespan(app):
                pass
    finally:
        db_path.chmod(0o644)  # restore so tmp_path cleanup succeeds


@pytest.mark.asyncio
async def test_uncreatable_analytics_parent_aborts_with_curated_error(monkeypatch, tmp_path):
    """mkdir EACCES on a deeper path surfaces as the curated RuntimeError
    naming ANALYTICS_DB_PATH, not a bare PermissionError (MN-02)."""
    from main import app, lifespan
    from config import settings

    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o500)
    monkeypatch.setattr(settings, "app_api_key", "k")
    monkeypatch.setattr(settings, "analytics_db_path", str(readonly_dir / "sub" / "a.db"))
    try:
        with pytest.raises(RuntimeError, match="ANALYTICS_DB_PATH"):
            async with lifespan(app):
                pass
    finally:
        readonly_dir.chmod(0o700)  # restore so tmp_path cleanup succeeds


@pytest.mark.asyncio
async def test_startup_abort_is_deterministic_and_side_effect_free(monkeypatch, tmp_path):
    from main import app, lifespan
    from config import settings

    db_path = tmp_path / "a.db"
    monkeypatch.setattr(settings, "app_api_key", "")
    monkeypatch.setattr(settings, "analytics_db_path", str(db_path))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="APP_API_KEY"):
            async with lifespan(app):
                pass
    assert not db_path.exists()  # abort precedes db.initialize()/writer.start()


@pytest.mark.asyncio
async def test_startup_logs_never_contain_secret_values(monkeypatch, tmp_path, caplog):
    from main import app, lifespan
    from config import settings

    sentinels = {
        "app_api_key": "sk-app-SENTINEL-123",
        "manifest_api_key": "sk-manifest-SENTINEL-456",
        "zai_coding_api_key": "sk-zai-SENTINEL-789",
        "llm_api_key": "sk-llm-SENTINEL-abc",
    }
    for attr, value in sentinels.items():
        monkeypatch.setattr(settings, attr, value)
    monkeypatch.setattr(settings, "analytics_db_path", str(tmp_path / "a.db"))
    with caplog.at_level(logging.DEBUG):
        async with lifespan(app):
            pass
    for value in sentinels.values():
        assert value not in caplog.text
        assert value[:8] not in caplog.text  # partial/masked leaks count too

    # RATE_LIMIT abort path: the raised ValidationError must not echo key values
    with pytest.raises(ValidationError, match="RATE_LIMIT") as exc_info:
        Settings(_env_file=None, rate_limit="bogus/zzz", **sentinels)
    for value in sentinels.values():
        assert value not in str(exc_info.value)
        assert value[:8] not in str(exc_info.value)
