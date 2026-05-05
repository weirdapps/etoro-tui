"""Header: equity, today's Δ, sparkline, cash, status dot, clock."""
from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Sparkline, Static

from ..models import AccountSummary, Status


def _fmt_eur(v: float) -> str:
    return f"€{v:,.2f}"


def _fmt_delta(v: float, pct: float) -> str:
    arrow = "▲" if v >= 0 else "▼"
    sign = "+" if v >= 0 else "−"
    return f"{arrow} {sign}€{abs(v):,.2f} ({sign}{abs(pct):.2f}%)"


_STATUS_DOT: dict[Status, str] = {
    "live": "[green]●[/green] live",
    "degraded": "[yellow]●[/yellow] degraded",
    "down": "[red]●[/red] down",
}


class Header(Horizontal):
    """Three-cell header row + sparkline."""

    account: reactive[AccountSummary | None] = reactive(None)
    status: reactive[Status] = reactive("live")
    sparkline_values: reactive[tuple[float, ...]] = reactive(())
    open_pnl: reactive[float] = reactive(0.0)
    today_delta: reactive[tuple[float, float]] = reactive((0.0, 0.0))

    def compose(self) -> ComposeResult:
        yield Static("", id="hdr-equity")
        yield Static("", id="hdr-delta")
        yield Sparkline([], id="hdr-spark", summary_function=max)
        yield Static("", id="hdr-cash")
        yield Static("", id="hdr-pnl")
        yield Static("", id="hdr-clock")
        yield Static("", id="hdr-status")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick_clock)
        self._tick_clock()
        self._render_status()

    def _tick_clock(self) -> None:
        now = datetime.now().astimezone()
        self.query_one("#hdr-clock", Static).update(now.strftime("%H:%M:%S %Z"))

    def watch_account(self, a: AccountSummary | None) -> None:
        if a is None:
            self.query_one("#hdr-equity", Static).update("Equity —")
            self.query_one("#hdr-cash", Static).update("Cash —")
            return
        self.query_one("#hdr-equity", Static).update(f"Equity {_fmt_eur(a.equity)}")
        self.query_one("#hdr-cash", Static).update(f"Cash {_fmt_eur(a.cash)}")

    def watch_today_delta(self, value: tuple[float, float]) -> None:
        delta, pct = value
        text = "Today " + _fmt_delta(delta, pct)
        self.query_one("#hdr-delta", Static).update(text)

    def watch_open_pnl(self, v: float) -> None:
        sign = "+" if v >= 0 else "−"
        self.query_one("#hdr-pnl", Static).update(f"Open P&L {sign}€{abs(v):,.2f}")

    def watch_sparkline_values(self, values: tuple[float, ...]) -> None:
        self.query_one("#hdr-spark", Sparkline).data = list(values)

    def watch_status(self, _: Status) -> None:
        self._render_status()

    def _render_status(self) -> None:
        self.query_one("#hdr-status", Static).update(_STATUS_DOT[self.status])
