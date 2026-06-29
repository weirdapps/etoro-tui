"""Previous-close lookup via yfinance.

Replaces the unreliable census `currentPrice` field as the "yesterday's close"
baseline for the header Δ% and the per-position Δday column. Census `currentPrice`
can be multi-day stale for some instruments (e.g. NVDA stuck on Friday's close
for three trading days running), making the daily Δ visibly wrong vs eToro web.
Yahoo's previous-close updates reliably after each session close, so the
daily Δ now matches what eToro web / Yahoo Finance show.

Lookup is best-effort: anything Yahoo doesn't know (eToro-internal CFD tickers,
weird crypto, network failure) is silently omitted from the response, and the
caller falls back to census. Cached for 30 min by default — Yahoo's previous
close is stable through the trading day, no need to hammer it.

yfinance is sync; we wrap it in `asyncio.to_thread` to keep the Textual event
loop responsive on the cold-cache fetch (~1-3 s for ~40 symbols batched).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# eToro names for synthetic indices → Yahoo tickers. Other symbols (US stocks,
# dotted .DE/.L/.HK/.CO listings, the GRE ETF) are already in a format Yahoo
# accepts natively.
_INDEX_TO_YAHOO: dict[str, str] = {
    "SPX500": "^GSPC",
    "NSDQ100": "^NDX",
    "DJ30": "^DJI",
    "EUSTX50": "^STOXX50E",
    "GER40": "^GDAXI",  # DAX
    "UK100": "^FTSE",  # FTSE 100
    "FRA40": "^FCHI",  # CAC 40
    "JPN225": "^N225",  # Nikkei 225
    "HKG50": "^HSI",  # Hang Seng
}

# eToro crypto symbols are bare bases (BTC, ETH, …); Yahoo uses BTC-USD form.
_CRYPTO_BASES: frozenset[str] = frozenset(
    {"BTC", "ETH", "XRP", "BCH", "ADA", "LTC", "EOS", "XLM", "NEO", "TRX", "ZEC", "DASH", "ETC"}
)


def to_yahoo_symbol(etoro_symbol: str) -> str | None:
    """eToro symbol → Yahoo ticker. Returns None for symbols Yahoo can't
    resolve (eToro-internal CFDs etc.) — caller falls back to census."""
    s = etoro_symbol.upper()
    if s in _INDEX_TO_YAHOO:
        return _INDEX_TO_YAHOO[s]
    if s in _CRYPTO_BASES:
        return f"{s}-USD"
    return s  # US tickers + dotted listings pass through


def _extract_prev_close(df: pd.DataFrame, yahoo_sym: str) -> float | None:
    """Pick the second-to-last Close from a yf.download response. Last bar is
    today's intraday; one before is yesterday's close. Returns None on NaN /
    missing column / single-row data.

    NaN rows are dropped first — batch downloads that include 24/7 instruments
    (BTC) extend the date index with weekend rows where stocks have NaN."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            closes = df[(yahoo_sym, "Close")]
        else:
            closes = df["Close"]
    except KeyError:
        return None
    closes = closes.dropna()
    if len(closes) < 2:
        return None
    val = closes.iloc[-2]
    return float(val) if val is not None and val > 0 else None


def _extract_last_two(df: pd.DataFrame, yahoo_sym: str) -> tuple[float, float] | None:
    """Return (last, prev) daily closes for an index — last bar ≈ today's live
    level, the one before it = previous session's close. NaNs are dropped first
    so a pre-market/holiday gap shows the prior move instead of blanking the
    index. With only one valid close, prev = last (renders at 0% rather than
    vanishing). Returns None when there's no usable close at all."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            closes = df[(yahoo_sym, "Close")]
        else:
            closes = df["Close"]
    except KeyError:
        return None
    closes = closes.dropna()
    if len(closes) == 0:
        return None
    last = float(closes.iloc[-1])
    if last <= 0:
        return None
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
    return last, prev


class YahooClient:
    """Async wrapper around yfinance with a TTL cache."""

    def __init__(self, ttl_seconds: int = 1800, index_ttl_seconds: int = 120) -> None:
        self._ttl = ttl_seconds
        # Indices move intraday, so they get a shorter TTL than position
        # prev-closes (which are stable through the trading day).
        self._index_ttl = index_ttl_seconds
        # etoro_symbol → (prev_close, fetched_at_epoch)
        self._cache: dict[str, tuple[float, float]] = {}
        # etoro_symbol(upper) → ((last, prev), fetched_at_epoch)
        self._index_cache: dict[str, tuple[tuple[float, float], float]] = {}

    async def fetch_prev_closes(self, symbols: list[str]) -> dict[str, float]:
        """Return {etoro_symbol: previous_close_in_listing_currency}.

        Symbols Yahoo can't resolve or that fail to fetch are silently omitted
        — the caller falls back to census for those. Cached for ttl_seconds
        per symbol; only expired/missing symbols hit the network."""
        now = time.monotonic()
        out: dict[str, float] = {}
        needed: dict[str, str] = {}  # yahoo_sym → etoro_sym
        for es in symbols:
            cached = self._cache.get(es)
            if cached and now - cached[1] < self._ttl:
                out[es] = cached[0]
                continue
            ys = to_yahoo_symbol(es)
            if ys is not None:
                needed[ys] = es
        if not needed:
            return out
        try:
            df = await asyncio.to_thread(self._download, list(needed))
        except Exception as e:  # noqa: BLE001 — yfinance raises diverse types
            log.warning("yfinance download failed: %s", e)
            return out
        if df is None or df.empty:
            return out
        for ys, es in needed.items():
            val = _extract_prev_close(df, ys)
            if val is not None and val > 0:
                self._cache[es] = (val, now)
                out[es] = val
        return out

    async def fetch_index_quotes(self, etoro_symbols: list[str]) -> dict[str, tuple[float, float]]:
        """Return {etoro_symbol_upper: (last, prev_close)} for header indices.

        Both values come straight from Yahoo's daily bars, decoupled from the
        eToro census — so standard market indices (S&P, Dow, …) always render
        regardless of whether a popular investor happens to hold a CFD on them.
        Symbols Yahoo can't resolve are silently omitted. Cached per symbol for
        index_ttl_seconds so the 5s header poll doesn't hammer Yahoo."""
        now = time.monotonic()
        out: dict[str, tuple[float, float]] = {}
        needed: dict[str, str] = {}  # yahoo_sym → etoro_sym(upper)
        for es in etoro_symbols:
            key = es.upper()
            cached = self._index_cache.get(key)
            if cached and now - cached[1] < self._index_ttl:
                out[key] = cached[0]
                continue
            ys = to_yahoo_symbol(key)
            if ys is not None:
                needed[ys] = key
        if not needed:
            return out
        try:
            df = await asyncio.to_thread(self._download, list(needed))
        except Exception as e:  # noqa: BLE001 — yfinance raises diverse types
            log.warning("yfinance index download failed: %s", e)
            return out
        if df is None or df.empty:
            return out
        for ys, key in needed.items():
            pair = _extract_last_two(df, ys)
            if pair is not None:
                self._index_cache[key] = (pair, now)
                out[key] = pair
        return out

    def _download(self, yahoo_tickers: list[str]) -> Any:
        """Sync yfinance call. period='5d' is enough to survive weekends +
        holidays and still give us yesterday's close as the second-to-last bar."""
        return yf.download(
            yahoo_tickers,
            period="5d",
            interval="1d",
            progress=False,
            group_by="ticker",
            auto_adjust=False,
        )
