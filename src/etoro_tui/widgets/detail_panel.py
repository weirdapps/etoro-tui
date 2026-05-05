# src/etoro_tui/widgets/detail_panel.py
"""Right-side panel: deep-dive on selected position."""
from __future__ import annotations

from rich.text import Text
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
            title.update(Text("Select a position", style="dim"))
            for sel in ("#dp-position", "#dp-now", "#dp-overlay"):
                self.query_one(sel, Static).update("")
            self.query_one("#dp-today", Sparkline).data = []
            self.query_one("#dp-week", Sparkline).data = []
            return

        title.update(Text(p.symbol, style="bold cyan"))

        # Position line: "3 lots · Buy · 50 units @ avg $123.45" — drop "avg" when single lot
        lots_text = f"{p.position_count} lots" if p.position_count > 1 else "1 lot"
        avg_word = "avg " if p.position_count > 1 else ""
        self.query_one("#dp-position", Static).update(
            Text.assemble(
                (lots_text, "dim"),
                ("  ·  ", "dim"),
                (p.direction, "green" if p.direction == "Buy" else "red"),
                ("  ·  ", "dim"),
                (f"{p.units:,.4f}".rstrip("0").rstrip("."), ""),
                (" units @ ", "dim"),
                (f"{avg_word}${p.open_rate:,.2f}", ""),
            )
        )

        sign = "+" if p.pnl >= 0 else "−"
        color = "green" if p.pnl >= 0 else "red"
        self.query_one("#dp-now", Static).update(
            Text.assemble(
                ("Now  ", "dim"),
                (f"${p.current_rate:,.2f}", color),
                ("  ·  ", "dim"),
                (f"{sign}{abs(p.pnl_pct):.2f}%", color),
                ("  ", "dim"),
                (f"({sign}${abs(p.pnl):,.2f})", color),
                ("\n", ""),
                ("Value  ", "dim"),
                (f"${p.value:,.2f}", "bold"),
            )
        )

        sig_text = "—" if p.signal is None else p.signal
        sig_color = {"BUY": "green", "SELL": "red", "HOLD": "dim"}.get(p.signal or "", "dim")
        if p.pi_pct is None:
            pi_text, pi_color = "—", "dim"
        elif p.pi_pct < 0.5:
            pi_text, pi_color = "<1%", "dim"
        else:
            pi_text, pi_color = f"{p.pi_pct:.0f}%", ""
        if p.news_24h is None:
            news_text, news_color = "—", "dim"
        elif p.news_24h == 0:
            news_text, news_color = "0", "dim"
        else:
            news_text = f"{p.news_24h} ▴" if p.news_anomaly else str(p.news_24h)
            news_color = "yellow" if p.news_anomaly else ""
        self.query_one("#dp-overlay", Static).update(
            Text.assemble(
                ("Signal  ", "dim"),
                (sig_text, sig_color),
                ("    ", ""),
                ("Census  ", "dim"),
                (pi_text, pi_color),
                (" of PIs", "dim"),
                ("    ", ""),
                ("News 24h  ", "dim"),
                (news_text, news_color),
            )
        )

    def watch_intraday(self, vals: tuple[float, ...]) -> None:
        self.query_one("#dp-today", Sparkline).data = list(vals)

    def watch_seven_day(self, vals: tuple[float, ...]) -> None:
        self.query_one("#dp-week", Sparkline).data = list(vals)
