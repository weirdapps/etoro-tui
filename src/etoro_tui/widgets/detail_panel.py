"""Right-side panel.

Two modes share the same lower sections (Indices + Actions):

  Mode 1 (no row selected) — Portfolio overview:
    title  : "Portfolio overview"
    body   : top 5 holdings with bars + currency mix + today's movers
    indices: live levels of S&P / NASDAQ / Dow / EuroStx50 / ATHEX
    actions: Buy / Add / Hold / Trim / Sell tally with top symbols

  Mode 2 (row selected) — Per-position dossier:
    title  : ticker
    body   : lots / direction / units / open price; Last + P&L; fundamentals; social
    indices: same as overview (always-on context)
    actions: same as overview (always-on context)

Sparklines are deliberately removed — they were degenerate without a long
snapshot history and were burning vertical space that's better spent on
indices + action buckets.
"""
from __future__ import annotations

from collections import Counter

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from ..models import ActionsSummary, IndexSummary, Position


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
        "L": "GBP",  "DE": "EUR", "PA": "EUR", "MI": "EUR", "AS": "EUR",
        "MC": "EUR", "VI": "EUR", "BR": "EUR", "LS": "EUR", "HE": "EUR",
        "ST": "SEK", "OL": "NOK", "CO": "DKK", "HK": "HKD",
        "T":  "JPY", "TO": "CAD", "AX": "AUD", "SI": "SGD", "TA": "ILS",
    }.get(suffix, "OTHER")


def _signed_pct(v: float) -> tuple[str, str]:
    """('+1.23%', 'green') or ('−4.56%', 'red')."""
    sign = "+" if v >= 0 else "−"
    color = "green" if v >= 0 else "red"
    return f"{sign}{abs(v):.2f}%", color


class DetailPanel(Vertical):
    """Two-mode side panel with always-on indices + actions sections."""

    position: reactive[Position | None] = reactive(None)
    all_positions: reactive[tuple[Position, ...]] = reactive(())
    equity: reactive[float] = reactive(0.0)
    indices: reactive[tuple[IndexSummary, ...]] = reactive(())
    actions: reactive[ActionsSummary | None] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static("", id="dp-title")
        yield Static("", id="dp-body")
        yield Static("", id="dp-indices")
        yield Static("", id="dp-actions")

    # ------- mode dispatch -------

    def on_mount(self) -> None:
        self._repaint_all()

    def watch_position(self, _: Position | None) -> None:
        if self.is_mounted:
            self._repaint_main()

    def watch_all_positions(self, _: tuple[Position, ...]) -> None:
        if self.is_mounted:
            self._repaint_main()

    def watch_equity(self, _: float) -> None:
        if self.is_mounted:
            self._repaint_main()

    def watch_indices(self, _: tuple[IndexSummary, ...]) -> None:
        if self.is_mounted:
            self._repaint_indices()

    def watch_actions(self, _: ActionsSummary | None) -> None:
        if self.is_mounted:
            self._repaint_actions()

    def _repaint_all(self) -> None:
        self._repaint_main()
        self._repaint_indices()
        self._repaint_actions()

    def _repaint_main(self) -> None:
        if self.position is None:
            self._render_overview()
        else:
            self._render_position(self.position)

    # ------- mode 1: overview -------

    def _render_overview(self) -> None:
        title = self.query_one("#dp-title", Static)
        body = self.query_one("#dp-body", Static)
        title.update(Text("Portfolio overview", style="bold cyan"))

        positions = list(self.all_positions)
        eq = self.equity
        if not positions or eq <= 0:
            body.update(Text("(awaiting data)", style="dim"))
            return

        positions.sort(key=lambda p: p.value, reverse=True)
        top5 = positions[:5]
        top5_pct = sum(p.value for p in top5) / eq * 100

        ccy_value: dict[str, float] = Counter()
        for p in positions:
            ccy_value[_classify_currency(p.symbol)] += p.value
        ccy_sorted = sorted(ccy_value.items(), key=lambda kv: kv[1], reverse=True)

        gainer = max(positions, key=lambda p: p.pnl_pct)
        loser = min(positions, key=lambda p: p.pnl_pct)

        parts: list = []
        parts.append(("Top 5 holdings\n", "bold"))
        for p in top5:
            pct = p.value / eq * 100
            parts.append((f"  {p.symbol:<10}", "bold"))
            parts.append((f" {pct:>5.1f}% ", ""))
            parts.append((_bar(pct, width=8), "cyan"))
            parts.append((f"  ${p.value:>8,.0f}\n", "dim"))
        parts.append((f"  Top 5 = {top5_pct:.0f}% of equity   ", "dim"))
        parts.append((f"{len(positions)} tickers\n", "dim"))
        parts.append(("\n", ""))

        parts.append(("Currency mix\n", "bold"))
        for ccy, v in ccy_sorted:
            pct = v / eq * 100
            parts.append((f"  {ccy:<6}", ""))
            parts.append((f" {pct:>5.1f}%  ", ""))
            parts.append((_bar(pct, width=8), "cyan"))
            parts.append(("\n", ""))
        parts.append(("\n", ""))

        parts.append(("Today's movers\n", "bold"))
        gp_label, gp_color = _signed_pct(gainer.pnl_pct)
        lp_label, lp_color = _signed_pct(loser.pnl_pct)
        parts.append(("  ▲ ", "green"))
        parts.append((f"{gainer.symbol:<10}", ""))
        parts.append((gp_label + "\n", gp_color))
        parts.append(("  ▼ ", "red"))
        parts.append((f"{loser.symbol:<10}", ""))
        parts.append((lp_label, lp_color))
        body.update(Text.assemble(*parts))

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
            return (fmt.format(v), "") if v is not None else ("—", "dim")

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
            (lots_text, "dim"),
            ("  ·  ", "dim"),
            (p.direction, "green" if p.direction == "Buy" else "red"),
            ("  ·  ", "dim"),
            (units_str, ""),
            (" units @ ", "dim"),
            (f"{avg_word}${p.open_rate:,.2f}", ""),
            (ccy_note, "dim"),
            ("\n\n", ""),
            ("Last   ", "dim"), (f"${p.current_rate:,.2f}", color),
            ("    ", ""),
            (f"{sign}{abs(p.pnl_pct):.2f}%", color),
            ("  ", ""),
            (f"({sign}${abs(p.pnl):,.0f})", color),
            ("\n", ""),
            ("Value  ", "dim"), (f"${p.value:,.0f}", "bold"),
            ("    ", ""),
            (f"{eq_pct:.1f}% of equity", "dim"),
            ("\n\n", ""),
            ("Fundamentals\n", "bold"),
            ("  PE-T  ", "dim"), (pet_label, pet_color),
            ("    PE-F  ", "dim"), (pef_label, pef_color),
            ("\n", ""),
            ("  Tgt   ", "dim"), (tgt_label, tgt_color),
            ("    Up%   ", "dim"), (ups_label, ups_color),
            ("\n", ""),
            ("  Buy%  ", "dim"), (buy_label, buy_color),
            ("\n\n", ""),
            ("Social\n", "bold"),
            ("  Sig   ", "dim"), (sig_label, sig_color),
            ("    Census  ", "dim"), (pi_label, pi_color), (" PIs", "dim"),
            ("\n", ""),
            ("  News 24h  ", "dim"), (news_label, news_color),
        ))

    # ------- always-on: indices block -------

    def _repaint_indices(self) -> None:
        widget = self.query_one("#dp-indices", Static)
        if not self.indices:
            widget.update("")
            return
        parts: list = [("\nIndices\n", "bold cyan")]
        for ix in self.indices:
            change_label, change_color = _signed_pct(ix.change_pct)
            parts.append((f"  {ix.name:<10}", ""))
            parts.append((f" {ix.last:>10,.2f}  ", ""))
            parts.append((change_label + "\n", change_color))
        widget.update(Text.assemble(*parts))

    # ------- always-on: actions snapshot -------

    def _repaint_actions(self) -> None:
        widget = self.query_one("#dp-actions", Static)
        a = self.actions
        if a is None:
            widget.update("")
            return

        rows = (
            ("Buy",  "✚", a.buy,  "green"),    # new ideas, top by upside
            ("Add",  "+", a.add,  "green"),    # held + BUY
            ("Hold", "=", a.hold, ""),         # held + HOLD
            ("Trim", "-", a.trim, "yellow"),   # held + SELL, small
            ("Sell", "✗", a.sell, "red"),      # held + SELL, ≥3% equity
        )

        parts: list = [("\nActions\n", "bold cyan")]
        for label, icon, items, color in rows:
            count = len(items)
            count_text = f"{count:>3}" if count else "  ·"
            count_color = color if count else "dim"
            parts.append((f"  {icon} {label:<5}", "dim"))
            parts.append((count_text + "  ", count_color))
            if items:
                head = ", ".join(items[:3])
                more = f" +{count - 3}" if count > 3 else ""
                parts.append((head, ""))
                parts.append((more + "\n", "dim"))
            else:
                parts.append(("\n", ""))
        widget.update(Text.assemble(*parts))
