"""Read etorotrade signals CSV with mtime-based caching.

Two methods, both served from a single parse:
  - read()         → {symbol: BUY/SELL/HOLD/None}  (legacy thin API)
  - fundamentals() → {symbol: Fundamentals(signal, pe_t, pe_f, upside_pct, …)}

Source resolution:
  1. local CSV at the configured path (the project author's dev box)
  2. fallback: fetch the same CSV from etorotrade's public GitHub raw URL
     and cache it at ~/.etoro-tui/cache/etoro.csv (re-fetched every 6h)

CSV refresh cadence (upstream): daily at ~22:00 UTC by GitHub Actions.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import NamedTuple, Optional

from .. import config
from ..models import Signal
from .remote_fetch import fetch_to_cache


_BS_MAP: dict[str, Optional[Signal]] = {
    "B": "BUY",
    "S": "SELL",
    "H": "HOLD",
    "I": None,  # inconclusive
}

log = logging.getLogger(__name__)


class Fundamentals(NamedTuple):
    """One row per ticker from the etorotrade fundamentals CSV.

    All numeric fields are Optional[float] — the source uses '--' or empty
    string for missing data (very common for ETFs, crypto, illiquid foreign).
    """
    signal: Optional[Signal]      # BS column → BUY/SELL/HOLD/None
    pe_trailing: Optional[float]  # PET — trailing 12-month P/E
    pe_forward: Optional[float]   # PEF — forward 12-month P/E
    upside_pct: Optional[float]   # UP% — analyst target / current - 1, in %
    analyst_buy_pct: Optional[float]  # %B — % of analysts saying buy
    target_price: Optional[float]     # TGT — analyst consensus target


def _parse_num(s: str | None) -> Optional[float]:
    """Parse a CSV cell into a float. Handles '--', '%', empty, commas."""
    if s is None:
        return None
    s = s.strip().replace(",", "").rstrip("%")
    if not s or s == "--":
        return None
    try:
        return float(s)
    except ValueError:
        return None


class SignalsReader:
    """Reads `etoro.csv`, caches by mtime, exposes signals + fundamentals."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache_signals: dict[str, Optional[Signal]] = {}
        self._cache_fundamentals: dict[str, Fundamentals] = {}
        self._cache_mtime: float | None = None
        self._missing_logged = False

    def _resolve_path(self) -> Path | None:
        """Local first, GitHub raw fallback (cached for 6h)."""
        if self.path.exists():
            return self.path
        cached = fetch_to_cache(
            url=config.SIGNALS_GITHUB_URL,
            cache_name="etoro.csv",
            max_age_seconds=6 * 3600,
        )
        if cached is None and not self._missing_logged:
            log.warning("signals CSV unavailable (local %s missing, GitHub fetch failed)",
                        self.path)
            self._missing_logged = True
        return cached

    def _refresh_if_stale(self) -> bool:
        path = self._resolve_path()
        if path is None:
            return False
        mtime = path.stat().st_mtime
        if self._cache_mtime == mtime:
            return True
        # Use the resolved (possibly cached) path for parsing.
        self.path = path
        signals: dict[str, Optional[Signal]] = {}
        fundamentals: dict[str, Fundamentals] = {}
        with self.path.open(newline="") as f:
            for row in csv.DictReader(f):
                tkr = row.get("TKR", "").strip().upper()
                if not tkr:
                    continue
                bs = row.get("BS", "").strip()
                sig = _BS_MAP.get(bs)
                signals[tkr] = sig
                fundamentals[tkr] = Fundamentals(
                    signal=sig,
                    pe_trailing=_parse_num(row.get("PET")),
                    pe_forward=_parse_num(row.get("PEF")),
                    upside_pct=_parse_num(row.get("UP%")),
                    analyst_buy_pct=_parse_num(row.get("%B")),
                    target_price=_parse_num(row.get("TGT")),
                )
        self._cache_signals = signals
        self._cache_fundamentals = fundamentals
        self._cache_mtime = mtime
        return True

    def read(self) -> dict[str, Optional[Signal]]:
        """Return {symbol: signal or None} — the legacy thin API."""
        if not self._refresh_if_stale():
            return {}
        return self._cache_signals

    def fundamentals(self) -> dict[str, Fundamentals]:
        """Return {symbol: Fundamentals(...)} — full row including signal."""
        if not self._refresh_if_stale():
            return {}
        return self._cache_fundamentals

    def mtime(self) -> Optional[float]:
        """Return the source file's mtime, or None if missing."""
        return self.path.stat().st_mtime if self.path.exists() else None
