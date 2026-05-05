"""Read news-reader SQLite for per-ticker article counts; hourly cache."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class NewsReader:
    """Read-only access to news.db with hourly per-ticker cache."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        # cache key: (ticker_upper, hour_bucket_iso)
        self._count_cache: dict[tuple[str, str], int] = {}
        self._anomaly_cache: dict[tuple[str, str], bool] = {}
        self._missing_logged = False

    def _hour_bucket(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    def _connect(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            if not self._missing_logged:
                log.info("news DB not found at %s", self.db_path)
                self._missing_logged = True
            return None
        uri = f"file:{self.db_path}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=2.0)

    def count_24h(self, ticker: str) -> Optional[int]:
        """Articles in last 24h tagged with this ticker. None if DB unavailable."""
        ticker = ticker.upper()
        key = (ticker, self._hour_bucket())
        if key in self._count_cache:
            return self._count_cache[key]
        conn = self._connect()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM article_tickers at "
                "JOIN articles a ON a.url = at.article_url "
                "WHERE at.ticker = ? AND a.published_at > datetime('now', '-1 day')",
                (ticker,),
            ).fetchone()
            count = int(row[0])
        finally:
            conn.close()
        self._count_cache[key] = count
        return count

    def is_anomaly(self, ticker: str) -> bool:
        """True if 24h count exceeds 1.5 × 7d daily average."""
        ticker = ticker.upper()
        key = (ticker, self._hour_bucket())
        if key in self._anomaly_cache:
            return self._anomaly_cache[key]
        conn = self._connect()
        if conn is None:
            return False
        try:
            seven_day_total = conn.execute(
                "SELECT COUNT(*) FROM article_tickers at "
                "JOIN articles a ON a.url = at.article_url "
                "WHERE at.ticker = ? AND a.published_at > datetime('now', '-7 days')",
                (ticker,),
            ).fetchone()[0]
            count_24h = self.count_24h(ticker) or 0
        finally:
            conn.close()
        avg = seven_day_total / 7.0
        result = count_24h > avg * 1.5 if avg > 0 else count_24h > 0
        # Special case: if there are no articles at all, never anomaly.
        if seven_day_total == 0 and count_24h == 0:
            result = False
        self._anomaly_cache[key] = result
        return result
