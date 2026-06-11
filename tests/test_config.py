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
    # Bypass any .env file or keyring entries the dev box might have.
    monkeypatch.setattr(config, "_ENVFILE", {})
    monkeypatch.setattr(config, "_keyring_lookup", lambda: (None, None))
    with pytest.raises(config.AuthMissingError):
        config.get_credentials()


def test_credentials_from_envfile(monkeypatch):
    monkeypatch.delenv("ETORO_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    monkeypatch.setattr(
        config, "_ENVFILE", {"ETORO_PUBLIC_KEY": "pk_file", "ETORO_USER_KEY": "uk_file"}
    )
    pk, uk = config.get_credentials()
    assert (pk, uk) == ("pk_file", "uk_file")
    assert config.get_credentials_source() == "envfile"


def test_credentials_from_keyring(monkeypatch):
    """When env + envfile are empty, _keyring_lookup is consulted."""
    monkeypatch.delenv("ETORO_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    monkeypatch.setattr(config, "_ENVFILE", {})
    monkeypatch.setattr(config, "_keyring_lookup", lambda: ("pk_kr", "uk_kr"))
    pk, uk = config.get_credentials()
    assert (pk, uk) == ("pk_kr", "uk_kr")
    assert config.get_credentials_source() == "keyring"


def test_credentials_resolution_priority(monkeypatch):
    """env wins over envfile, envfile wins over keyring."""
    monkeypatch.setenv("ETORO_PUBLIC_KEY", "pk_env")
    monkeypatch.setenv("ETORO_USER_KEY", "uk_env")
    monkeypatch.setattr(
        config, "_ENVFILE", {"ETORO_PUBLIC_KEY": "pk_file", "ETORO_USER_KEY": "uk_file"}
    )
    monkeypatch.setattr(config, "_keyring_lookup", lambda: ("pk_kr", "uk_kr"))
    pk, uk = config.get_credentials()
    assert (pk, uk) == ("pk_env", "uk_env")
    assert config.get_credentials_source() == "env"


def test_keyring_lookup_no_module(monkeypatch):
    """When the optional `keyring` package isn't importable, lookup returns Nones."""
    import sys

    # Force ImportError by removing keyring from sys.modules and blocking re-import.
    monkeypatch.setitem(sys.modules, "keyring", None)
    pk, uk = config._keyring_lookup()
    assert (pk, uk) == (None, None)


def test_paths_are_absolute():
    assert config.SNAPSHOT_DB_PATH.is_absolute()
    assert config.SIGNALS_CSV.is_absolute()
    assert config.CENSUS_GLOB_DIR.is_absolute()


def test_intervals_are_positive():
    assert config.POLL_PORTFOLIO_S > 0
    assert config.POLL_SIGNALS_S > 0
    assert config.SNAPSHOT_S > 0


def test_get_indices_default():
    """Without a TOML override, the curated default set is returned, led by the
    three US majors — the two that regressed off the bar (S&P, Dow) plus NASDAQ.
    The header always shows at least these first three."""
    out = config.get_indices()
    assert all(isinstance(t, tuple) and len(t) == 2 for t in out)
    assert [name for name, _ in out[:3]] == ["S&P 500", "Dow 30", "NASDAQ"]


def test_default_indices_resolve_to_yahoo_index_tickers():
    """Every default index code must map to a real Yahoo index ticker (^…).

    Indices are priced from Yahoo, so a code with no Yahoo index mapping would
    silently vanish from the bar — exactly the regression this guards against.
    """
    from etoro_tui.clients.yahoo import _INDEX_TO_YAHOO

    for name, sym in config.DEFAULT_INDICES:
        assert sym in _INDEX_TO_YAHOO, f"{name} ({sym}) has no Yahoo index mapping"
        assert _INDEX_TO_YAHOO[sym].startswith("^")
