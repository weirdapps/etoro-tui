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

# PI% is measured over the most-copied investors only — the census carries
# ~1500 popular investors sorted by copiers, but the signal we want is what the
# *most influential* investors hold, so we cap the denominator at the top N.
TOP_N_PIS = 100


class InstrumentInfo(NamedTuple):
    """One per eToro instrument id, sourced from census."""

    symbol: str
    current_price: float


class CensusReader:
    """Picks newest `etoro-data-*.json` in dir; mtime-cached.

    Two public read methods, both served from a single parse:
    - read() → {symbol: pct_of_top_PIs_holding} (over the TOP_N_PIS most-copied)
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

    def _candidate_files(self) -> list[Path]:
        """Local census files, oldest→newest by name.

        Filenames are `etoro-data-YYYY-MM-DD-HH-MM.json`, so a lexicographic
        sort is chronological. Empty when the dir is absent or has no matches;
        the caller then falls back to the GitHub archive.
        """
        if self.directory.exists():
            return sorted(self.directory.glob(self.pattern))
        return []

    @staticmethod
    def _load_valid(path: Path) -> dict | None:
        """Parse a census file, returning it only if structurally complete.

        Complete = the three sections read() needs (instrument details,
        priceData, investors) are all present AND non-empty. The census writer
        rewrites its 80+ MB JSON in place and, on bad upstream days, has emitted
        files with investors present but an empty `instruments` block
        (2026-06-27/28): parseable yet useless, because with no id→symbol map
        every PI% collapses to None. Rejecting those here lets the reader fall
        back to the last good file instead of silently blanking the column.
        """
        try:
            with path.open() as f:
                data = json.load(f)
            details = data["instruments"]["details"]
            price_data = data["instruments"]["priceData"]
            investors = data["investors"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None
        if not details or not price_data or not investors:
            return None
        return data

    def _refresh_if_stale(self) -> bool:
        """Return True if cache is populated (either fresh or already cached)."""
        files = self._candidate_files()
        if not files:
            # No local files — try the GitHub archive (caches to ~/.etoro-tui/).
            remote = fetch_newest_census_file()
            if remote is not None:
                files = [remote]
        if not files:
            if not self._missing_logged:
                log.info("no census file found in %s", self.directory)
                self._missing_logged = True
            return bool(self._cache_key)

        newest = files[-1]
        cache_key = (newest, newest.stat().st_mtime)
        if self._cache_key == cache_key:
            # Already processed this newest-on-disk file (valid, or fell back
            # from it) — keep whatever _stale we last determined for it.
            return True

        # Newest changed. Walk newest→oldest for the first structurally-complete
        # file so a corrupt newest (empty instruments block) doesn't blank the UI.
        data: dict | None = None
        used: Path | None = None
        for candidate in reversed(files):
            data = self._load_valid(candidate)
            if data is not None:
                used = candidate
                break

        if data is None:
            if self._cache_key is not None:
                log.warning("no valid census file; serving previous cache")
                self._stale = True
                self._cache_key = cache_key  # don't rescan until newest changes
                return True
            log.warning("no valid census file and no cache to fall back on")
            return False

        details = data["instruments"]["details"]
        price_data = data["instruments"]["priceData"]
        investors = data["investors"]

        # Build instruments map (id → symbol + current price)
        id_to_symbol = {item["instrumentId"]: item["symbolFull"] for item in details}
        id_to_price = {item["instrumentId"]: item["currentPrice"] for item in price_data}
        instruments: dict[int, InstrumentInfo] = {}
        for inst_id, sym in id_to_symbol.items():
            price = id_to_price.get(inst_id)
            if price is not None:
                instruments[inst_id] = InstrumentInfo(symbol=sym, current_price=float(price))
        self._cache_instruments = instruments

        # Build PI% map over the TOP_N_PIS most-copied investors. The census is
        # already ordered by copiers, but sort defensively in case a future file
        # isn't. Denominator is the number actually taken (≤ TOP_N_PIS).
        top = sorted(investors, key=lambda inv: inv.get("copiers", 0) or 0, reverse=True)
        top = top[:TOP_N_PIS]
        counter: Counter[int] = Counter()
        for inv in top:
            held_ids = {pos["instrumentId"] for pos in inv["portfolio"]["positions"]}
            counter.update(held_ids)
        total = len(top)
        pi_pct: dict[str, float] = {}
        if total:
            for inst_id, count in counter.items():
                sym = id_to_symbol.get(inst_id)
                if sym:
                    pi_pct[sym.upper()] = round(count / total * 100, 2)
        self._cache_pi = pi_pct

        self._cache_key = cache_key
        self._stale = used != newest  # stale when we fell back to an older file
        return True

    def read(self) -> dict[str, float]:
        """Return {symbol: pct_of_top_PIs_holding} over the TOP_N_PIS most-copied PIs."""
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
