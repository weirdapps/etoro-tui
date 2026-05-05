"""Single-row header — packed for vertical density.

  $100,000.00   ▲ +$500 (+0.26%) today  ▁▂▃▅▆▇   Cash $20K  Open P&L +$5K   14:23 EET  ●live

Equity is bold-cyan and visually leads. Everything else is dim labels with
moderate-weight values. One row only — every saved row is one more ticker
visible in the table below.
"""
from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Sparkline, Static

from ..models import AccountSummary, Status


def _equity(v: float) -> Text:
    return Text(f"${v:,.2f}", style="bold cyan")


def _delta(v: float, pct: float) -> Text:
    arrow = "▲" if v >= 0 else "▼"
    sign = "+" if v >= 0 else "−"
    color = "green" if v >= 0 else "red"
    return Text.assemble(
        (f"{arrow} ", color),
        (f"{sign}${abs(v):,.0f}", color),
        (f" ({sign}{abs(pct):.2f}%)", color),
        (" today", "dim"),
    )


def _cash(v: float) -> Text:
    return Text.assemble(("Cash ", "dim"), (f"${v:,.0f}", ""))


def _open_pnl(v: float) -> Text:
    color = "green" if v >= 0 else "red"
    sign = "+" if v >= 0 else "−"
    return Text.assemble(
        ("P&L ", "dim"),
        (f"{sign}${abs(v):,.0f}", color),
    )


_STATUS_DOT: dict[Status, Text] = {
    "live":     Text.assemble(("●", "green"),  (" live", "dim")),
    "degraded": Text.assemble(("●", "yellow"), (" slow", "dim")),
    "down":     Text.assemble(("●", "red"),    (" down", "dim")),
}


class Header(Horizontal):
    """Single-row header. Equity is the headline; the rest is context."""

    account: reactive[AccountSummary | None] = reactive(None)
    status: reactive[Status] = reactive("live")
    sparkline_values: reactive[tuple[float, ...]] = reactive(())
    open_pnl: reactive[float] = reactive(0.0)
    today_delta: reactive[tuple[float, float]] = reactive((0.0, 0.0))
    today_baseline_known: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static("", id="hdr-equity")
        yield Static("", id="hdr-delta")
        yield Sparkline([], id="hdr-spark", summary_function=max)
        yield Static("", id="hdr-fill")  # absorbs leftover horizontal space
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
            Text(now.strftime("%H:%M %Z"), style="dim")
        )

    def watch_account(self, a: AccountSummary | None) -> None:
        if a is None:
            self.query_one("#hdr-equity", Static).update(Text("$ —", style="dim"))
            self.query_one("#hdr-cash", Static).update(Text("Cash —", style="dim"))
            return
        self.query_one("#hdr-equity", Static).update(_equity(a.equity))
        self.query_one("#hdr-cash", Static).update(_cash(a.cash))

    def watch_today_delta(self, value: tuple[float, float]) -> None:
        self._render_delta()

    def watch_today_baseline_known(self, _: bool) -> None:
        self._render_delta()

    def _render_delta(self) -> None:
        widget = self.query_one("#hdr-delta", Static)
        if not self.today_baseline_known:
            widget.update(Text("today collecting…", style="dim"))
            return
        delta, pct = self.today_delta
        widget.update(_delta(delta, pct))

    def watch_open_pnl(self, v: float) -> None:
        self.query_one("#hdr-pnl", Static).update(_open_pnl(v))

    def watch_sparkline_values(self, values: tuple[float, ...]) -> None:
        self.query_one("#hdr-spark", Sparkline).data = list(values)

    def watch_status(self, _: Status) -> None:
        self._render_status()

    def _render_status(self) -> None:
        self.query_one("#hdr-status", Static).update(_STATUS_DOT[self.status])
