"""Read newest etoro_census JSON and aggregate PI holdings per symbol.

Also exposes an instrument map (instrumentID → symbol + current price) since
the eToro Public API doesn't return symbols or current prices in its portfolio
response. Census has both (instruments.details + instruments.priceData) so we
piggy-back on it. Prices refresh whenever census refreshes (~daily 03:00).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import NamedTuple

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

    def _newest_file(self) -> Path | None:
        if not self.directory.exists():
            return None
        files = sorted(self.directory.glob(self.pattern))
        return files[-1] if files else None

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
            return True
        try:
            with newest.open() as f:
                data = json.load(f)
            details = data["instruments"]["details"]
            price_data = data["instruments"]["priceData"]
            investors = data["investors"]
        except KeyError as e:
            log.error("census schema mismatch in %s: missing key %s", newest, e)
            raise

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
