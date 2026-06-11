"""Unit tests for app.py pure business logic.

Covers:
  - _overlay_fields: single source of truth for the overlay-kwargs dict
  - _to_position price fallback: live → bid → census, never crashes on None
  - _to_position prev_close: Yahoo overrides stale census, fallback chain
  - _build_indices: header bar priced from Yahoo, decoupled from census
  - _day_change_pct formatter: percent display, sign, missing-prev fallback
  - _previous_close_equity: baseline for today's Δ that mirrors SPX
"""

from datetime import UTC, datetime

import pytest

from etoro_tui.app import (
    _build_indices,
    _overlay_fields,
    _previous_close_equity,
    _to_position,
)
from etoro_tui.clients.census import InstrumentInfo
from etoro_tui.clients.signals import Fundamentals
from etoro_tui.models import Position
from etoro_tui.widgets.positions_table import _day_change_pct

# ---------------------------------------------------------------------------
# _overlay_fields
# ---------------------------------------------------------------------------


def test_overlay_fields_with_full_data() -> None:
    fund = Fundamentals(
        signal="BUY",
        pe_trailing=33.5,
        pe_forward=29.0,
        upside_pct=8.6,
        analyst_buy_pct=53.0,
        analyst_momentum=4.0,
        target_price=210.0,
    )
    out = _overlay_fields("AAPL", fund, {"AAPL": 22.0})
    assert out["signal"] == "BUY"
    assert out["pi_pct"] == 22.0
    assert out["pe_trailing"] == 33.5
    assert out["pe_forward"] == 29.0
    assert out["upside_pct"] == 8.6
    assert out["analyst_buy_pct"] == 53.0
    assert out["analyst_momentum"] == 4.0
    assert out["target_price"] == 210.0


def test_overlay_fields_no_fundamentals() -> None:
    out = _overlay_fields("UNKNOWN", None, {})
    assert out["signal"] is None
    assert out["pi_pct"] is None
    assert out["pe_trailing"] is None
    assert out["pe_forward"] is None
    assert out["upside_pct"] is None
    assert out["analyst_buy_pct"] is None
    assert out["analyst_momentum"] is None
    assert out["target_price"] is None


def test_overlay_fields_pi_lookup() -> None:
    """Symbol absent from PI map → pi_pct is None (not 0 or KeyError)."""
    out = _overlay_fields("UNKNOWN", None, {"AAPL": 22.0})
    assert out["pi_pct"] is None


# ---------------------------------------------------------------------------
# _to_position price-fallback paths
# ---------------------------------------------------------------------------


def _raw(
    inst_id: int = 1001, units: float = 10, open_rate: float = 150.0, is_buy: bool = True
) -> dict:
    return {
        "positionID": 42,
        "instrumentID": inst_id,
        "units": units,
        "openRate": open_rate,
        "openConversionRate": 1.0,
        "isBuy": is_buy,
        "openDateTime": "2026-01-01T10:00:00.000Z",
    }


@pytest.fixture
def instruments() -> dict:
    return {1001: InstrumentInfo(symbol="AAPL", current_price=200.0)}


def test_to_position_uses_live_rate_when_present(
    instruments: dict,
) -> None:
    rates = {1001: {"lastExecution": 195.40, "conversionRateAsk": 1.0}}
    p = _to_position(_raw(), instruments, {}, {}, rates)
    assert p is not None
    assert p.current_rate == 195.40
    # prev_close = census.current_price × current_ocr (1.0)
    assert p.prev_close == 200.0


def test_to_position_falls_back_to_bid_when_lastexec_none(
    instruments: dict,
) -> None:
    rates = {1001: {"lastExecution": None, "Bid": 194.50, "conversionRateAsk": 1.0}}
    p = _to_position(_raw(), instruments, {}, {}, rates)
    assert p is not None
    assert p.current_rate == 194.50


def test_to_position_falls_back_to_census_when_lastexec_zero(
    instruments: dict,
) -> None:
    """0.0 means broken/glitched price; should NOT be used."""
    rates = {1001: {"lastExecution": 0.0, "Bid": 0.0, "bid": 0.0, "conversionRateAsk": 1.0}}
    p = _to_position(_raw(), instruments, {}, {}, rates)
    assert p is not None
    # All live keys are 0 → falls back to census (200.0 × open_ocr 1.0)
    assert p.current_rate == 200.0


def test_to_position_falls_back_when_all_keys_missing(
    instruments: dict,
) -> None:
    """Empty rates dict for the instrument → census fallback, no None crash."""
    rates = {1001: {}}
    p = _to_position(_raw(), instruments, {}, {}, rates)
    assert p is not None
    assert p.current_rate == 200.0  # census price (200.0) × open_ocr (1.0)


def test_to_position_falls_back_when_no_rates_at_all(
    instruments: dict,
) -> None:
    """rates=None → census fallback path."""
    p = _to_position(_raw(), instruments, {}, {}, None)
    assert p is not None
    assert p.current_rate == 200.0


# ---------------------------------------------------------------------------
# _day_change_pct formatter
# ---------------------------------------------------------------------------


def _text_styles(t) -> str:
    """Concatenate every style applied in the Text — top-level + each span."""
    return str(t.style) + " " + " ".join(str(s.style) for s in t.spans)


def test_day_change_pct_positive() -> None:
    text = _day_change_pct(195.40, 194.58)
    assert "+0.42%" in text.plain
    assert "▴" in text.plain  # small-gain triangle for <1%
    assert "green" in _text_styles(text)


def test_day_change_pct_negative() -> None:
    text = _day_change_pct(198.80, 205.20)
    assert "-3.12%" in text.plain
    assert "▼" in text.plain  # big-loss triangle for ≥1%
    assert "red" in _text_styles(text)


def test_day_change_pct_zero_change() -> None:
    text = _day_change_pct(100.0, 100.0)
    assert "+0.00%" in text.plain  # treated as ≥0 → green
    assert "green" in _text_styles(text)


def test_day_change_pct_missing_prev() -> None:
    text = _day_change_pct(100.0, None)
    assert "—" in text.plain
    assert "dim" in str(text.style)


def test_day_change_pct_zero_prev() -> None:
    """Avoid divide-by-zero on bad census data."""
    text = _day_change_pct(100.0, 0.0)
    assert "—" in text.plain


# ---------------------------------------------------------------------------
# _previous_close_equity — baseline for today's Δ
# ---------------------------------------------------------------------------


def _pos(
    *,
    symbol: str = "AAPL",
    units: float = 10,
    open_rate: float = 150.0,
    current_rate: float = 200.0,
    prev_close: float | None = 190.0,
    open_ts: datetime = datetime(2026, 1, 1, 10, tzinfo=UTC),
    direction: str = "Buy",
) -> Position:
    """Build a Position fixture with only the fields the baseline uses."""
    return Position(
        position_id=1,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        units=units,
        open_rate=open_rate,
        current_rate=current_rate,
        value=units * current_rate,
        pnl=(current_rate - open_rate) * units,
        pnl_pct=(current_rate - open_rate) / open_rate * 100,
        open_ts=open_ts,
        prev_close=prev_close,
    )


def test_previous_close_equity_uses_prev_close_for_held_positions() -> None:
    """Baseline = sum(units × prev_close) + cash for positions held since before today."""
    now = datetime(2026, 5, 19, 14, tzinfo=UTC)
    positions = (
        _pos(symbol="AAPL", units=10, prev_close=190.0, current_rate=200.0),
        _pos(symbol="MSFT", units=5, prev_close=400.0, current_rate=410.0),
    )
    baseline = _previous_close_equity(positions, cash=1000.0, now=now)
    # 10×190 + 5×400 + 1000 = 1900 + 2000 + 1000 = 4900
    assert baseline == pytest.approx(4900.0)


def test_previous_close_equity_uses_open_rate_for_today_opened() -> None:
    """Position opened today (UTC) uses open_rate, not prev_close — only the
    post-open move counts toward today's delta, matching eToro."""
    now = datetime(2026, 5, 19, 14, tzinfo=UTC)
    opened_today = datetime(2026, 5, 19, 10, tzinfo=UTC)
    positions = (
        _pos(
            symbol="NVDA",
            units=4,
            open_rate=120.0,
            current_rate=125.0,
            prev_close=118.0,  # would be wrong to use — position didn't exist yesterday
            open_ts=opened_today,
        ),
    )
    baseline = _previous_close_equity(positions, cash=0.0, now=now)
    # 4 × 120 (open_rate, NOT 118 prev_close) = 480
    assert baseline == pytest.approx(480.0)


def test_previous_close_equity_falls_back_to_current_when_prev_close_missing() -> None:
    """No prev_close (census miss) AND not opened today → use current_rate so
    the position contributes 0 to the delta (conservative)."""
    now = datetime(2026, 5, 19, 14, tzinfo=UTC)
    positions = (_pos(units=10, current_rate=200.0, prev_close=None),)
    baseline = _previous_close_equity(positions, cash=500.0, now=now)
    # 10 × 200 (current_rate fallback) + 500 = 2500
    assert baseline == pytest.approx(2500.0)


def test_previous_close_equity_delta_is_pure_price_move() -> None:
    """Same-day deposit invariance: delta = equity - baseline should equal the
    sum of per-position price moves, with cash cancelling out."""
    now = datetime(2026, 5, 19, 14, tzinfo=UTC)
    positions = (
        _pos(symbol="AAPL", units=10, prev_close=190.0, current_rate=200.0),
        _pos(symbol="MSFT", units=5, prev_close=400.0, current_rate=410.0),
    )
    equity = sum(p.value for p in positions) + 1234.56
    baseline = _previous_close_equity(positions, cash=1234.56, now=now)
    delta = equity - baseline
    # 10×(200−190) + 5×(410−400) = 100 + 50 = 150
    assert delta == pytest.approx(150.0)


def test_previous_close_equity_cash_only() -> None:
    """No positions → baseline equals cash."""
    now = datetime(2026, 5, 19, 14, tzinfo=UTC)
    assert _previous_close_equity((), cash=5000.0, now=now) == pytest.approx(5000.0)


def test_previous_close_equity_open_ts_local_timezone_normalised_to_utc() -> None:
    """A position opened 2026-05-19 02:00 Athens (= 2026-05-18 23:00 UTC) was
    opened YESTERDAY in UTC — must use prev_close, not open_rate."""
    from datetime import timedelta, timezone

    athens = timezone(timedelta(hours=3))
    now = datetime(2026, 5, 19, 14, tzinfo=UTC)
    opened_yesterday_utc = datetime(2026, 5, 19, 2, tzinfo=athens)  # = 23:00 UTC prior day
    positions = (
        _pos(
            units=10,
            open_rate=120.0,
            current_rate=125.0,
            prev_close=118.0,
            open_ts=opened_yesterday_utc,
        ),
    )
    baseline = _previous_close_equity(positions, cash=0.0, now=now)
    # 10 × 118 (prev_close, because opened yesterday UTC) = 1180
    assert baseline == pytest.approx(1180.0)


# ---------------------------------------------------------------------------
# _to_position with yahoo_prev — Yahoo overrides census for prev_close
# ---------------------------------------------------------------------------


def test_to_position_uses_yahoo_prev_when_present(instruments: dict) -> None:
    """Yahoo's previous-close wins over census `currentPrice` for prev_close."""
    rates = {1001: {"lastExecution": 195.40, "conversionRateAsk": 1.0}}
    yahoo_prev = {"AAPL": 197.50}
    p = _to_position(_raw(), instruments, {}, {}, rates, yahoo_prev=yahoo_prev)
    assert p is not None
    # prev_close = yahoo_prev (197.50) × current_ocr (1.0) — NOT census 200.0
    assert p.prev_close == 197.50
    # quote_prev (listing-currency display) also uses Yahoo
    assert p.quote_prev == 197.50


def test_to_position_falls_back_to_census_when_yahoo_missing(instruments: dict) -> None:
    """If Yahoo doesn't have the symbol, prev_close still comes from census."""
    rates = {1001: {"lastExecution": 195.40, "conversionRateAsk": 1.0}}
    p = _to_position(_raw(), instruments, {}, {}, rates, yahoo_prev={})
    assert p is not None
    assert p.prev_close == 200.0  # census fallback


def test_to_position_yahoo_overrides_stale_census(instruments: dict) -> None:
    """Concrete regression: census stuck on Friday's $300.23 but real Tue close was $298.97.
    Yahoo must win so the Δday matches eToro web."""
    # Simulate a stale census: instrument map says current_price=300.23 (wrong)
    stale_instruments = {1001: InstrumentInfo(symbol="AAPL", current_price=300.23)}
    rates = {1001: {"lastExecution": 298.20, "conversionRateAsk": 1.0}}
    yahoo_prev = {"AAPL": 298.97}
    p = _to_position(_raw(), stale_instruments, {}, {}, rates, yahoo_prev=yahoo_prev)
    assert p is not None
    assert p.prev_close == 298.97
    # Δday = (298.20 - 298.97) / 298.97 ≈ -0.26% (matches eToro web)


def test_to_position_yahoo_zero_or_negative_ignored(instruments: dict) -> None:
    """A 0/negative from Yahoo (NaN→0 leak, bad data) must NOT override census."""
    rates = {1001: {"lastExecution": 195.40, "conversionRateAsk": 1.0}}
    p = _to_position(_raw(), instruments, {}, {}, rates, yahoo_prev={"AAPL": 0.0})
    assert p is not None
    assert p.prev_close == 200.0  # census fallback (Yahoo zero rejected)


def test_to_position_yahoo_applies_fx_for_non_usd_listing() -> None:
    """Yahoo returns prev_close in listing currency — caller multiplies by
    current_ocr to get USD. Same convention as census fallback."""
    # EUR-listed stock: openConversionRate=1.10 (EUR→USD)
    eur_instruments = {1001: InstrumentInfo(symbol="DTE.DE", current_price=27.75)}
    raw_eur = {
        "positionID": 42,
        "instrumentID": 1001,
        "units": 100,
        "openRate": 25.0,
        "openConversionRate": 1.08,
        "isBuy": True,
        "openDateTime": "2026-01-01T10:00:00.000Z",
    }
    rates = {1001: {"lastExecution": 29.29, "conversionRateAsk": 1.10}}
    yahoo_prev = {"DTE.DE": 28.50}
    p = _to_position(raw_eur, eur_instruments, {}, {}, rates, yahoo_prev=yahoo_prev)
    assert p is not None
    # prev_close USD = yahoo_prev EUR × current_ocr = 28.50 × 1.10 = 31.35
    assert p.prev_close == pytest.approx(31.35)


# ---------------------------------------------------------------------------
# _build_indices — header bar priced from Yahoo, decoupled from census
# ---------------------------------------------------------------------------


def test_build_indices_computes_change_from_yahoo_last_and_prev() -> None:
    """change_pct = (last − prev) / prev × 100, both from Yahoo daily bars."""
    specs = [("S&P 500", "SPX500")]
    quotes = {"SPX500": (7480.10, 7425.75)}
    out = _build_indices(specs, quotes)
    assert len(out) == 1
    assert out[0].name == "S&P 500"
    assert out[0].last == 7480.10
    assert out[0].change_pct == pytest.approx((7480.10 - 7425.75) / 7425.75 * 100)


def test_build_indices_preserves_spec_priority_order() -> None:
    """Output order follows the configured spec order (header shows the first
    N that fit) — not dict/iteration order of the quotes."""
    specs = [("S&P 500", "SPX500"), ("Dow 30", "DJ30"), ("NASDAQ", "NSDQ100")]
    quotes = {
        "NSDQ100": (17234.0, 17100.0),
        "SPX500": (7480.0, 7400.0),
        "DJ30": (40050.0, 40123.0),
    }
    out = _build_indices(specs, quotes)
    assert [ix.name for ix in out] == ["S&P 500", "Dow 30", "NASDAQ"]


def test_build_indices_skips_symbols_yahoo_lacks() -> None:
    """An index Yahoo has no quote for is omitted — never rendered with a zero.
    This is the regression: S&P/Dow must not vanish just because they're absent
    from the census, but a genuinely unresolvable symbol still drops cleanly."""
    specs = [("S&P 500", "SPX500"), ("Greek ETF", "LYXGRE.DE")]
    quotes = {"SPX500": (7480.0, 7400.0)}  # LYXGRE.DE delisted on Yahoo
    out = _build_indices(specs, quotes)
    assert [ix.name for ix in out] == ["S&P 500"]


def test_build_indices_case_insensitive_symbol_lookup() -> None:
    """Config symbols resolve against the (upper-cased) quote keys regardless of case."""
    specs = [("S&P 500", "spx500")]
    out = _build_indices(specs, {"SPX500": (7480.0, 7400.0)})
    assert len(out) == 1
    assert out[0].name == "S&P 500"


def test_build_indices_zero_prev_is_zero_pct_not_crash() -> None:
    """prev <= 0 (single-bar fallback edge) → 0% change, no divide-by-zero."""
    specs = [("S&P 500", "SPX500")]
    out = _build_indices(specs, {"SPX500": (7480.0, 0.0)})
    assert out[0].change_pct == 0.0


def test_build_indices_empty() -> None:
    assert _build_indices([], {}) == ()


# ---------------------------------------------------------------------------
# _to_position with census-missing instruments
# ---------------------------------------------------------------------------


def test_to_position_census_missing_with_live_rates() -> None:
    """Instrument not in census but live rates available → rendered with placeholder symbol."""
    raw = _raw(inst_id=14710)
    rates = {14710: {"lastExecution": 2850.0, "conversionRateAsk": 0.0065}}
    p = _to_position(raw, {}, {}, {}, rates)
    assert p is not None
    assert p.symbol == "#14710"
    assert p.current_rate == pytest.approx(2850.0 * 0.0065)
    assert p.prev_close is None


def test_to_position_census_missing_with_config_override() -> None:
    """Instrument not in census but user mapped via [instruments.map] → gets real symbol."""
    raw = _raw(inst_id=14710)
    rates = {14710: {"lastExecution": 2850.0, "conversionRateAsk": 0.0065}}
    yahoo_prev = {"9201.T": 2800.0}
    overrides = {14710: "9201.T"}
    p = _to_position(raw, {}, {}, {}, rates, yahoo_prev, overrides)
    assert p is not None
    assert p.symbol == "9201.T"
    assert p.prev_close == pytest.approx(2800.0 * 0.0065)


def test_to_position_census_missing_no_rates_uses_open() -> None:
    """No census AND no live rates → uses open_rate as fallback."""
    raw = _raw(inst_id=14710, open_rate=2900.0)
    p = _to_position(raw, {}, {}, {}, None)
    assert p is not None
    assert p.symbol == "#14710"
    assert p.current_rate == pytest.approx(2900.0)
    assert p.pnl == 0.0
