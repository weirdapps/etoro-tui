"""Main DataTable: aggregated-by-ticker positions, sortable + filterable.

Column labels are deliberately precise so nothing is mistaken for live data:

  Symbol  — eToro instrument symbol (live; positions added/removed as you trade)
  Open    — weighted-avg cost per unit, USD (static, set when each lot opened)
  Close   — last close from census priceData (DAILY ~03:00 UTC, NOT live)
  Δ%      — total % change Close vs Open, NOT today's change
  Value   — units × Close, in USD (DAILY)
  % Eq    — Value / total equity (DAILY)
  P&L $   — (Close − Open) × units × dir, total since open, NOT today (DAILY)
  PE-T    — trailing 12m P/E from etorotrade (DAILY ~22:00 UTC)
  PE-F    — forward 12m P/E (DAILY)
  Up%     — analyst-target implied upside (DAILY)
  Buy%    — % of analyst recs = BUY (DAILY)
  PI%     — % of eToro popular investors holding (DAILY)
  Sig     — etorotrade BUY / SELL / HOLD (DAILY)

Lots and per-position Units live in the detail panel — for daily glance the
aggregated $ matters more than how many lots accumulated it.

There is no "today's Δ" column — eToro's free retail endpoint does not return
intraday or session-open prices, so we cannot honestly compute one. Header
shows session-vs-snapshot equity Δ instead.
"""
from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, Input

from ..models import Position


SortKey = Literal["value", "pnl", "pnl_pct", "upside_pct", "analyst_buy_pct",
                  "pe_forward", "symbol", "signal"]
_SORT_CYCLE: list[SortKey] = [
    "value", "pnl", "pnl_pct", "upside_pct", "analyst_buy_pct",
    "pe_forward", "signal", "symbol",
]
SORT_LABELS: dict[SortKey, str] = {
    "value": "Value ↓",
    "pnl": "P&L ↓",
    "pnl_pct": "Δ% ↓",
    "upside_pct": "Upside ↓",
    "analyst_buy_pct": "Buy% ↓",
    "pe_forward": "PE-F ↑",   # cheaper first
    "signal": "Signal",
    "symbol": "Symbol",
}

_SIG_STYLE = {
    "BUY": ("green", "BUY"),
    "SELL": ("red", "SELL"),
    "HOLD": ("dim", "HOLD"),
}

# (label, width). Width = None lets DataTable auto-size; explicit widths give
# justify="right" Text actual room to right-align inside the cell.
# Total ≈ 110 chars (excluding Symbol auto-size). Fits a 130+ col terminal
# alongside a 48-col detail panel.
_COLS: tuple[tuple[str, int | None], ...] = (
    ("Symbol",   None),
    ("Open",        9),
    ("Close",       9),
    ("Δ%",          7),
    ("Value $",    12),
    ("% Eq",        6),
    ("P&L $",      12),
    ("PE-T",        6),
    ("PE-F",        6),
    ("Up%",         7),
    ("Buy%",        6),
    ("PI%",         5),
    ("Sig",         5),
)


def _money(v: float) -> Text:
    return Text(f"{v:,.2f}", justify="right")


def _signal(s: str | None) -> Text:
    if s is None:
        return Text("—", style="dim", justify="center")
    style, label = _SIG_STYLE.get(s, ("", str(s)))
    return Text(label, style=style, justify="center")


def _pi(p: float | None) -> Text:
    if p is None:
        return Text("—", style="dim", justify="right")
    if p < 0.5:
        return Text("<1%", style="dim", justify="right")
    return Text(f"{p:.0f}%", justify="right")


def _delta_pct(pct: float) -> Text:
    color = "green" if pct >= 0 else "red"
    sign = "+" if pct >= 0 else ""
    return Text(f"{sign}{pct:.2f}", style=color, justify="right")


def _pnl(pnl: float) -> Text:
    color = "green" if pnl >= 0 else "red"
    sign = "+" if pnl >= 0 else "−"
    return Text(f"{sign}{abs(pnl):,.2f}", style=color, justify="right")


def _eq_pct(pct: float) -> Text:
    if pct >= 10:
        style = "bold"
    elif pct < 2:
        style = "dim"
    else:
        style = ""
    return Text(f"{pct:.1f}%", style=style, justify="right")


def _pe(v: float | None) -> Text:
    """P/E ratio: dim if >40 (expensive) or <0 (loss-making) or missing."""
    if v is None:
        return Text("—", style="dim", justify="right")
    if v <= 0 or v > 100:
        # Loss-making (negative) or extreme — show but dim.
        return Text(f"{v:.1f}", style="dim", justify="right")
    return Text(f"{v:.1f}", justify="right")


def _upside(v: float | None) -> Text:
    """Analyst upside %. Green if >=10, red if <=-10, dim if missing."""
    if v is None:
        return Text("—", style="dim", justify="right")
    if v >= 10:
        color = "green"
    elif v <= -10:
        color = "red"
    else:
        color = ""
    sign = "+" if v >= 0 else ""
    return Text(f"{sign}{v:.1f}", style=color, justify="right")


def _buy_pct(v: float | None) -> Text:
    """Analyst buy %. Green ≥75, red ≤25, dim if missing."""
    if v is None:
        return Text("—", style="dim", justify="right")
    if v >= 75:
        color = "green"
    elif v <= 25:
        color = "red"
    else:
        color = ""
    return Text(f"{v:.0f}%", style=color, justify="right")


class PositionsTable(Vertical):
    positions: reactive[tuple[Position, ...]] = reactive(())
    equity: reactive[float] = reactive(0.0)
    sort_key: reactive[SortKey] = reactive("value")
    filter_text: reactive[str] = reactive("")

    class PositionSelected(Message):
        def __init__(self, position: Position | None) -> None:
            self.position = position
            super().__init__()

    class SortChanged(Message):
        def __init__(self, key: SortKey) -> None:
            self.key = key
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter symbol…", id="filter", classes="hidden")
        yield DataTable(id="positions-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for label, width in _COLS:
            table.add_column(label, key=label, width=width)
        table.focus()

    def cycle_sort(self) -> None:
        idx = _SORT_CYCLE.index(self.sort_key)
        self.sort_key = _SORT_CYCLE[(idx + 1) % len(_SORT_CYCLE)]

    def show_filter(self) -> None:
        f = self.query_one("#filter", Input)
        f.remove_class("hidden")
        f.focus()

    def hide_filter(self) -> None:
        f = self.query_one("#filter", Input)
        f.add_class("hidden")
        f.value = ""
        self.filter_text = ""
        self.query_one(DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.query_one(DataTable).focus()

    def watch_positions(self, _: tuple[Position, ...]) -> None:
        self._refresh_table()

    def watch_equity(self, _: float) -> None:
        self._refresh_table()

    def watch_sort_key(self, key: SortKey) -> None:
        self._refresh_table()
        self.post_message(self.SortChanged(key))

    def watch_filter_text(self, _: str) -> None:
        self._refresh_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        idx = event.cursor_row
        rows = self._sorted_filtered_positions()
        if 0 <= idx < len(rows):
            self.post_message(self.PositionSelected(rows[idx]))
        else:
            self.post_message(self.PositionSelected(None))

    def _sorted_filtered_positions(self) -> list[Position]:
        rows = list(self.positions)
        f = self.filter_text.upper()
        if f:
            rows = [p for p in rows if f in p.symbol.upper()]
        key = self.sort_key
        if key == "symbol":
            rows.sort(key=lambda p: p.symbol)
        elif key == "signal":
            order = {"BUY": 0, "SELL": 1, "HOLD": 2, None: 3}
            rows.sort(key=lambda p: (order.get(p.signal, 4), p.symbol))
        elif key == "pe_forward":
            # Cheap first. Treat None as huge so missing data sinks to bottom.
            rows.sort(key=lambda p: p.pe_forward
                      if p.pe_forward is not None and p.pe_forward > 0 else float("inf"))
        elif key in ("upside_pct", "analyst_buy_pct"):
            # None → bottom. Higher first.
            rows.sort(key=lambda p: getattr(p, key)
                      if getattr(p, key) is not None else float("-inf"),
                      reverse=True)
        else:
            rows.sort(key=lambda p: getattr(p, key), reverse=True)
        return rows

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        eq = self.equity if self.equity > 0 else 0
        for p in self._sorted_filtered_positions():
            pct_eq = (p.value / eq * 100) if eq > 0 else 0.0
            table.add_row(
                Text(p.symbol, style="bold"),
                _money(p.open_rate),
                _money(p.current_rate),
                _delta_pct(p.pnl_pct),
                _money(p.value),
                _eq_pct(pct_eq),
                _pnl(p.pnl),
                _pe(p.pe_trailing),
                _pe(p.pe_forward),
                _upside(p.upside_pct),
                _buy_pct(p.analyst_buy_pct),
                _pi(p.pi_pct),
                _signal(p.signal),
                key=str(p.position_id),
            )
