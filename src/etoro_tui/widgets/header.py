"""Single-row Bloomberg-style header — no vertical dividers.

  $100,000.00 ▲+0.50%   Cash $20K   P&L +$5K   ▁▂▃▅▆▇   S&P 5,432 ▲+0.34%   NDX 17,234 ▲+0.45%   DOW 40,123 ▼-0.21%        14:23 EEST  ●

Two-section layout: portfolio data + indices on the LEFT (packs flush left),
clock + status dot anchored to the RIGHT edge. Sections separated by
generous whitespace instead of │ characters — cleaner for scanning.
Indices are priced from Yahoo in their native index points (S&P/Dow/etc.) and
auto-fit to the bar width — as many as fit, always keeping the first few.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rich.text import Text
from textual import events
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
        "S&P 500": "S&P",
        "NASDAQ": "NDX",
        "Dow 30": "DOW",
        "EuroStx50": "STX",
        "Greek ETF": "GRE",
    }.get(ix.name, ix.name[:max_name])
    arrow = "▲" if ix.change_pct >= 0 else "▼"
    sign = "+" if ix.change_pct >= 0 else ""
    color = "green" if ix.change_pct >= 0 else "red"
    # Format price by magnitude so low-priced ETFs (LYXGRE.DE ~€2.51) keep
    # their decimals instead of rounding to a useless integer.
    if ix.last >= 100:
        price = f"{ix.last:,.0f}"
    elif ix.last >= 10:
        price = f"{ix.last:.1f}"
    else:
        price = f"{ix.last:.2f}"
    return Text.assemble(
        (f"{short} ", "dim"),
        (f"{price} ", ""),
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
    return Text.assemble(("Cash ", "dim"), (f"${v / 1000:,.0f}K", ""))


def _open_pnl(v: float) -> Text:
    color = "bold green" if v >= 0 else "bold red"
    sign = "+" if v >= 0 else "−"
    return Text.assemble(
        ("P&L ", "dim"),
        (f"{sign}${abs(v) / 1000:,.0f}K", color),
    )


# Status: just the dot, colour-coded. Hover/help reveals the meaning.
_STATUS_DOT: dict[Status, Text] = {
    "live": Text("●", style="bold green"),
    "degraded": Text("●", style="bold yellow"),
    "down": Text("●", style="bold red"),
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


def _fit_indices(
    indices: Sequence[IndexSummary], budget: int, minimum: int = 3
) -> tuple[IndexSummary, ...]:
    """Greedily pack indices (each prefixed by a gap) into ``budget`` cells.

    The first ``minimum`` are always kept: losing S&P/Dow because the terminal
    is a few columns short is worse than a touch of overflow. Beyond that, an
    index is added only while its rendered width still fits the budget — so a
    wide terminal shows more indices and a narrow one shows fewer, with no
    hard-coded cap.
    """
    out = list(indices[:minimum])
    used = sum(_GAP.cell_len + _index_text(ix).cell_len for ix in out)
    for ix in indices[minimum:]:
        width = _GAP.cell_len + _index_text(ix).cell_len
        if used + width > budget:
            break
        used += width
        out.append(ix)
    return tuple(out)


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
        # ---- portfolio summary (always shown, flush left) ----
        equity = _equity(a.equity) if a else Text("$ —", style="dim")
        if self.today_baseline_known:
            _, pct = self.today_delta
            delta = _delta_compact(pct)
        else:
            delta = Text("collecting…", style="dim")
        cash = _cash(a.cash) if a else Text("Cash —", style="dim")
        pnl = _open_pnl(self.open_pnl)
        spark = _mini_sparkline(self.sparkline_values, width=8)

        base = Text.assemble(equity, Text(" "), delta, _GAP, cash, _GAP, pnl, _GAP, spark)

        # ---- RIGHT: clock + status dot (separated by a single space) ----
        clock = Text(datetime.now().astimezone().strftime("%H:%M %Z"), style="dim")
        dot = _STATUS_DOT[self.status]
        right = Text.assemble(clock, Text("  "), dot)

        # ---- indices: pack as many as fit between the summary and the clock ----
        # Budget = header width − summary − clock − paddings. Both Statics carry
        # `padding: 0 1` (2 cells each); a small extra margin keeps the left
        # section from colliding with the right-anchored clock. When the width
        # isn't known yet (pre-layout), budget ≤ 0 and _fit_indices falls back
        # to its minimum (the first 3) so S&P/Dow are never dropped.
        total = self.size.width
        budget = (total - base.cell_len - right.cell_len - 6) if total else 0
        idx_parts: list[Text] = []
        for ix in _fit_indices(self.indices, max(budget, 0)):
            idx_parts.append(_GAP)
            idx_parts.append(_index_text(ix))

        self.query_one("#hdr-left", Static).update(Text.assemble(base, *idx_parts))
        self.query_one("#hdr-right", Static).update(right)

    def on_resize(self, _: events.Resize) -> None:
        # Re-pack indices to the new width (more fit when widened, fewer when
        # shrunk).
        self._repaint()
