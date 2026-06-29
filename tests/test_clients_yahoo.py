"""Tests for clients.yahoo — previous-close lookup via yfinance.

The Yahoo client is the trustworthy source for "yesterday's close" because the
census `currentPrice` field can be multi-day stale for some instruments. Tests
cover the symbol mapping (pure function), the cache (TTL behaviour), and the
fallback paths when yfinance raises or returns NaN.

yfinance itself is monkey-patched — these are unit tests, never hit the network.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from etoro_tui.clients import yahoo as yahoo_module
from etoro_tui.clients.yahoo import YahooClient, to_yahoo_symbol

# ---------------------------------------------------------------------------
# to_yahoo_symbol — pure mapping
# ---------------------------------------------------------------------------


def test_to_yahoo_symbol_us_stock_passthrough() -> None:
    assert to_yahoo_symbol("AAPL") == "AAPL"
    assert to_yahoo_symbol("aapl") == "AAPL"  # uppercases


def test_to_yahoo_symbol_indices() -> None:
    assert to_yahoo_symbol("SPX500") == "^GSPC"
    assert to_yahoo_symbol("NSDQ100") == "^NDX"
    assert to_yahoo_symbol("DJ30") == "^DJI"
    assert to_yahoo_symbol("EUSTX50") == "^STOXX50E"


def test_to_yahoo_symbol_european_and_asian_indices() -> None:
    """Indices listed in config.example.toml must all map to a Yahoo ticker."""
    assert to_yahoo_symbol("GER40") == "^GDAXI"  # DAX
    assert to_yahoo_symbol("UK100") == "^FTSE"  # FTSE 100
    assert to_yahoo_symbol("FRA40") == "^FCHI"  # CAC 40
    assert to_yahoo_symbol("JPN225") == "^N225"  # Nikkei 225
    assert to_yahoo_symbol("HKG50") == "^HSI"  # Hang Seng


def test_to_yahoo_symbol_crypto_gets_usd_suffix() -> None:
    assert to_yahoo_symbol("BTC") == "BTC-USD"
    assert to_yahoo_symbol("ETH") == "ETH-USD"


def test_to_yahoo_symbol_dotted_listings_passthrough() -> None:
    """Yahoo natively accepts the same .DE / .L / .MI suffixes eToro uses."""
    assert to_yahoo_symbol("PRU.L") == "PRU.L"
    assert to_yahoo_symbol("DTE.DE") == "DTE.DE"
    assert to_yahoo_symbol("UCG.MI") == "UCG.MI"


def test_to_yahoo_symbol_hk_leading_zeros() -> None:
    """Yahoo expects no leading zeros on HK tickers."""
    assert to_yahoo_symbol("0700.HK") == "700.HK"
    assert to_yahoo_symbol("00175.HK") == "175.HK"
    assert to_yahoo_symbol("9988.HK") == "9988.HK"


def test_to_yahoo_symbol_suffix_remap() -> None:
    """.NV → .AS (Amsterdam), .ASX → .AX (Australia), etc."""
    assert to_yahoo_symbol("ASML.NV") == "ASML.AS"
    assert to_yahoo_symbol("HEIA.NV") == "HEIA.AS"


def test_to_yahoo_symbol_data_fetch_substitutions() -> None:
    """Instruments that need a completely different Yahoo ticker."""
    assert to_yahoo_symbol("LYXGRE.DE") == "GRE.PA"


def test_to_yahoo_symbol_copenhagen_share_classes() -> None:
    assert to_yahoo_symbol("NOVOB.CO") == "NOVO-B.CO"


def test_to_yahoo_symbol_commodities_and_fx() -> None:
    assert to_yahoo_symbol("GOLD") == "GC=F"
    assert to_yahoo_symbol("OIL") == "CL=F"
    assert to_yahoo_symbol("EURUSD") == "EURUSD=X"


# ---------------------------------------------------------------------------
# YahooClient — fetch_prev_closes with monkey-patched yfinance
# ---------------------------------------------------------------------------


def _multi_ticker_df(rows: dict[str, list[float | None]]) -> pd.DataFrame:
    """Build a yf.download-style DataFrame with group_by='ticker'.

    rows = {ticker: [day1_close, day2_close, ...]}. The first column under each
    ticker is "Close" — the only column the client reads.
    """
    cols = pd.MultiIndex.from_tuples([(t, "Close") for t in rows.keys()])
    data = {(t, "Close"): closes for t, closes in rows.items()}
    return pd.DataFrame(data, columns=cols)


@pytest.fixture
def fake_download(monkeypatch):
    """Replace yf.download with a recorder. Returns the recorder so tests can
    set its `.return_value` and inspect `.calls`."""

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []
            self.return_value: pd.DataFrame | None = None
            self.exc: Exception | None = None

        def __call__(self, tickers, **kwargs):  # noqa: ARG002
            self.calls.append(list(tickers) if isinstance(tickers, list) else [tickers])
            if self.exc is not None:
                raise self.exc
            return self.return_value

    rec = Recorder()
    monkeypatch.setattr(yahoo_module.yf, "download", rec)
    return rec


async def test_fetch_prev_closes_picks_second_to_last_close(fake_download) -> None:
    """The most recent close is yesterday's; the last row is today's intraday."""
    fake_download.return_value = _multi_ticker_df(
        {
            "AAPL": [297.84, 298.97, 298.20],  # Mon, Tue, Wed-intraday
            "MSFT": [423.54, 417.42, 414.30],
        }
    )
    c = YahooClient()
    out = await c.fetch_prev_closes(["AAPL", "MSFT"])
    assert out == {"AAPL": 298.97, "MSFT": 417.42}


async def test_fetch_prev_closes_maps_index_symbols(fake_download) -> None:
    """The returned dict is keyed by eToro symbol, not Yahoo symbol."""
    fake_download.return_value = _multi_ticker_df(
        {
            "^GSPC": [7400.0, 7500.0, 7480.0],
        }
    )
    c = YahooClient()
    out = await c.fetch_prev_closes(["SPX500"])
    assert out == {"SPX500": 7500.0}
    # And the request went to Yahoo with the mapped symbol.
    assert fake_download.calls == [["^GSPC"]]


async def test_fetch_prev_closes_maps_crypto(fake_download) -> None:
    fake_download.return_value = _multi_ticker_df({"BTC-USD": [77000.0, 78207.04, 77300.0]})
    c = YahooClient()
    out = await c.fetch_prev_closes(["BTC"])
    assert out == {"BTC": 78207.04}


async def test_fetch_prev_closes_omits_nan_rows(fake_download) -> None:
    """NaN second-to-last close → symbol absent from the response (census fallback)."""
    fake_download.return_value = _multi_ticker_df(
        {
            "AAPL": [297.84, 298.97, 298.20],
            "DELISTED": [math.nan, math.nan, math.nan],
        }
    )
    c = YahooClient()
    out = await c.fetch_prev_closes(["AAPL", "DELISTED"])
    assert "AAPL" in out
    assert "DELISTED" not in out


async def test_fetch_prev_closes_caches_within_ttl(fake_download) -> None:
    """Second call inside TTL hits the cache, never re-asks Yahoo."""
    fake_download.return_value = _multi_ticker_df({"AAPL": [297.84, 298.97, 298.20]})
    c = YahooClient(ttl_seconds=1800)
    first = await c.fetch_prev_closes(["AAPL"])
    second = await c.fetch_prev_closes(["AAPL"])
    assert first == second == {"AAPL": 298.97}
    assert len(fake_download.calls) == 1  # only one network call


async def test_fetch_prev_closes_re_fetches_after_ttl(fake_download) -> None:
    """Past TTL, the symbol is re-fetched."""
    fake_download.return_value = _multi_ticker_df({"AAPL": [297.84, 298.97, 298.20]})
    c = YahooClient(ttl_seconds=0)  # instant expiry
    await c.fetch_prev_closes(["AAPL"])
    await c.fetch_prev_closes(["AAPL"])
    assert len(fake_download.calls) == 2


async def test_fetch_prev_closes_only_asks_for_missing_symbols(fake_download) -> None:
    """If half the symbols are cached, only the new half hits Yahoo."""
    fake_download.return_value = _multi_ticker_df({"AAPL": [297.84, 298.97, 298.20]})
    c = YahooClient()
    await c.fetch_prev_closes(["AAPL"])
    fake_download.return_value = _multi_ticker_df({"MSFT": [423.54, 417.42, 414.30]})
    out = await c.fetch_prev_closes(["AAPL", "MSFT"])
    assert out == {"AAPL": 298.97, "MSFT": 417.42}
    # Second call only asked for MSFT (the missing one).
    assert fake_download.calls[1] == ["MSFT"]


async def test_fetch_prev_closes_swallows_yfinance_exception(fake_download) -> None:
    """A yfinance failure must NOT crash the app — return whatever cache has."""
    fake_download.exc = RuntimeError("Yahoo rate-limited")
    c = YahooClient()
    out = await c.fetch_prev_closes(["AAPL"])
    assert out == {}


async def test_fetch_prev_closes_returns_cache_when_yahoo_fails_later(fake_download) -> None:
    """If a prior call populated the cache, a later failure returns the cache."""
    fake_download.return_value = _multi_ticker_df({"AAPL": [297.84, 298.97, 298.20]})
    c = YahooClient()
    await c.fetch_prev_closes(["AAPL"])
    fake_download.exc = RuntimeError("network")
    fake_download.return_value = None
    out = await c.fetch_prev_closes(["AAPL", "MSFT"])  # MSFT triggers fetch, fails
    assert out == {"AAPL": 298.97}  # AAPL from cache, MSFT omitted


async def test_fetch_prev_closes_empty_input_short_circuits(fake_download) -> None:
    """Empty list never calls yfinance."""
    c = YahooClient()
    out = await c.fetch_prev_closes([])
    assert out == {}
    assert fake_download.calls == []


async def test_fetch_prev_closes_skips_unmappable_symbols(fake_download) -> None:
    """Symbols to_yahoo_symbol returns None for never hit Yahoo."""
    # Patch to_yahoo_symbol so "INTERNAL" returns None
    import etoro_tui.clients.yahoo as ym

    orig = ym.to_yahoo_symbol
    ym.to_yahoo_symbol = lambda s: None if s == "INTERNAL" else orig(s)
    try:
        fake_download.return_value = _multi_ticker_df({"AAPL": [297.84, 298.97, 298.20]})
        c = YahooClient()
        out = await c.fetch_prev_closes(["AAPL", "INTERNAL"])
        assert out == {"AAPL": 298.97}
        # INTERNAL was never sent to Yahoo
        assert fake_download.calls[0] == ["AAPL"]
    finally:
        ym.to_yahoo_symbol = orig


async def test_fetch_prev_closes_single_ticker_df_shape(fake_download) -> None:
    """When yf.download is called with one ticker, the returned DataFrame has
    flat columns (Open/Close/...) rather than a MultiIndex. The client must
    cope with both shapes."""
    # Flat-column DataFrame as yf.download returns for a single ticker
    flat = pd.DataFrame({"Close": [297.84, 298.97, 298.20]})
    fake_download.return_value = flat
    c = YahooClient()
    out = await c.fetch_prev_closes(["AAPL"])
    assert out == {"AAPL": 298.97}


# ---------------------------------------------------------------------------
# YahooClient.fetch_index_quotes — (last, prev) for the header bar
# ---------------------------------------------------------------------------


async def test_fetch_index_quotes_returns_last_and_prev(fake_download) -> None:
    """Last bar ≈ today's live level; the bar before it = previous close.
    Keyed by eToro symbol (upper), not the Yahoo ticker."""
    fake_download.return_value = _multi_ticker_df(
        {
            "^GSPC": [7400.0, 7425.75, 7480.10],  # day-before, prev, today-intraday
            "^DJI": [40000.0, 40123.0, 40050.0],
        }
    )
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500", "DJ30"])
    assert out == {"SPX500": (7480.10, 7425.75), "DJ30": (40050.0, 40123.0)}
    # Requests used the mapped Yahoo tickers.
    assert fake_download.calls == [["^GSPC", "^DJI"]]


async def test_fetch_index_quotes_single_bar_prev_equals_last(fake_download) -> None:
    """Only one valid close (fresh listing / holiday week) → prev = last so the
    index still renders, at 0% change instead of vanishing."""
    fake_download.return_value = _multi_ticker_df({"^GSPC": [7500.0]})
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500"])
    assert out == {"SPX500": (7500.0, 7500.0)}


async def test_fetch_index_quotes_drops_nan_last_bar(fake_download) -> None:
    """A NaN today-bar (pre-market) falls back to the last two valid closes —
    the index shows yesterday's move rather than disappearing."""
    fake_download.return_value = _multi_ticker_df({"^GSPC": [7400.0, 7425.75, math.nan]})
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500"])
    assert out == {"SPX500": (7425.75, 7400.0)}


async def test_fetch_index_quotes_omits_all_nan(fake_download) -> None:
    """No valid closes at all → symbol omitted (caller skips it)."""
    fake_download.return_value = _multi_ticker_df({"^GSPC": [math.nan, math.nan]})
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500"])
    assert out == {}


async def test_fetch_index_quotes_caches_within_ttl(fake_download) -> None:
    """Index quotes cache on their own short TTL — header polls every 5s but
    must not hammer Yahoo on every tick."""
    fake_download.return_value = _multi_ticker_df({"^GSPC": [7400.0, 7425.75, 7480.10]})
    c = YahooClient(index_ttl_seconds=120)
    first = await c.fetch_index_quotes(["SPX500"])
    second = await c.fetch_index_quotes(["SPX500"])
    assert first == second == {"SPX500": (7480.10, 7425.75)}
    assert len(fake_download.calls) == 1


async def test_fetch_index_quotes_swallows_exception(fake_download) -> None:
    """A yfinance failure must not crash the header — return whatever cache has."""
    fake_download.exc = RuntimeError("Yahoo rate-limited")
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500"])
    assert out == {}


async def test_fetch_index_quotes_empty_input_short_circuits(fake_download) -> None:
    c = YahooClient()
    out = await c.fetch_index_quotes([])
    assert out == {}
    assert fake_download.calls == []
