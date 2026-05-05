"""Tests for clients.census module."""

import json
import time
from pathlib import Path

from etoro_tui.clients.census import CensusReader


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
            "details": [{"instrumentId": 1001, "symbolFull": "AAPL"}]
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
