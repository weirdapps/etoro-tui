"""Shared pytest fixtures."""
import pytest
from pathlib import Path


@pytest.fixture
def tmp_signals_csv(tmp_path: Path) -> Path:
    """Sample etoro.csv with TKR and BS columns."""
    p = tmp_path / "etoro.csv"
    p.write_text(
        "TKR,NAME,BS\n"
        "AAPL,Apple Inc,B\n"
        "MSFT,Microsoft,H\n"
        "TSLA,Tesla Inc,S\n"
        "TM,Toyota,I\n"
    )
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


@pytest.fixture
def tmp_news_db(tmp_path: Path) -> Path:
    """Sample news.db with articles + article_tickers."""
    import sqlite3
    p = tmp_path / "news.db"
    conn = sqlite3.connect(p)
    conn.executescript("""
        CREATE TABLE articles (
            url TEXT PRIMARY KEY, title TEXT, source TEXT, published_at TEXT
        );
        CREATE TABLE article_tickers (article_url TEXT, ticker TEXT);
    """)
    # 5 AAPL articles in last 24h, 1 in last 7d (older), 0 for MSFT
    conn.execute(
        "INSERT INTO articles VALUES ('u1', 't1', 's', datetime('now','-1 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('u2', 't2', 's', datetime('now','-2 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('u3', 't3', 's', datetime('now','-3 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('u4', 't4', 's', datetime('now','-4 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('u5', 't5', 's', datetime('now','-5 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('uold', 't_old', 's', datetime('now','-3 days'))"
    )
    for url in ["u1", "u2", "u3", "u4", "u5", "uold"]:
        conn.execute("INSERT INTO article_tickers VALUES (?, 'AAPL')", (url,))
    conn.commit()
    conn.close()
    return p
