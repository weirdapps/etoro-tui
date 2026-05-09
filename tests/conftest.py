"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_signals_csv(tmp_path: Path) -> Path:
    """Sample etoro.csv with TKR and BS columns."""
    p = tmp_path / "etoro.csv"
    p.write_text("TKR,NAME,BS\nAAPL,Apple Inc,B\nMSFT,Microsoft,H\nTSLA,Tesla Inc,S\nTM,Toyota,I\n")
    return p


@pytest.fixture
def tmp_census_dir(tmp_path: Path) -> Path:
    """Sample census archive dir with one JSON file."""
    import json

    d = tmp_path / "census"
    d.mkdir()
    sample = {
        "instruments": {
            "details": [
                {"instrumentId": 1001, "symbolFull": "AAPL"},
                {"instrumentId": 1002, "symbolFull": "MSFT"},
                {"instrumentId": 1007, "symbolFull": "TSLA"},
            ],
            "priceData": [
                {"instrumentId": 1001, "currentPrice": 280.14},
                {"instrumentId": 1002, "currentPrice": 410.50},
                {"instrumentId": 1007, "currentPrice": 245.00},
            ],
        },
        "investors": [
            {"portfolio": {"positions": [{"instrumentId": 1001}, {"instrumentId": 1002}]}},
            {"portfolio": {"positions": [{"instrumentId": 1001}]}},
            {"portfolio": {"positions": [{"instrumentId": 1007}]}},
            {"portfolio": {"positions": [{"instrumentId": 1001}, {"instrumentId": 1007}]}},
        ],
    }
    (d / "etoro-data-2026-05-04-03-34.json").write_text(json.dumps(sample))
    return d
