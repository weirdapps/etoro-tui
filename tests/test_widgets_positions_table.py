"""Tests for PositionsTable cell formatters — PIs colour grading."""

from __future__ import annotations

from etoro_tui.widgets.positions_table import _pi


def _value_style(t) -> str:
    """Colour applied to the value.

    `_cell` renders `Text("│ ", style="dim") + Text(value, style=S)`: the divider
    stays as the base `.style` and the value's colour is appended as the last span.
    """
    return str(t.spans[-1].style) if t.spans else str(t.style)


def test_pi_bands_use_distinct_hues():
    """Distinct hue per crowding band (thresholds 25/10/5) so the gradient is
    readable in a terminal — three shades of one colour were indistinguishable."""
    # ≥25% — very crowded
    assert _value_style(_pi(25.0)) == "bold green"
    assert _value_style(_pi(47.0)) == "bold green"
    # 10–25% — crowded
    assert _value_style(_pi(10.0)) == "cyan"
    assert _value_style(_pi(24.0)) == "cyan"
    # 5–10% — moderate
    assert _value_style(_pi(5.0)) == "yellow"
    assert _value_style(_pi(9.0)) == "yellow"
    # <5% — light (recedes)
    assert _value_style(_pi(1.0)) == "dim"
    assert _value_style(_pi(4.0)) == "dim"


def test_pi_negligible_stays_dim_with_lt1_label():
    t = _pi(0.3)
    assert "<1%" in t.plain
    assert "dim" in _value_style(t)


def test_pi_missing_stays_dim_dash():
    t = _pi(None)
    assert "—" in t.plain
    assert "dim" in _value_style(t)
