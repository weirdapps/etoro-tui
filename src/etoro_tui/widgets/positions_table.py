"""Main DataTable: positions with overlay columns, sortable + filterable."""
from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, Input

from ..models import Position


SortKey = Literal["pnl_pct", "pnl", "value", "symbol", "signal"]
_SORT_CYCLE: list[SortKey] = ["pnl_pct", "pnl", "value", "symbol", "signal"]

_SIG_STYLE = {
    "BUY": "[green]BUY[/green]",
    "SELL": "[red]SELL[/red]",
    "HOLD": "[dim]HOLD[/dim]",
}

_COLS = (
    "Symbol", "Units", "Open", "Now", "Δ%", "Value", "P&L €",
    "Sig", "PI%", "News",
)


def _fmt_signal(s: str | None) -> str:
    if s is None:
        return "[dim]—[/dim]"
    return _SIG_STYLE.get(s, str(s))


def _fmt_pi(p: float | None) -> str:
    return f"{p:.0f}%" if p is not None else "[dim]—[/dim]"


def _fmt_news(n: int | None, anomaly: bool) -> str:
    if n is None:
        return "[dim]—[/dim]"
    prefix = "▴" if anomaly else " "
    return f"{prefix}{n}"


def _delta_pct_styled(pct: float) -> str:
    if pct >= 0:
        return f"[green]+{pct:.2f}[/green]"
    return f"[red]{pct:.2f}[/red]"


def _pnl_styled(pnl: float) -> str:
    sign = "+" if pnl >= 0 else "−"
    color = "green" if pnl >= 0 else "red"
    return f"[{color}]{sign}{abs(pnl):,.2f}[/{color}]"


class PositionsTable(Vertical):
    """Container for the table + filter input."""

    positions: reactive[tuple[Position, ...]] = reactive(())
    sort_key: reactive[SortKey] = reactive("pnl_pct")
    filter_text: reactive[str] = reactive("")

    class PositionSelected(Message):
        def __init__(self, position: Position | None) -> None:
            self.position = position
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter symbol…", id="filter", classes="hidden")
        yield DataTable(id="positions-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for c in _COLS:
            table.add_column(c, key=c)
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

    def watch_sort_key(self, _: SortKey) -> None:
        self._refresh_table()

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
            rows.sort(key=lambda p: (p.signal or "ZZZ"))
        else:
            rows.sort(key=lambda p: getattr(p, key), reverse=True)
        return rows

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for p in self._sorted_filtered_positions():
            table.add_row(
                p.symbol,
                f"{p.units:g}",
                f"{p.open_rate:,.2f}",
                f"{p.current_rate:,.2f}",
                _delta_pct_styled(p.pnl_pct),
                f"{p.value:,.2f}",
                _pnl_styled(p.pnl),
                _fmt_signal(p.signal),
                _fmt_pi(p.pi_pct),
                _fmt_news(p.news_24h, p.news_anomaly),
                key=str(p.position_id),
            )
