"""Unit tests for app.py pure business logic.

Covers:
  - _overlay_fields: single source of truth for the overlay-kwargs dict
  - _to_position price fallback: live → bid → census, never crashes on None
  - _day_change_pct formatter: percent display, sign, missing-prev fallback
"""

import pytest

from etoro_tui.app import _overlay_fields, _to_position
from etoro_tui.clients.census import InstrumentInfo
from etoro_tui.clients.signals import Fundamentals
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
        target_price=210.0,
    )
    out = _overlay_fields("AAPL", fund, {"AAPL": 22.0})
    assert out["signal"] == "BUY"
    assert out["pi_pct"] == 22.0
    assert out["pe_trailing"] == 33.5
    assert out["pe_forward"] == 29.0
    assert out["upside_pct"] == 8.6
    assert out["analyst_buy_pct"] == 53.0
    assert out["target_price"] == 210.0


def test_overlay_fields_no_fundamentals() -> None:
    out = _overlay_fields("UNKNOWN", None, {})
    assert out["signal"] is None
    assert out["pi_pct"] is None
    assert out["pe_trailing"] is None
    assert out["pe_forward"] is None
    assert out["upside_pct"] is None
    assert out["analyst_buy_pct"] is None
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
