"""Right-side panel.

When nothing selected → portfolio overview (top holdings, currency mix,
biggest mover, concentration). This makes the panel useful at idle, not
just when a row is highlighted.

When a position is selected → per-ticker dossier (lots, P&L, overlays,
sparklines). News count lives here (not in the main table) since it's
single-ticker context, not table-scanning context.
"""
from __future__ import annotations

from collections import Counter

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Sparkline, Static

from ..models import Position


def _bar(pct: float, width: int = 12) -> str:
    """Render a Unicode horizontal bar showing percent of width."""
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _classify_currency(symbol: str) -> str:
    """Infer currency bucket from eToro ticker suffix."""
    if "." not in symbol:
        return "USD"
    suffix = symbol.rsplit(".", 1)[1]
    return {
        "L": "GBP",
        "DE": "EUR",
        "PA": "EUR",
        "MI": "EUR",
        "AS": "EUR",
        "MC": "EUR",
        "VI": "EUR",
        "BR": "EUR",
        "LS": "EUR",
        "HE": "EUR",
        "ST": "SEK",
        "OL": "NOK",
        "CO": "DKK",
        "HK": "HKD",
        "T":  "JPY",
        "TO": "CAD",
        "AX": "AUD",
        "SI": "SGD",
        "TA": "ILS",
    }.get(suffix, "OTHER")


class DetailPanel(Vertical):
    """Renders portfolio overview OR per-position dossier."""

    position: reactive[Position | None] = reactive(None)
    intraday: reactive[tuple[float, ...]] = reactive(())
    seven_day: reactive[tuple[float, ...]] = reactive(())
    all_positions: reactive[tuple[Position, ...]] = reactive(())
    equity: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        # Single Static drives both modes — content swaps based on `position`.
        yield Static("", id="dp-title")
        yield Static("", id="dp-body")
        yield Static("Today", id="dp-today-label")
        yield Sparkline([], id="dp-today")
        yield Static("7-day", id="dp-week-label")
        yield Sparkline([], id="dp-week")

    # ------- mode selection -------

    def on_mount(self) -> None:
        # Compose has run; safe to render with whatever reactive values exist.
        self._repaint()

    def watch_position(self, _: Position | None) -> None:
        if self.is_mounted:
            self._repaint()

    def watch_all_positions(self, _: tuple[Position, ...]) -> None:
        if self.is_mounted:
            self._repaint()

    def watch_equity(self, _: float) -> None:
        if self.is_mounted:
            self._repaint()

    def _repaint(self) -> None:
        # NOTE: do NOT name this `_render` — that would shadow Textual's
        # internal Widget._render() method and break rendering entirely.
        if self.position is None:
            self._render_portfolio()
        else:
            self._render_position(self.position)

    # ------- mode 1: portfolio overview (idle) -------

    def _render_portfolio(self) -> None:
        title = self.query_one("#dp-title", Static)
        body = self.query_one("#dp-body", Static)
        title.update(Text("Portfolio overview", style="bold cyan"))

        positions = list(self.all_positions)
        eq = self.equity
        if not positions or eq <= 0:
            body.update(Text("(awaiting data)", style="dim"))
            for sel in ("#dp-today", "#dp-week"):
                self.query_one(sel, Sparkline).data = []
            return

        positions.sort(key=lambda p: p.value, reverse=True)
        top5 = positions[:5]
        top5_sum = sum(p.value for p in top5)
        top5_pct = top5_sum / eq * 100

        # Currency mix (by USD-equivalent value)
        ccy_value: dict[str, float] = Counter()
        for p in positions:
            ccy_value[_classify_currency(p.symbol)] += p.value
        ccy_sorted = sorted(ccy_value.items(), key=lambda kv: kv[1], reverse=True)

        # Biggest movers today (% terms) — use P&L% as proxy
        gainer = max(positions, key=lambda p: p.pnl_pct)
        loser = min(positions, key=lambda p: p.pnl_pct)

        # Build the body Text
        parts: list = []
        parts.append(("Top 5 holdings\n", "bold"))
        for p in top5:
            pct = p.value / eq * 100
            parts.append((f"  {p.symbol:<10}", "bold"))
            parts.append((f"  {pct:>5.1f}%  ", ""))
            parts.append((_bar(pct, width=10), "cyan"))
            parts.append((f"  ${p.value:>10,.0f}\n", "dim"))
        parts.append(("\n", ""))
        parts.append((f"  Top 5 = {top5_pct:.0f}% of equity\n", "dim"))
        parts.append(("\n", ""))

        parts.append((f"All positions  ", "bold"))
        parts.append((f"{len(positions)} tickers\n", ""))
        parts.append(("\n", ""))

        parts.append(("Currency mix\n", "bold"))
        for ccy, v in ccy_sorted:
            pct = v / eq * 100
            parts.append((f"  {ccy:<6}", ""))
            parts.append((f"  {pct:>4.1f}%  ", ""))
            parts.append((_bar(pct, width=8), "cyan"))
            parts.append(("\n", ""))
        parts.append(("\n", ""))

        parts.append(("Today's movers\n", "bold"))
        parts.append((f"  ▲ {gainer.symbol:<8}", ""))
        parts.append((f"{gainer.pnl_pct:+6.2f}%\n", "green"))
        parts.append((f"  ▼ {loser.symbol:<8}", ""))
        parts.append((f"{loser.pnl_pct:+6.2f}%\n", "red"))

        body.update(Text.assemble(*parts))

        # Hide sparklines in portfolio mode
        for sel in ("#dp-today", "#dp-week"):
            self.query_one(sel, Sparkline).data = []
        for sel in ("#dp-today-label", "#dp-week-label"):
            self.query_one(sel, Static).update("")

    # ------- mode 2: per-position dossier -------

    def _render_position(self, p: Position) -> None:
        title = self.query_one("#dp-title", Static)
        body = self.query_one("#dp-body", Static)
        title.update(Text(p.symbol, style="bold cyan"))

        lots_text = f"{p.position_count} lots" if p.position_count > 1 else "1 lot"
        avg_word = "avg " if p.position_count > 1 else ""
        sign = "+" if p.pnl >= 0 else "−"
        color = "green" if p.pnl >= 0 else "red"
        eq_pct = (p.value / self.equity * 100) if self.equity > 0 else 0.0

        sig_label = "—" if p.signal is None else p.signal
        sig_color = {"BUY": "green", "SELL": "red", "HOLD": "dim"}.get(p.signal or "", "dim")
        if p.pi_pct is None:
            pi_label, pi_color = "—", "dim"
        elif p.pi_pct < 0.5:
            pi_label, pi_color = "<1%", "dim"
        else:
            pi_label, pi_color = f"{p.pi_pct:.0f}%", ""
        if p.news_24h is None:
            news_label, news_color = "—", "dim"
        elif p.news_24h == 0:
            news_label, news_color = "0", "dim"
        else:
            news_label = f"{p.news_24h} ▴" if p.news_anomaly else str(p.news_24h)
            news_color = "yellow" if p.news_anomaly else ""

        def _opt(v: float | None, fmt: str = "{:.1f}") -> tuple[str, str]:
            if v is None:
                return ("—", "dim")
            return (fmt.format(v), "")

        pet_label, pet_color = _opt(p.pe_trailing)
        pef_label, pef_color = _opt(p.pe_forward)
        ups_label = "—" if p.upside_pct is None else f"{p.upside_pct:+.1f}%"
        ups_color = "dim" if p.upside_pct is None else (
            "green" if p.upside_pct >= 10 else "red" if p.upside_pct <= -10 else "")
        buy_label = "—" if p.analyst_buy_pct is None else f"{p.analyst_buy_pct:.0f}%"
        buy_color = "dim" if p.analyst_buy_pct is None else (
            "green" if p.analyst_buy_pct >= 75 else "red" if p.analyst_buy_pct <= 25 else "")
        tgt_label = "—" if p.target_price is None else f"${p.target_price:,.2f}"
        tgt_color = "dim" if p.target_price is None else ""

        units_str = f"{p.units:,.4f}".rstrip("0").rstrip(".")
        ccy = _classify_currency(p.symbol)
        ccy_note = f"  [{ccy}]" if ccy != "USD" else ""

        body.update(Text.assemble(
            # Position structure
            (lots_text, "dim"),
            ("  ·  ", "dim"),
            (p.direction, "green" if p.direction == "Buy" else "red"),
            ("  ·  ", "dim"),
            (units_str, ""),
            (" units @ ", "dim"),
            (f"{avg_word}${p.open_rate:,.2f}", ""),
            (ccy_note, "dim"),
            ("\n\n", ""),
            # Price + P&L block
            ("Close  ", "dim"),
            (f"${p.current_rate:,.2f}", color),
            ("    ", ""),
            (f"{sign}{abs(p.pnl_pct):.2f}%", color),
            ("  ", ""),
            (f"({sign}${abs(p.pnl):,.2f})", color),
            ("\n", ""),
            ("Value  ", "dim"),
            (f"${p.value:,.2f}", "bold"),
            ("    ", ""),
            (f"{eq_pct:.1f}% of equity", "dim"),
            ("\n\n", ""),
            # Fundamentals block
            ("Fundamentals\n", "bold"),
            ("  PE-T  ", "dim"), (pet_label, pet_color),
            ("    PE-F  ", "dim"), (pef_label, pef_color),
            ("\n", ""),
            ("  Tgt   ", "dim"), (tgt_label, tgt_color),
            ("    Up%   ", "dim"), (ups_label, ups_color),
            ("\n", ""),
            ("  Buy%  ", "dim"), (buy_label, buy_color),
            ("\n\n", ""),
            # Social / signals
            ("Social\n", "bold"),
            ("  Sig   ", "dim"), (sig_label, sig_color),
            ("    Census  ", "dim"), (pi_label, pi_color), (" PIs", "dim"),
            ("\n", ""),
            ("  News 24h  ", "dim"), (news_label, news_color),
        ))

        self.query_one("#dp-today-label", Static).update(Text("Close (24h)", style="dim"))
        self.query_one("#dp-week-label", Static).update(Text("Close (7d)", style="dim"))

    def watch_intraday(self, vals: tuple[float, ...]) -> None:
        if self.is_mounted:
            self.query_one("#dp-today", Sparkline).data = list(vals)

    def watch_seven_day(self, vals: tuple[float, ...]) -> None:
        if self.is_mounted:
            self.query_one("#dp-week", Sparkline).data = list(vals)
