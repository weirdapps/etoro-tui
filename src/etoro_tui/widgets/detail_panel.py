# src/etoro_tui/widgets/detail_panel.py
"""Right-side panel: deep-dive on selected position."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Sparkline, Static

from ..models import Position


class DetailPanel(Vertical):
    """Shown when a position is selected and width ≥ 100."""

    position: reactive[Position | None] = reactive(None)
    intraday: reactive[tuple[float, ...]] = reactive(())
    seven_day: reactive[tuple[float, ...]] = reactive(())

    def compose(self) -> ComposeResult:
        yield Static("Select a position", id="dp-title")
        yield Static("", id="dp-position")
        yield Static("", id="dp-now")
        yield Static("", id="dp-overlay")
        yield Static("Today", id="dp-today-label")
        yield Sparkline([], id="dp-today")
        yield Static("7-day", id="dp-week-label")
        yield Sparkline([], id="dp-week")

    def watch_position(self, p: Position | None) -> None:
        title = self.query_one("#dp-title", Static)
        if p is None:
            title.update("Select a position")
            for sel in ("#dp-position", "#dp-now", "#dp-overlay"):
                self.query_one(sel, Static).update("")
            self.query_one("#dp-today", Sparkline).data = []
            self.query_one("#dp-week", Sparkline).data = []
            return
        title.update(f"{p.symbol}")
        self.query_one("#dp-position", Static).update(
            f"#{p.position_id} · {p.direction} · {p.units:g} units @ {p.open_rate:,.2f}"
        )
        sign = "+" if p.pnl >= 0 else "−"
        color = "green" if p.pnl >= 0 else "red"
        self.query_one("#dp-now", Static).update(
            f"Now [{color}]{p.current_rate:,.2f}[/{color}]   "
            f"Δopen [{color}]{sign}{abs(p.pnl_pct):.2f}%[/{color}] "
            f"([{color}]{sign}€{abs(p.pnl):,.2f}[/{color}])   "
            f"Value €{p.value:,.2f}"
        )
        sig = "—" if p.signal is None else p.signal
        pi = "—" if p.pi_pct is None else f"{p.pi_pct:.0f}%"
        news = "—" if p.news_24h is None else f"{p.news_24h}{' ▴' if p.news_anomaly else ''}"
        self.query_one("#dp-overlay", Static).update(
            f"Signal {sig}   Census {pi} of PIs hold   News (24h) {news}"
        )

    def watch_intraday(self, vals: tuple[float, ...]) -> None:
        self.query_one("#dp-today", Sparkline).data = list(vals)

    def watch_seven_day(self, vals: tuple[float, ...]) -> None:
        self.query_one("#dp-week", Sparkline).data = list(vals)
