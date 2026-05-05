"""Read newest etoro_census JSON and aggregate PI holdings per symbol."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

log = logging.getLogger(__name__)


class CensusReader:
    """Picks newest `etoro-data-*.json` in dir; mtime-cached."""

    def __init__(self, directory: Path, pattern: str) -> None:
        self.directory = directory
        self.pattern = pattern
        self._cache: dict[str, float] = {}
        self._cache_key: tuple[Path, float] | None = None
        self._missing_logged = False

    def _newest_file(self) -> Path | None:
        if not self.directory.exists():
            return None
        files = sorted(self.directory.glob(self.pattern))
        return files[-1] if files else None

    def read(self) -> dict[str, float]:
        """Return {symbol: pct_of_PIs_holding}."""
        newest = self._newest_file()
        if newest is None:
            if not self._missing_logged:
                log.info("no census file found in %s", self.directory)
                self._missing_logged = True
            return {}
        mtime = newest.stat().st_mtime
        cache_key = (newest, mtime)
        if self._cache_key == cache_key:
            return self._cache
        try:
            with newest.open() as f:
                data = json.load(f)
            id_to_symbol = {
                item["instrumentId"]: item["symbolFull"]
                for item in data["instruments"]["details"]
            }
            investors = data["investors"]
        except KeyError as e:
            log.error("census schema mismatch in %s: missing key %s", newest, e)
            raise
        if not investors:
            self._cache = {}
            self._cache_key = cache_key
            return self._cache
        counter: Counter[int] = Counter()
        for inv in investors:
            held_ids = {
                pos["instrumentId"] for pos in inv["portfolio"]["positions"]
            }
            counter.update(held_ids)
        total = len(investors)
        result: dict[str, float] = {}
        for inst_id, count in counter.items():
            sym = id_to_symbol.get(inst_id)
            if sym:
                result[sym.upper()] = round(count / total * 100, 2)
        self._cache = result
        self._cache_key = cache_key
        return result
