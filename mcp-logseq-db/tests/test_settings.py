import pytest

from mcp_logseq_db.settings import Settings


def test_settings_keep_connect_and_read_timeouts_independent(monkeypatch) -> None:
    monkeypatch.setenv("LOGSEQ_API_TOKEN", "test-token")
    monkeypatch.setenv("LOGSEQ_API_CONNECT_TIMEOUT", "2.5")
    monkeypatch.setenv("LOGSEQ_API_READ_TIMEOUT", "17")

    settings = Settings.from_env()

    assert settings.connect_timeout == 2.5
    assert settings.read_timeout == 17


def test_settings_require_token(monkeypatch) -> None:
    monkeypatch.delenv("LOGSEQ_API_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="LOGSEQ_API_TOKEN is required"):
        Settings.from_env()