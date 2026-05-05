"""Main DataTable: positions with overlay columns, sortable + filterable."""
from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, Input

from ..models import Position


SortKey = Literal["value", "pnl", "pnl_pct", "symbol", "signal"]
_SORT_CYCLE: list[SortKey] = ["value", "pnl", "pnl_pct", "symbol", "signal"]
SORT_LABELS: dict[SortKey, str] = {
    "value": "Value ↓",
    "pnl": "P&L ↓",
    "pnl_pct": "Δ% ↓",
    "symbol": "Symbol",
    "signal": "Signal",
}

_SIG_STYLE = {
    "BUY": ("green", "BUY"),
    "SELL": ("red", "SELL"),
    "HOLD": ("dim", "HOLD"),
}

# (label, justify) pairs — justify drives DataTable rendering of the value cells
_COLS: tuple[tuple[str, str], ...] = (
    ("Symbol", "left"),
    ("Lots",   "right"),
    ("Units",  "right"),
    ("Avg Open", "right"),
    ("Now",    "right"),
    ("Δ%",     "right"),
    ("Value $", "right"),
    ("P&L $",  "right"),
    ("Sig",    "center"),
    ("PI%",    "right"),
    ("News",   "right"),
)


def _fmt_units(u: float) -> Text:
    """No scientific notation. Compact for big numbers."""
    if u >= 10_000:
        s = f"{u:,.0f}"
    elif u >= 100:
        s = f"{u:,.1f}"
    elif u >= 1:
        s = f"{u:,.4f}".rstrip("0").rstrip(".")
    else:
        s = f"{u:,.6f}".rstrip("0").rstrip(".")
    return Text(s, justify="right")


def _fmt_money(v: float) -> Text:
    return Text(f"{v:,.2f}", justify="right")


def _fmt_signal(s: str | None) -> Text:
    if s is None:
        return Text("—", style="dim", justify="center")
    style, label = _SIG_STYLE.get(s, ("", str(s)))
    return Text(label, style=style, justify="center")


def _fmt_pi(p: float | None) -> Text:
    if p is None:
        return Text("—", style="dim", justify="right")
    if p < 0.5:
        return Text("<1%", style="dim", justify="right")
    return Text(f"{p:.0f}%", justify="right")


def _fmt_news(n: int | None, anomaly: bool) -> Text:
    if n is None:
        return Text("—", style="dim", justify="right")
    if n == 0:
        return Text("0", style="dim", justify="right")
    label = f"▴{n}" if anomaly else f"{n}"
    style = "yellow" if anomaly else ""
    return Text(label, style=style, justify="right")


def _delta_pct(pct: float) -> Text:
    color = "green" if pct >= 0 else "red"
    sign = "+" if pct >= 0 else ""
    return Text(f"{sign}{pct:.2f}", style=color, justify="right")


def _pnl(pnl: float) -> Text:
    color = "green" if pnl >= 0 else "red"
    sign = "+" if pnl >= 0 else "−"
    return Text(f"{sign}{abs(pnl):,.2f}", style=color, justify="right")


def _lots(n: int) -> Text:
    style = "dim" if n == 1 else ""
    return Text(str(n), style=style, justify="right")


class PositionsTable(Vertical):
    """Container for the table + filter input."""

    positions: reactive[tuple[Position, ...]] = reactive(())
    sort_key: reactive[SortKey] = reactive("value")
    filter_text: reactive[str] = reactive("")

    class PositionSelected(Message):
        def __init__(self, position: Position | None) -> None:
            self.position = position
            super().__init__()

    class SortChanged(Message):
        """Posted whenever the active sort key changes — Footer listens."""
        def __init__(self, key: SortKey) -> None:
            self.key = key
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter symbol…", id="filter", classes="hidden")
        yield DataTable(id="positions-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for label, _justify in _COLS:
            table.add_column(label, key=label)
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
            # BUY first, then SELL, then HOLD, then None — most actionable on top
            order = {"BUY": 0, "SELL": 1, "HOLD": 2, None: 3}
            rows.sort(key=lambda p: (order.get(p.signal, 4), p.symbol))
        else:
            rows.sort(key=lambda p: getattr(p, key), reverse=True)
        return rows

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for p in self._sorted_filtered_positions():
            table.add_row(
                Text(p.symbol, style="bold"),
                _lots(p.position_count),
                _fmt_units(p.units),
                _fmt_money(p.open_rate),
                _fmt_money(p.current_rate),
                _delta_pct(p.pnl_pct),
                _fmt_money(p.value),
                _pnl(p.pnl),
                _fmt_signal(p.signal),
                _fmt_pi(p.pi_pct),
                _fmt_news(p.news_24h, p.news_anomaly),
                key=str(p.position_id),
            )
