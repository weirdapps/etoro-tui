"""Tests for clients/news.py — news.db reader."""
from pathlib import Path

from etoro_tui.clients.news import NewsReader


def test_count_24h_for_known_ticker(tmp_news_db: Path):
    r = NewsReader(tmp_news_db)
    assert r.count_24h("AAPL") == 5


def test_count_24h_for_missing_ticker(tmp_news_db: Path):
    r = NewsReader(tmp_news_db)
    assert r.count_24h("ZZZZ") == 0


def test_anomaly_when_above_threshold(tmp_news_db: Path):
    # AAPL: 5 in last 24h. 7d total = 6 → daily avg ≈ 0.857.
    # 5 > 0.857 * 1.5 (≈1.29) → anomaly = True.
    r = NewsReader(tmp_news_db)
    assert r.is_anomaly("AAPL") is True


def test_no_anomaly_when_no_articles(tmp_news_db: Path):
    r = NewsReader(tmp_news_db)
    assert r.is_anomaly("ZZZZ") is False


def test_missing_db_returns_none(tmp_path: Path):
    r = NewsReader(tmp_path / "nope.db")
    assert r.count_24h("AAPL") is None
    assert r.is_anomaly("AAPL") is False


def test_hourly_cache_hit(tmp_news_db: Path, monkeypatch):
    r = NewsReader(tmp_news_db)
    r.count_24h("AAPL")
    # Delete the DB file. Next call should hit cache, not error.
    tmp_news_db.unlink()
    assert r.count_24h("AAPL") == 5
