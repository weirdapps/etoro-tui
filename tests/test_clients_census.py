"""Tests for clients.census module."""

import json
from pathlib import Path

import pytest

from etoro_tui.clients import census as census_module
from etoro_tui.clients.census import CensusReader, InstrumentInfo


@pytest.fixture(autouse=True)
def _disable_github_fallback(monkeypatch):
    """Tests must not hit the network. Force the GitHub fallback to no-op so
    'no local file' actually means 'no data', not 'live download from
    weirdapps/etoro_census'."""
    monkeypatch.setattr(census_module, "fetch_newest_census_file", lambda: None)


def test_aggregates_pi_holdings(tmp_census_dir: Path):
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    out = r.read()
    # 4 investors total. AAPL held by 3 → 75%, TSLA by 2 → 50%, MSFT by 1 → 25%
    assert out["AAPL"] == 75.0
    assert out["TSLA"] == 50.0
    assert out["MSFT"] == 25.0


def test_picks_newest_file(tmp_census_dir: Path):
    # Add a newer file (later date) with different data
    newer = tmp_census_dir / "etoro-data-2026-05-05-03-00.json"
    sample = {
        "instruments": {
            "details": [{"instrumentId": 1001, "symbolFull": "AAPL"}],
            "priceData": [{"instrumentId": 1001, "currentPrice": 300.00}],
        },
        "investors": [
            {"portfolio": {"positions": [{"instrumentId": 1001}]}},
            {"portfolio": {"positions": []}},
        ],
    }
    newer.write_text(json.dumps(sample))
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    out = r.read()
    # Should reflect the newer file: 1/2 = 50%
    assert out == {"AAPL": 50.0}


def test_no_files_returns_empty(tmp_path: Path):
    r = CensusReader(tmp_path, "etoro-data-*.json")
    assert r.read() == {}


def test_cache_hit_when_unchanged(tmp_census_dir: Path):
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    first = r.read()
    second = r.read()
    assert first is second  # identity, not just equality — proves cache hit


def test_instruments_returns_id_to_symbol_and_price(tmp_census_dir: Path):
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    out = r.instruments()
    assert out[1001] == InstrumentInfo(symbol="AAPL", current_price=280.14)
    assert out[1002] == InstrumentInfo(symbol="MSFT", current_price=410.50)
    assert out[1007] == InstrumentInfo(symbol="TSLA", current_price=245.00)


def test_instruments_empty_when_no_files(tmp_path: Path):
    r = CensusReader(tmp_path, "etoro-data-*.json")
    assert r.instruments() == {}


def test_instruments_and_pi_share_a_single_parse(tmp_census_dir: Path):
    """Both methods served from one file parse — calling either populates both caches."""
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    r.read()  # parse once
    inst_first = r.instruments()
    inst_second = r.instruments()
    assert inst_first is inst_second  # cache identity proves no re-parse


def test_malformed_json_serves_stale_cache_when_present(tmp_census_dir: Path):
    """A newer file caught mid-write shouldn't crash — keep serving the previous cache."""
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    first = r.read()
    assert first  # populated from fixture's good file

    bad = tmp_census_dir / "etoro-data-2026-05-05-03-00.json"
    bad.write_text('{"instruments": {"details": [{"instrumentId": 1001, "symbol')

    second = r.read()
    assert second == first
    assert r.is_stale is True


def test_malformed_json_with_no_prior_cache_returns_empty(tmp_path: Path):
    """First-ever read of a broken file: no cache, no crash, empty result, not stale."""
    d = tmp_path / "census"
    d.mkdir()
    (d / "etoro-data-2026-05-05-03-00.json").write_text('{"investors": [trunc')
    r = CensusReader(d, "etoro-data-*.json")
    assert r.read() == {}
    assert r.is_stale is False


def test_recovery_clears_stale_flag(tmp_census_dir: Path):
    """Bad file → good newer file: stale flag flips back to False on successful parse."""
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    r.read()  # cache from fixture (05-04)

    bad = tmp_census_dir / "etoro-data-2026-05-05-03-00.json"
    bad.write_text('{"broken')
    r.read()
    assert r.is_stale is True

    good = tmp_census_dir / "etoro-data-2026-05-06-03-00.json"
    good.write_text(json.dumps({
        "instruments": {
            "details": [{"instrumentId": 1001, "symbolFull": "AAPL"}],
            "priceData": [{"instrumentId": 1001, "currentPrice": 300.0}],
        },
        "investors": [{"portfolio": {"positions": [{"instrumentId": 1001}]}}],
    }))
    assert r.read() == {"AAPL": 100.0}
    assert r.is_stale is False


def test_missing_required_key_falls_back_to_cache(tmp_census_dir: Path):
    """A well-formed-but-incomplete JSON file is treated the same as a parse error."""
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    first = r.read()

    bad = tmp_census_dir / "etoro-data-2026-05-05-03-00.json"
    bad.write_text('{"instruments": {"details": []}}')  # missing priceData + investors

    second = r.read()
    assert second == first
    assert r.is_stale is True
