"""Header: equity, today's Δ, sparkline, cash, status dot, clock."""
from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Sparkline, Static

from ..models import AccountSummary, Status


def _fmt_usd(v: float) -> str:
    """Compact USD formatting with thousands separators."""
    return f"${v:,.2f}"


def _delta_text(v: float, pct: float) -> Text:
    """Today's delta with arrow + colour, returned as styled Text."""
    arrow = "▲" if v >= 0 else "▼"
    sign = "+" if v >= 0 else "−"
    color = "green" if v >= 0 else "red"
    return Text.assemble(
        ("Today  ", "dim"),
        (f"{arrow} {sign}${abs(v):,.2f}", color),
        ("  ", ""),
        (f"({sign}{abs(pct):.2f}%)", color),
    )


def _equity_text(v: float) -> Text:
    return Text.assemble(("Equity  ", "dim"), (_fmt_usd(v), "bold cyan"))


def _cash_text(v: float) -> Text:
    return Text.assemble(("Cash  ", "dim"), (_fmt_usd(v), ""))


def _open_pnl_text(v: float) -> Text:
    color = "green" if v >= 0 else "red"
    sign = "+" if v >= 0 else "−"
    return Text.assemble(("Open P&L  ", "dim"), (f"{sign}${abs(v):,.2f}", color))


_STATUS_DOT: dict[Status, Text] = {
    "live":     Text.assemble(("●", "green"),  (" live", "dim")),
    "degraded": Text.assemble(("●", "yellow"), (" slow", "dim")),
    "down":     Text.assemble(("●", "red"),    (" down", "dim")),
}


class Header(Horizontal):
    """One-row header: equity, today's Δ, sparkline, cash, P&L, clock, status."""

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
        self.query_one("#hdr-clock", Static).update(
            Text(now.strftime("%H:%M:%S %Z"), style="dim")
        )

    def watch_account(self, a: AccountSummary | None) -> None:
        if a is None:
            self.query_one("#hdr-equity", Static).update(
                Text.assemble(("Equity  ", "dim"), ("—", "dim"))
            )
            self.query_one("#hdr-cash", Static).update(
                Text.assemble(("Cash  ", "dim"), ("—", "dim"))
            )
            return
        self.query_one("#hdr-equity", Static).update(_equity_text(a.equity))
        self.query_one("#hdr-cash", Static).update(_cash_text(a.cash))

    def watch_today_delta(self, value: tuple[float, float]) -> None:
        delta, pct = value
        self.query_one("#hdr-delta", Static).update(_delta_text(delta, pct))

    def watch_open_pnl(self, v: float) -> None:
        self.query_one("#hdr-pnl", Static).update(_open_pnl_text(v))

    def watch_sparkline_values(self, values: tuple[float, ...]) -> None:
        self.query_one("#hdr-spark", Sparkline).data = list(values)

    def watch_status(self, _: Status) -> None:
        self._render_status()

    def _render_status(self) -> None:
        self.query_one("#hdr-status", Static).update(_STATUS_DOT[self.status])
