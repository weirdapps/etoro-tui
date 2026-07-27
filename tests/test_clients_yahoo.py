"""Tests for clients.yahoo — previous-close lookup via yfinance.

The Yahoo client is the trustworthy source for "yesterday's close" because the
census `currentPrice` field can be multi-day stale for some instruments. Tests
cover the symbol mapping (pure function), the cache (TTL behaviour), and the
fallback paths when yfinance fails or returns nothing.

The previous close comes from Yahoo's authoritative `fast_info.previous_close`
(the close of the last COMPLETED session, computed per-exchange) rather than a
positional guess into daily bars — see the regression test below. `_fetch_quote`
is the network seam; it is monkey-patched here so these unit tests never hit the
network.
"""

from __future__ import annotations

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
# YahooClient — fetch_prev_closes / fetch_index_quotes with a faked quote seam
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_quotes(monkeypatch):
    """Replace `_fetch_quote` (the per-ticker network seam) with a recorder.

    Tests set `.quotes` = {yahoo_symbol: (last_price, previous_close)} and read
    `.requested` (the yahoo symbols asked for — order is unspecified because the
    real client fetches concurrently, so assert with sets). Set `.exc` to make a
    fetch raise, simulating a Yahoo outage.
    """

    class Recorder:
        def __init__(self) -> None:
            self.quotes: dict[str, tuple[float | None, float | None]] = {}
            self.requested: list[str] = []
            self.exc: Exception | None = None

        def __call__(self, yahoo_sym: str) -> tuple[float | None, float | None]:
            self.requested.append(yahoo_sym)
            if self.exc is not None:
                raise self.exc
            return self.quotes.get(yahoo_sym, (None, None))

    rec = Recorder()
    monkeypatch.setattr(yahoo_module, "_fetch_quote", rec)
    return rec


async def test_prev_close_is_authoritative_previous_close_not_intraday_position(
    fake_quotes,
) -> None:
    """Regression: the Δday '−16% pre-market' bug.

    prev_close must be Yahoo's authoritative previous_close (last completed
    session), NOT a positional guess (iloc[-2]) into daily bars. Pre-market the
    old code took the second-to-last bar, which straddled TSLA's −14.5% crash
    day and reported a phantom −16% move. Here TSLA's last price is 313.03 and
    its true previous close is 311.38 → a small, correct move.
    """
    fake_quotes.quotes = {"TSLA": (313.03, 311.38)}  # (last_price, previous_close)
    c = YahooClient()
    out = await c.fetch_prev_closes(["TSLA"])
    assert out == {"TSLA": 311.38}


async def test_fetch_prev_closes_returns_authoritative_prev(fake_quotes) -> None:
    fake_quotes.quotes = {
        "AAPL": (300.10, 298.97),
        "MSFT": (415.00, 417.42),
    }
    c = YahooClient()
    out = await c.fetch_prev_closes(["AAPL", "MSFT"])
    assert out == {"AAPL": 298.97, "MSFT": 417.42}


async def test_fetch_prev_closes_maps_index_symbols(fake_quotes) -> None:
    """The returned dict is keyed by eToro symbol; the seam is asked for the
    mapped Yahoo symbol."""
    fake_quotes.quotes = {"^GSPC": (7480.0, 7500.0)}
    c = YahooClient()
    out = await c.fetch_prev_closes(["SPX500"])
    assert out == {"SPX500": 7500.0}
    assert fake_quotes.requested == ["^GSPC"]


async def test_fetch_prev_closes_maps_crypto(fake_quotes) -> None:
    fake_quotes.quotes = {"BTC-USD": (77300.0, 78207.04)}
    c = YahooClient()
    out = await c.fetch_prev_closes(["BTC"])
    assert out == {"BTC": 78207.04}


async def test_fetch_prev_closes_omits_missing_prev(fake_quotes) -> None:
    """A symbol with no previous_close (None) → absent from the response so the
    caller falls back to census."""
    fake_quotes.quotes = {
        "AAPL": (300.10, 298.97),
        "DELISTED": (None, None),
    }
    c = YahooClient()
    out = await c.fetch_prev_closes(["AAPL", "DELISTED"])
    assert "AAPL" in out
    assert "DELISTED" not in out


async def test_fetch_prev_closes_omits_nonpositive_prev(fake_quotes) -> None:
    """A zero/negative previous_close is treated as unusable (census fallback)."""
    fake_quotes.quotes = {"AAPL": (300.10, 298.97), "WEIRD": (10.0, 0.0)}
    c = YahooClient()
    out = await c.fetch_prev_closes(["AAPL", "WEIRD"])
    assert out == {"AAPL": 298.97}


async def test_fetch_prev_closes_caches_within_ttl(fake_quotes) -> None:
    """Second call inside TTL hits the cache, never re-asks Yahoo."""
    fake_quotes.quotes = {"AAPL": (300.10, 298.97)}
    c = YahooClient(ttl_seconds=1800)
    first = await c.fetch_prev_closes(["AAPL"])
    second = await c.fetch_prev_closes(["AAPL"])
    assert first == second == {"AAPL": 298.97}
    assert fake_quotes.requested == ["AAPL"]  # only one network call


async def test_fetch_prev_closes_re_fetches_after_ttl(fake_quotes) -> None:
    """Past TTL, the symbol is re-fetched."""
    fake_quotes.quotes = {"AAPL": (300.10, 298.97)}
    c = YahooClient(ttl_seconds=0)  # instant expiry
    await c.fetch_prev_closes(["AAPL"])
    await c.fetch_prev_closes(["AAPL"])
    assert fake_quotes.requested == ["AAPL", "AAPL"]


async def test_fetch_prev_closes_only_asks_for_missing_symbols(fake_quotes) -> None:
    """If half the symbols are cached, only the new half hits Yahoo."""
    fake_quotes.quotes = {"AAPL": (300.10, 298.97), "MSFT": (415.00, 417.42)}
    c = YahooClient()
    await c.fetch_prev_closes(["AAPL"])
    fake_quotes.requested.clear()
    out = await c.fetch_prev_closes(["AAPL", "MSFT"])
    assert out == {"AAPL": 298.97, "MSFT": 417.42}
    # Second call only asked for MSFT (AAPL served from cache).
    assert fake_quotes.requested == ["MSFT"]


async def test_fetch_prev_closes_swallows_fetch_exception(fake_quotes) -> None:
    """A Yahoo failure must NOT crash the app — return whatever cache has."""
    fake_quotes.exc = RuntimeError("Yahoo rate-limited")
    c = YahooClient()
    out = await c.fetch_prev_closes(["AAPL"])
    assert out == {}


async def test_fetch_prev_closes_returns_cache_when_yahoo_fails_later(fake_quotes) -> None:
    """If a prior call populated the cache, a later failure returns the cache."""
    fake_quotes.quotes = {"AAPL": (300.10, 298.97)}
    c = YahooClient()
    await c.fetch_prev_closes(["AAPL"])
    fake_quotes.exc = RuntimeError("network")
    out = await c.fetch_prev_closes(["AAPL", "MSFT"])  # MSFT triggers fetch, fails
    assert out == {"AAPL": 298.97}  # AAPL from cache, MSFT omitted


async def test_fetch_prev_closes_empty_input_short_circuits(fake_quotes) -> None:
    """Empty list never calls Yahoo."""
    c = YahooClient()
    out = await c.fetch_prev_closes([])
    assert out == {}
    assert fake_quotes.requested == []


async def test_fetch_prev_closes_skips_unmappable_symbols(fake_quotes) -> None:
    """Symbols to_yahoo_symbol returns None for never hit Yahoo."""
    import etoro_tui.clients.yahoo as ym

    orig = ym.to_yahoo_symbol
    ym.to_yahoo_symbol = lambda s: None if s == "INTERNAL" else orig(s)
    try:
        fake_quotes.quotes = {"AAPL": (300.10, 298.97)}
        c = YahooClient()
        out = await c.fetch_prev_closes(["AAPL", "INTERNAL"])
        assert out == {"AAPL": 298.97}
        assert fake_quotes.requested == ["AAPL"]  # INTERNAL never sent to Yahoo
    finally:
        ym.to_yahoo_symbol = orig


# ---------------------------------------------------------------------------
# YahooClient.fetch_index_quotes — (last, prev) for the header bar
# ---------------------------------------------------------------------------


async def test_fetch_index_quotes_returns_last_and_prev(fake_quotes) -> None:
    """last = current level, prev = previous close. Keyed by eToro symbol (upper)."""
    fake_quotes.quotes = {
        "^GSPC": (7480.10, 7425.75),
        "^DJI": (40050.0, 40123.0),
    }
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500", "DJ30"])
    assert out == {"SPX500": (7480.10, 7425.75), "DJ30": (40050.0, 40123.0)}
    assert set(fake_quotes.requested) == {"^GSPC", "^DJI"}


async def test_fetch_index_quotes_missing_prev_uses_last(fake_quotes) -> None:
    """Only a last price (fresh listing / holiday) → prev = last so the index
    still renders, at 0% change instead of vanishing."""
    fake_quotes.quotes = {"^GSPC": (7500.0, None)}
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500"])
    assert out == {"SPX500": (7500.0, 7500.0)}


async def test_fetch_index_quotes_omits_when_no_last(fake_quotes) -> None:
    """No usable last price at all → symbol omitted (caller skips it)."""
    fake_quotes.quotes = {"^GSPC": (None, None)}
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500"])
    assert out == {}


async def test_fetch_index_quotes_caches_within_ttl(fake_quotes) -> None:
    """Index quotes cache on their own short TTL — header polls every 5s but
    must not hammer Yahoo on every tick."""
    fake_quotes.quotes = {"^GSPC": (7480.10, 7425.75)}
    c = YahooClient(index_ttl_seconds=120)
    first = await c.fetch_index_quotes(["SPX500"])
    second = await c.fetch_index_quotes(["SPX500"])
    assert first == second == {"SPX500": (7480.10, 7425.75)}
    assert fake_quotes.requested == ["^GSPC"]


async def test_fetch_index_quotes_swallows_exception(fake_quotes) -> None:
    """A Yahoo failure must not crash the header — return whatever cache has."""
    fake_quotes.exc = RuntimeError("Yahoo rate-limited")
    c = YahooClient()
    out = await c.fetch_index_quotes(["SPX500"])
    assert out == {}


async def test_fetch_index_quotes_empty_input_short_circuits(fake_quotes) -> None:
    c = YahooClient()
    out = await c.fetch_index_quotes([])
    assert out == {}
    assert fake_quotes.requested == []
