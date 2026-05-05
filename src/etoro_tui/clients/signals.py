"""Read etorotrade signals CSV with mtime-based caching."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional

from ..models import Signal


_BS_MAP: dict[str, Optional[Signal]] = {
    "B": "BUY",
    "S": "SELL",
    "H": "HOLD",
    "I": None,  # inconclusive
}

log = logging.getLogger(__name__)


class SignalsReader:
    """Reads `etoro.csv`, caches by mtime."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: dict[str, Optional[Signal]] = {}
        self._cache_mtime: float | None = None
        self._missing_logged = False

    def read(self) -> dict[str, Optional[Signal]]:
        """Return {symbol: signal or None}."""
        if not self.path.exists():
            if not self._missing_logged:
                log.info("signals CSV not found at %s", self.path)
                self._missing_logged = True
            return {}
        mtime = self.path.stat().st_mtime
        if self._cache_mtime == mtime:
            return self._cache
        result: dict[str, Optional[Signal]] = {}
        with self.path.open(newline="") as f:
            for row in csv.DictReader(f):
                tkr = row.get("TKR", "").strip().upper()
                bs = row.get("BS", "").strip()
                if not tkr:
                    continue
                result[tkr] = _BS_MAP.get(bs)
        self._cache = result
        self._cache_mtime = mtime
        return result
