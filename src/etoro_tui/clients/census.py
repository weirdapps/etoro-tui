"""Read newest etoro_census JSON and aggregate PI holdings per symbol.

Also exposes an instrument map (instrumentID → symbol + current price) since
the eToro Public API doesn't return symbols or current prices in its portfolio
response. Census has both (instruments.details + instruments.priceData) so we
piggy-back on it. Prices refresh whenever census refreshes (~daily 03:00).

Source resolution:
  1. local newest etoro-data-*.json in the configured directory (dev box)
  2. fallback: list the data-archive branch on GitHub, pick the newest
     filename, fetch + cache to ~/.etoro-tui/cache/
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from .remote_fetch import fetch_newest_census_file

log = logging.getLogger(__name__)


class InstrumentInfo(NamedTuple):
    """One per eToro instrument id, sourced from census."""

    symbol: str
    current_price: float


class CensusReader:
    """Picks newest `etoro-data-*.json` in dir; mtime-cached.

    Two public read methods, both served from a single parse:
    - read() → {symbol: pct_of_PIs_holding}
    - instruments() → {instrumentID: InstrumentInfo(symbol, current_price)}
    """

    def __init__(self, directory: Path, pattern: str) -> None:
        self.directory = directory
        self.pattern = pattern
        self._cache_pi: dict[str, float] = {}
        self._cache_instruments: dict[int, InstrumentInfo] = {}
        self._cache_key: tuple[Path, float] | None = None
        self._missing_logged = False
        self._stale = False

    @property
    def is_stale(self) -> bool:
        """True iff the latest refresh attempt failed and we're serving older cache.

        The census writer rewrites its 80+ MB JSON file in place, non-atomically,
        so ticks that land mid-rewrite see partial data. We keep the previous
        cache and flip this flag so the UI can show a 'census stale' indicator.
        """
        return self._stale

    def _newest_file(self) -> Path | None:
        # Local first.
        if self.directory.exists():
            files = sorted(self.directory.glob(self.pattern))
            if files:
                return files[-1]
        # Fallback: GitHub. The fetcher caches to ~/.etoro-tui/cache/ so we
        # only re-download when the upstream filename changes (~daily).
        return fetch_newest_census_file()

    def _refresh_if_stale(self) -> bool:
        """Return True if cache is populated (either fresh or already cached)."""
        newest = self._newest_file()
        if newest is None:
            if not self._missing_logged:
                log.info("no census file found in %s", self.directory)
                self._missing_logged = True
            return False
        mtime = newest.stat().st_mtime
        cache_key = (newest, mtime)
        if self._cache_key == cache_key:
            self._stale = False
            return True
        try:
            with newest.open() as f:
                data = json.load(f)
            details = data["instruments"]["details"]
            price_data = data["instruments"]["priceData"]
            investors = data["investors"]
        except (json.JSONDecodeError, KeyError, OSError) as e:
            if self._cache_key is not None:
                log.warning(
                    "census refresh failed (%s); serving previous cache from %s",
                    e, self._cache_key[0].name,
                )
                self._stale = True
                return True
            log.warning("census refresh failed and no cache to fall back on: %s", e)
            return False

        # Build instruments map (id → symbol + current price)
        id_to_symbol = {item["instrumentId"]: item["symbolFull"] for item in details}
        id_to_price = {item["instrumentId"]: item["currentPrice"] for item in price_data}
        instruments: dict[int, InstrumentInfo] = {}
        for inst_id, sym in id_to_symbol.items():
            price = id_to_price.get(inst_id)
            if price is not None:
                instruments[inst_id] = InstrumentInfo(symbol=sym, current_price=float(price))
        self._cache_instruments = instruments

        # Build PI% map
        if not investors:
            self._cache_pi = {}
        else:
            counter: Counter[int] = Counter()
            for inv in investors:
                held_ids = {pos["instrumentId"] for pos in inv["portfolio"]["positions"]}
                counter.update(held_ids)
            total = len(investors)
            pi_pct: dict[str, float] = {}
            for inst_id, count in counter.items():
                sym = id_to_symbol.get(inst_id)
                if sym:
                    pi_pct[sym.upper()] = round(count / total * 100, 2)
            self._cache_pi = pi_pct

        self._cache_key = cache_key
        self._stale = False
        return True

    def read(self) -> dict[str, float]:
        """Return {symbol: pct_of_PIs_holding}."""
        if not self._refresh_if_stale():
            return {}
        return self._cache_pi

    def instruments(self) -> dict[int, InstrumentInfo]:
        """Return {instrumentID: InstrumentInfo(symbol, current_price)}.

        Used by app.py to resolve eToro position rows (which only carry
        instrumentID) into displayable Position objects.
        """
        if not self._refresh_if_stale():
            return {}
        return self._cache_instruments
