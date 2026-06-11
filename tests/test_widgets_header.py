"""Tests for the header bar's responsive index packing.

The header shows market indices flush-left alongside the portfolio summary, with
the clock anchored right. `_fit_indices` decides how many indices fit a given
width: it always keeps the first few (so S&P/Dow never vanish on a narrow
terminal) and adds the rest only while they fit.
"""

from __future__ import annotations

from etoro_tui.models import IndexSummary
from etoro_tui.widgets.header import _GAP, _fit_indices, _index_text


def _ix(name: str, last: float = 1000.0, pct: float = 0.5) -> IndexSummary:
    return IndexSummary(name=name, last=last, change_pct=pct)


def _cells(ix: IndexSummary) -> int:
    """Rendered width of one index, including its leading gap."""
    return _GAP.cell_len + _index_text(ix).cell_len


_FIVE = (_ix("S&P 500"), _ix("Dow 30"), _ix("NASDAQ"), _ix("DAX"), _ix("FTSE 100"))


def test_fit_indices_shows_all_when_budget_large() -> None:
    assert _fit_indices(_FIVE, budget=10_000) == _FIVE


def test_fit_indices_keeps_first_three_when_budget_zero() -> None:
    """Priority: never drop S&P/Dow/NASDAQ to a tight terminal, even if showing
    them means a little overflow — that's the regression we're guarding."""
    out = _fit_indices(_FIVE, budget=0)
    assert tuple(i.name for i in out) == ("S&P 500", "Dow 30", "NASDAQ")


def test_fit_indices_returns_all_when_fewer_than_minimum() -> None:
    pair = (_ix("S&P 500"), _ix("Dow 30"))
    assert _fit_indices(pair, budget=0) == pair


def test_fit_indices_adds_only_extras_that_fit() -> None:
    """Budget for exactly four → the fifth is dropped."""
    budget = sum(_cells(i) for i in _FIVE[:4])
    out = _fit_indices(_FIVE, budget=budget)
    assert tuple(i.name for i in out) == ("S&P 500", "Dow 30", "NASDAQ", "DAX")


def test_fit_indices_empty() -> None:
    assert _fit_indices((), budget=100) == ()
