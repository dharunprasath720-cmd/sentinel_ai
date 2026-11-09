from sentinel.config import get_settings


def test_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.database_url == "sqlite:///./sentinel.db"
    assert s.seed == 42

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/sentinel")
    get_settings.cache_clear()
    assert get_settings().database_url == "postgresql://u:p@localhost/sentinel"
    get_settings.cache_clear()
