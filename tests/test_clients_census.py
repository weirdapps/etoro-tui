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


def _census_json(details: list, price_data: list, investors: list) -> str:
    """Serialise a census payload with the three sections read() depends on."""
    return json.dumps(
        {
            "instruments": {"details": details, "priceData": price_data},
            "investors": investors,
        }
    )


def _investor(copiers: int, held_ids: list[int]) -> dict:
    """One census investor with a copier count and a set of held instrument ids."""
    return {
        "copiers": copiers,
        "portfolio": {"positions": [{"instrumentId": i} for i in held_ids]},
    }


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
    good.write_text(
        json.dumps(
            {
                "instruments": {
                    "details": [{"instrumentId": 1001, "symbolFull": "AAPL"}],
                    "priceData": [{"instrumentId": 1001, "currentPrice": 300.0}],
                },
                "investors": [{"portfolio": {"positions": [{"instrumentId": 1001}]}}],
            }
        )
    )
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


def test_pi_denominator_caps_at_top_100_most_copied(tmp_path: Path):
    """PI% is computed over the 100 most-copied investors, not the whole census.

    150 investors, copiers descending so investor 0 is most-copied:
      YSYM — held by all 150 → 100/100 among the top-100 → 100%
      XSYM — held by the 50 most-copied → 50/100 → 50%
      ZSYM — held only by the 30 least-copied (outside the top-100) → excluded
    """
    d = tmp_path / "census"
    d.mkdir()
    details = [
        {"instrumentId": 1001, "symbolFull": "XSYM"},
        {"instrumentId": 1002, "symbolFull": "YSYM"},
        {"instrumentId": 1003, "symbolFull": "ZSYM"},
    ]
    price = [
        {"instrumentId": 1001, "currentPrice": 1.0},
        {"instrumentId": 1002, "currentPrice": 1.0},
        {"instrumentId": 1003, "currentPrice": 1.0},
    ]
    investors = []
    for i in range(150):
        held = [1002]  # Y held by everyone
        if i < 50:
            held.append(1001)  # X held by the 50 most-copied
        if i >= 120:
            held.append(1003)  # Z held by the 30 least-copied (outside top-100)
        investors.append(_investor(copiers=150 - i, held_ids=held))
    (d / "etoro-data-2026-05-04-03-00.json").write_text(_census_json(details, price, investors))

    out = CensusReader(d, "etoro-data-*.json").read()
    assert out["YSYM"] == 100.0
    assert out["XSYM"] == 50.0
    assert "ZSYM" not in out


def test_empty_details_falls_back_to_newest_valid_file(tmp_census_dir: Path):
    """A newest file with an empty instrument list is skipped for the last valid one.

    This is the real-world corruption seen 2026-06-27/28: investors present but
    `instruments.details` empty, so no id→symbol translation is possible. The
    reader must fall back to the newest structurally-complete file — even with no
    prior in-memory cache (cold start) — and flag the result as stale.
    """
    newer = tmp_census_dir / "etoro-data-2026-05-05-03-00.json"
    newer.write_text(_census_json([], [], [{"portfolio": {"positions": [{"instrumentId": 1001}]}}]))

    r = CensusReader(tmp_census_dir, "etoro-data-*.json")  # fresh: no prior cache
    assert r.read() == {"AAPL": 75.0, "TSLA": 50.0, "MSFT": 25.0}
    assert r.is_stale is True


def test_empty_price_data_falls_back_to_newest_valid_file(tmp_census_dir: Path):
    """A file with symbols but no priceData is structurally incomplete → skipped."""
    newer = tmp_census_dir / "etoro-data-2026-05-05-03-00.json"
    newer.write_text(
        _census_json(
            [{"instrumentId": 1001, "symbolFull": "AAPL"}],
            [],
            [{"portfolio": {"positions": [{"instrumentId": 1001}]}}],
        )
    )
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    assert r.read()["AAPL"] == 75.0
    assert r.is_stale is True


def test_empty_investors_falls_back_to_newest_valid_file(tmp_census_dir: Path):
    """A file with instruments but no investors carries no PI signal → skipped."""
    newer = tmp_census_dir / "etoro-data-2026-05-05-03-00.json"
    newer.write_text(
        _census_json(
            [{"instrumentId": 1001, "symbolFull": "AAPL"}],
            [{"instrumentId": 1001, "currentPrice": 1.0}],
            [],
        )
    )
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    assert r.read()["AAPL"] == 75.0
    assert r.is_stale is True


def test_all_files_invalid_returns_empty_not_stale(tmp_path: Path):
    """When no file anywhere is structurally complete, return empty without a stale flag."""
    d = tmp_path / "census"
    d.mkdir()
    (d / "etoro-data-2026-05-04-03-00.json").write_text(_census_json([], [], []))
    (d / "etoro-data-2026-05-05-03-00.json").write_text(_census_json([], [], []))
    r = CensusReader(d, "etoro-data-*.json")
    assert r.read() == {}
    assert r.is_stale is False
