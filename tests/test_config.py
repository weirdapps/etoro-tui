from unittest.mock import patch

import pytest

from etoro_tui import config


def test_credentials_from_env(monkeypatch):
    monkeypatch.setenv("ETORO_PUBLIC_KEY", "pk_env")
    monkeypatch.setenv("ETORO_USER_KEY", "uk_env")
    pk, uk = config.get_credentials()
    assert pk == "pk_env"
    assert uk == "uk_env"


def test_credentials_source_env(monkeypatch):
    monkeypatch.setenv("ETORO_PUBLIC_KEY", "pk")
    monkeypatch.setenv("ETORO_USER_KEY", "uk")
    assert config.get_credentials_source() == "env"


def test_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("ETORO_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    # Mock the keychain shell-out to fail
    with patch("etoro_tui.config._keychain_lookup", return_value=None):
        with pytest.raises(config.AuthMissingError):
            config.get_credentials()


def test_paths_are_absolute():
    assert config.SNAPSHOT_DB_PATH.is_absolute()
    assert config.SIGNALS_CSV.is_absolute()
    assert config.NEWS_DB_PATH.is_absolute()


def test_intervals_are_positive():
    assert config.POLL_PORTFOLIO_S > 0
    assert config.POLL_SIGNALS_S > 0
    assert config.SNAPSHOT_S > 0
