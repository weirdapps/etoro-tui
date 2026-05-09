"""Single-row Bloomberg-style header — no vertical dividers.

  $100,000.00 ▲+0.26%   Cash $20K   P&L +$5K   ▁▂▃▅▆▇   S&P 5,432 ▲+0.34%   NDX 17,234 ▲+0.45%   DOW 40,123 ▼-0.21%        14:23 EEST  ●

Two-section layout: portfolio data + indices on the LEFT (packs flush left),
clock + status dot anchored to the RIGHT edge. Sections separated by
generous whitespace instead of │ characters — cleaner for scanning.
Indices are FX-converted to USD upstream so they match what the table shows.
"""
from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static

from ..models import AccountSummary, IndexSummary, Status


# Two-space gap separates sections — replaces the prior │ dividers for a
# cleaner, less-busy look.
_GAP = Text("   ", style="")


def _index_text(ix: IndexSummary, max_name: int = 4) -> Text:
    """Render one index inline: '<short_name> <price> ▲±X.XX%'."""
    # Squash long names ("S&P 500" → "S&P", "NASDAQ" → "NDX", "Dow 30" → "DOW",
    # "EuroStx50" → "STX", "Greek ETF" → "GRE"). Fits more indices in the bar.
    short = {
        "S&P 500": "S&P", "NASDAQ": "NDX", "Dow 30": "DOW",
        "EuroStx50": "STX", "Greek ETF": "GRE",
    }.get(ix.name, ix.name[:max_name])
    arrow = "▲" if ix.change_pct >= 0 else "▼"
    sign = "+" if ix.change_pct >= 0 else ""
    color = "green" if ix.change_pct >= 0 else "red"
    return Text.assemble(
        (f"{short} ", "dim"),
        (f"{ix.last:,.0f} ", ""),
        (f"{arrow}{sign}{ix.change_pct:.2f}%", color),
    )


def _equity(v: float) -> Text:
    return Text(f"${v:,.2f}", style="bold cyan")


def _delta_compact(pct: float) -> Text:
    """Compact today-Δ — arrow + percent only, no $ amount, no 'today' label."""
    arrow = "▲" if pct >= 0 else "▼"
    sign = "+" if pct >= 0 else ""
    color = "bold green" if pct >= 0 else "bold red"
    return Text(f"{arrow}{sign}{pct:.2f}%", style=color)


def _cash(v: float) -> Text:
    return Text.assemble(("Cash ", "dim"), (f"${v/1000:,.0f}K", ""))


def _open_pnl(v: float) -> Text:
    color = "bold green" if v >= 0 else "bold red"
    sign = "+" if v >= 0 else "−"
    return Text.assemble(
        ("P&L ", "dim"),
        (f"{sign}${abs(v)/1000:,.0f}K", color),
    )


# Status: just the dot, colour-coded. Hover/help reveals the meaning.
_STATUS_DOT: dict[Status, Text] = {
    "live":     Text("●", style="bold green"),
    "degraded": Text("●", style="bold yellow"),
    "down":     Text("●", style="bold red"),
}


_SPARK_BARS = "▁▂▃▄▅▆▇█"


def _mini_sparkline(values: tuple[float, ...], width: int = 8) -> Text:
    """Compact Unicode sparkline — width chars wide, one block per bucket."""
    if not values or len(values) < 2:
        return Text("·" * width, style="dim")
    # Downsample to `width` buckets
    step = max(1, len(values) // width)
    sampled = [values[i] for i in range(0, len(values), step)][:width]
    while len(sampled) < width:
        sampled.append(sampled[-1])
    lo, hi = min(sampled), max(sampled)
    span = hi - lo if hi > lo else 1.0
    bars = "".join(
        _SPARK_BARS[min(len(_SPARK_BARS) - 1, int((v - lo) / span * (len(_SPARK_BARS) - 1)))]
        for v in sampled
    )
    color = "green" if values[-1] >= values[0] else "red"
    return Text(bars, style=color)


class Header(Horizontal):
    """Single-row Bloomberg-style header. One Static, assembled with │ separators."""

    account: reactive[AccountSummary | None] = reactive(None)
    status: reactive[Status] = reactive("live")
    sparkline_values: reactive[tuple[float, ...]] = reactive(())
    open_pnl: reactive[float] = reactive(0.0)
    today_delta: reactive[tuple[float, float]] = reactive((0.0, 0.0))
    today_baseline_known: reactive[bool] = reactive(False)
    indices: reactive[tuple[IndexSummary, ...]] = reactive(())

    def compose(self) -> ComposeResult:
        yield Static("", id="hdr-left")
        yield Static("", id="hdr-right")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._render)
        self._repaint()

    def watch_account(self, _: AccountSummary | None) -> None:
        self._repaint()

    def watch_today_delta(self, _: tuple[float, float]) -> None:
        self._repaint()

    def watch_today_baseline_known(self, _: bool) -> None:
        self._repaint()

    def watch_open_pnl(self, _: float) -> None:
        self._repaint()

    def watch_sparkline_values(self, _: tuple[float, ...]) -> None:
        self._repaint()

    def watch_status(self, _: Status) -> None:
        self._repaint()

    def watch_indices(self, _: tuple[IndexSummary, ...]) -> None:
        self._repaint()

    def _repaint(self) -> None:
        if not self.is_mounted:
            return
        a = self.account
        # ---- LEFT: portfolio data + up to 3 indices ----
        equity = _equity(a.equity) if a else Text("$ —", style="dim")
        if self.today_baseline_known:
            _, pct = self.today_delta
            delta = _delta_compact(pct)
        else:
            delta = Text("collecting…", style="dim")
        cash = _cash(a.cash) if a else Text("Cash —", style="dim")
        pnl = _open_pnl(self.open_pnl)
        spark = _mini_sparkline(self.sparkline_values, width=8)

        parts: list[Text] = [
            equity, Text(" "), delta,
            _GAP, cash,
            _GAP, pnl,
            _GAP, spark,
        ]
        # Up to 3 indices in the header — keeps the bar from overflowing on
        # narrower terminals (cap is conservative; a 5th would push clock off
        # the right edge).
        for ix in self.indices[:3]:
            parts.append(_GAP)
            parts.append(_index_text(ix))
        self.query_one("#hdr-left", Static).update(Text.assemble(*parts))

        # ---- RIGHT: clock + status dot (separated by a single space) ----
        clock = Text(datetime.now().astimezone().strftime("%H:%M %Z"), style="dim")
        dot = _STATUS_DOT[self.status]
        right = Text.assemble(clock, Text("  "), dot)
        self.query_one("#hdr-right", Static).update(right)
