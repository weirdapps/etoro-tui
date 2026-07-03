"""Main DataTable: aggregated-by-ticker positions, sortable + filterable.

Column labels are deliberately precise so nothing is mistaken for live data:

  SYMBOL    — eToro instrument symbol (live; positions added/removed as you trade)
  Price     — last execution from /market-data/instruments/rates (LIVE, ~5s poll)
              in the instrument's listing currency. Matches the quote on
              Yahoo / eToro web / the issuer page. Falls back to census
              priceData (yesterday's close) if rates fail.
  Curr      — listing currency code (USD / EUR / GBp / HKD / DKK / …),
              derived from the symbol suffix; "—" when the suffix is unknown.
  Δday      — (Price − prev_close) / prev_close · 100, where prev_close is
              yesterday's close from census priceData (DAILY refresh ~00:00 UTC).
              FX-invariant — same number whether computed in USD or local.
              Shows "—" for symbols not covered by census.
  Value     — units × Price, in USD (live, integer rounding)
  Allocation — Value / total equity (live)
  Profit    — (Price − Open) × units × dir, total since open, NOT today's change
              (live, integer rounding). For lifetime % return see detail panel.
  PET       — trailing 12m P/E from etorotrade (DAILY ~22:00 UTC)
  PEF       — forward 12m P/E (DAILY)
  Upside    — analyst-target implied upside (DAILY)
  Buy %     — % of analyst recs = BUY (DAILY)
  ΔBuy      — change in Buy % over the past 3 months (etorotrade AM, DAILY)
              ▲ upgrades / ▼ downgrades — bright when ≥|5|pp
  PIs       — % of the top-100 most-copied eToro popular investors holding (DAILY)
  Signal    — etorotrade BUY / SELL / HOLD (DAILY)

Lots and per-position Units live in the detail panel — for daily glance the
aggregated $ matters more than how many lots accumulated it.

Value / Profit / Allocation are FX-converted to USD (account currency) so
totals roll up correctly. Only the per-share Price column shows the local
quote — that's the cell users cross-check against external sources.
"""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, Input

from ..models import Position

SortKey = Literal[
    "value",
    "pnl",
    "day_change_pct",
    "upside_pct",
    "analyst_buy_pct",
    "pe_forward",
    "symbol",
    "signal",
]
_SORT_CYCLE: list[SortKey] = [
    "value",
    "pnl",
    "day_change_pct",
    "upside_pct",
    "analyst_buy_pct",
    "pe_forward",
    "signal",
    "symbol",
]
SORT_LABELS: dict[SortKey, str] = {
    "value": "Value ↓",
    "pnl": "Profit ↓",
    "day_change_pct": "Δday ↓",
    "upside_pct": "Upside ↓",
    "analyst_buy_pct": "Buy % ↓",
    "pe_forward": "PEF ↑",  # cheaper first
    "signal": "Signal",
    "symbol": "SYMBOL",
}

_SIG_STYLE = {
    "BUY": ("bold green", "BUY"),
    "SELL": ("bold red", "SELL"),
    "HOLD": ("dim", "HOLD"),
}

# Column specifications. Each tuple = (label, key, min_inner, flex_weight, align).
#   - label: header text (with "│ " prefix for non-first columns so the divider
#     also appears in the header row, vertically aligned with cell dividers).
#   - key: short name used by formatters as a key into _INNER / _ALIGN.
#   - min_inner: minimum inner width (excludes the "│ " prefix). Column will
#     never shrink below this even on narrow terminals.
#   - flex_weight: extra terminal width is distributed proportionally to this.
#     Columns whose data benefits from room (Profit, Value, SYMBOL) get higher
#     weights; tight numeric columns (PET, PIs) get lower weights.
#   - align: how the value is positioned within inner_width.
_COL_SPECS: tuple[tuple[str, str, int, float, str], ...] = (
    ("SYMBOL", "SYMBOL", 9, 1.0, "left"),
    ("│ Price", "Price", 8, 1.2, "right"),
    ("│ Curr", "Curr", 3, 0.2, "center"),
    ("│ Δday", "Δday", 8, 0.8, "right"),
    ("│ Value", "Value", 9, 1.2, "right"),
    ("│ Alloc", "Alloc", 5, 0.4, "right"),
    ("│ Profit", "Profit", 9, 1.5, "right"),
    ("│ PET", "PET", 5, 0.3, "right"),
    ("│ PEF", "PEF", 5, 0.3, "right"),
    ("│ Upside", "Upside", 7, 0.8, "right"),
    ("│ Buy %", "Buy %", 5, 0.4, "right"),
    ("│ ΔBuy", "ΔBuy", 4, 0.3, "right"),
    ("│ PIs", "PIs", 4, 0.3, "right"),
    ("│ Signal", "Signal", 4, 0.4, "center"),
)

# Mutable inner widths — compute_widths() updates these on mount/resize, and
# formatters read them via _cell(). Single source of truth so formatters and
# DataTable column widths can never drift apart.
_INNER: dict[str, int] = {key: minw for _, key, minw, _, _ in _COL_SPECS}
_ALIGN: dict[str, str] = {key: a for _, key, _, _, a in _COL_SPECS}


def compute_widths(available_chars: int) -> None:
    """Distribute terminal width across columns by flex weight.

    Mutates _INNER so all formatters automatically use the new widths. Call
    this on mount and on terminal resize.

    `available_chars` = the width the table widget gets (typically the full
    screen width for our layout where the table spans 1fr).
    """
    base_sum = sum(spec[2] for spec in _COL_SPECS)
    flex_sum = sum(spec[3] for spec in _COL_SPECS)
    # Per-column overhead inside DataTable:
    #   - SYMBOL has no "│ " prefix; all 11 others contribute 2 chars for it.
    #   - Default cell_padding=1 each side ⇒ 2 chars per column.
    #   - 1 extra for the cursor column / scrollbar.
    sep_overhead = sum(2 for label, *_ in _COL_SPECS if label.startswith("│"))
    cell_padding = len(_COL_SPECS) * 2
    overhead = sep_overhead + cell_padding + 1
    extra = max(0, available_chars - base_sum - overhead)
    if flex_sum <= 0 or extra <= 0:
        # Reset to mins (tightest layout for narrow terminals).
        for _, key, minw, _, _ in _COL_SPECS:
            _INNER[key] = minw
        return
    for _, key, minw, flex, _ in _COL_SPECS:
        _INNER[key] = minw + round(extra * flex / flex_sum)


def _grad_color(magnitude: float, thresholds: tuple[float, float], positive: bool) -> str:
    """Bloomberg 3-tier colour: bright/normal/dim by magnitude.

    `thresholds` = (small, large). Below small → dim, above large → bold.
    `positive` selects green (True) or red (False).
    """
    base = "green" if positive else "red"
    a = abs(magnitude)
    if a >= thresholds[1]:
        return f"bold bright_{base}"
    if a >= thresholds[0]:
        return base
    return f"dim {base}"


# (label, width). Width = None lets DataTable auto-size; explicit widths
# include the inline "│ " separator (2 chars) injected by each formatter.
# Bloomberg-style column dividers are baked into cell text since Textual's
# DataTable has no native show_dividers option.


def _cell(value: str, col: str, *, style: str = "", align: str | None = None) -> Text:
    """Build a cell with the divider at position 0 + value padded in remaining space.

    Returns a Rich Text whose first 2 chars are the dim divider, followed by
    the value right/center/left-aligned within (col_width - 2) chars. This
    keeps all │ characters perfectly column-aligned regardless of value width.

    `align` defaults to the per-column alignment from _ALIGN.
    """
    inner = _INNER[col]
    a = align or _ALIGN.get(col, "right")
    if a == "right":
        padded = f"{value:>{inner}}"
    elif a == "center":
        padded = f"{value:^{inner}}"
    else:
        padded = f"{value:<{inner}}"
    return Text("│ ", style="dim") + Text(padded, style=style)


def _money(v: float) -> Text:
    """Two-decimal money for the Price column. Currency lives in its own column."""
    return _cell(f"{v:,.2f}", "Price")


def _currency(ccy: str) -> Text:
    """Currency code for the Curr column. Dim '—' when unknown."""
    if not ccy:
        return _cell("—", "Curr", style="dim", align="center")
    return _cell(ccy, "Curr", style="dim", align="center")


def _money_int(v: float) -> Text:
    """Integer money for the Value column."""
    return _cell(f"{v:,.0f}", "Value")


def _signal(s: str | None) -> Text:
    """Signal cell — bold BUY/SELL, dim HOLD/missing. Centred."""
    if s is None:
        return _cell("—", "Signal", style="dim", align="center")
    style, label = _SIG_STYLE.get(s, ("", str(s)))
    return _cell(label, "Signal", style=style, align="center")


def _pi(p: float | None) -> Text:
    """% of top-100 PIs holding — a distinct hue per crowding band.

    Shades of one colour read as identical in the terminal, so each band gets
    its own hue:

      ≥25% → bold green (very crowded)   10–25% → cyan (crowded)
      5–10% → yellow (moderate)          <5% → dim (light)
      <0.5% → dim "<1%"                  missing → dim "—"
    """
    if p is None:
        return _cell("—", "PIs", style="dim")
    if p < 0.5:
        return _cell("<1%", "PIs", style="dim")
    if p >= 25:
        style = "bold green"
    elif p >= 10:
        style = "cyan"
    elif p >= 5:
        style = "yellow"
    else:
        style = "dim"
    return _cell(f"{p:.0f}%", "PIs", style=style)


def _day_change_pct(curr: float, prev: float | None) -> Text:
    """Δday with magnitude-coded triangle and intensity-graded colour.

    ▲ = ≥ 1% gain  ▴ = small gain
    ▼ = ≥ 1% loss  ▾ = small loss
    Colour: dim only sub-noise (<0.1%), normal for 0.1-1%, bold bright for ≥1%.
    '—' when prev_close unavailable.
    """
    if prev is None or prev <= 0:
        return _cell("—", "Δday", style="dim")
    pct = (curr - prev) / prev * 100
    a = abs(pct)
    if pct >= 0:
        glyph = "▲" if a >= 1 else "▴"
    else:
        glyph = "▼" if a >= 1 else "▾"
    sign = "+" if pct >= 0 else ""
    color = _grad_color(pct, thresholds=(0.1, 1.0), positive=pct >= 0)
    return _cell(f"{glyph}{sign}{pct:.2f}%", "Δday", style=color)


def _pnl(pnl: float) -> Text:
    """Integer Profit — magnitude-coded colour intensity (bright ≥$10k, normal ≥$1k, dim below)."""
    sign = "+" if pnl >= 0 else "−"
    color = _grad_color(pnl, thresholds=(1_000.0, 10_000.0), positive=pnl >= 0)
    return _cell(f"{sign}{abs(pnl):,.0f}", "Profit", style=color)


def _eq_pct(pct: float) -> Text:
    """Allocation cell — just the percentage. Bold for ≥10% (concentration)."""
    if pct >= 10:
        style = "bold"
    elif pct < 1:
        style = "dim"
    else:
        style = ""
    return _cell(f"{pct:.1f}%", "Alloc", style=style)


def _pe(v: float | None, col: str) -> Text:
    """P/E ratio: dim if >100 (extreme) or <0 (loss-making) or missing."""
    if v is None:
        return _cell("—", col, style="dim")
    if v <= 0 or v > 100:
        return _cell(f"{v:.1f}", col, style="dim")
    return _cell(f"{v:.1f}", col)


def _upside(v: float | None) -> Text:
    """Analyst upside %. Bright green ≥25%, green ≥10%, dim if missing."""
    if v is None:
        return _cell("—", "Upside", style="dim")
    color = _grad_color(v, thresholds=(10.0, 25.0), positive=v >= 0)
    sign = "+" if v >= 0 else ""
    return _cell(f"{sign}{v:.1f}%", "Upside", style=color)


def _buy_pct(v: float | None) -> Text:
    """Analyst buy %. Bold green ≥75, green ≥50, bold red ≤25, dim if missing."""
    if v is None:
        return _cell("—", "Buy %", style="dim")
    if v >= 75:
        style = "bold green"
    elif v >= 50:
        style = "green"
    elif v <= 25:
        style = "bold red"
    else:
        style = "dim"
    return _cell(f"{v:.0f}%", "Buy %", style=style)


def _buy_momentum(v: float | None) -> Text:
    """Δ in analyst Buy % over 3 months (etorotrade AM column).

    ▲ upgrades / ▼ downgrades. Symmetric thresholds:
      |Δ| ≥ 5pp → bright, |Δ| ≥ 1pp → normal, otherwise dim.
    Sub-threshold values (-1 < Δ < 1) render as dim "0" with no arrow,
    visually deprioritising noise so real moves stand out.
    """
    if v is None:
        return _cell("—", "ΔBuy", style="dim")
    if -1 < v < 1:
        return _cell("0", "ΔBuy", style="dim")
    glyph = "▲" if v > 0 else "▼"
    sign = "+" if v > 0 else "−"
    color = _grad_color(v, thresholds=(1.0, 5.0), positive=v > 0)
    return _cell(f"{glyph}{sign}{abs(v):.0f}", "ΔBuy", style=color)


class PositionsTable(Vertical):
    positions: reactive[tuple[Position, ...]] = reactive(())
    equity: reactive[float] = reactive(0.0)
    sort_key: reactive[SortKey] = reactive("value")
    filter_text: reactive[str] = reactive("")

    class PositionSelected(Message):
        def __init__(self, position: Position | None) -> None:
            self.position = position
            super().__init__()

    class SortChanged(Message):
        def __init__(self, key: SortKey) -> None:
            self.key = key
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter symbol…", id="filter", classes="hidden")
        yield DataTable(id="positions-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        # Compute initial widths based on current screen size, then add columns.
        compute_widths(self._available_width())
        self._add_columns()
        self.query_one(DataTable).focus()

    def _available_width(self) -> int:
        """Width the table widget gets to work with."""
        # self.size may not be set yet at on_mount, fall back to the screen.
        w = self.size.width if self.size.width > 0 else 0
        if w <= 0 and self.app is not None:
            w = self.app.size.width
        # Sensible fallback for very early calls / tests.
        return w if w > 40 else 120

    def _add_columns(self) -> None:
        """(Re-)add columns using widths from _INNER. Idempotent: clears existing first."""
        table = self.query_one(DataTable)
        table.clear(columns=True)
        for label, key, _, _, _ in _COL_SPECS:
            inner = _INNER[key]
            # Non-SYMBOL columns include the "│ " prefix in the cell, so add 2.
            width = inner + (2 if label.startswith("│") else 0)
            table.add_column(label, key=key, width=width)

    def on_resize(self) -> None:
        """Re-flow column widths when the terminal is resized."""
        if not self.is_mounted:
            return
        new_width = self._available_width()
        compute_widths(new_width)
        self._add_columns()
        self._rebuild_table()

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
        self._update_values()

    def watch_equity(self, _: float) -> None:
        self._update_values()

    def watch_sort_key(self, key: SortKey) -> None:
        self._rebuild_table()
        self.post_message(self.SortChanged(key))

    def watch_filter_text(self, _: str) -> None:
        self._rebuild_table()

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
            order = {"BUY": 0, "SELL": 1, "HOLD": 2, None: 3}
            rows.sort(key=lambda p: (order.get(p.signal, 4), p.symbol))
        elif key == "pe_forward":
            # Cheap first. Treat None as huge so missing data sinks to bottom.
            rows.sort(
                key=lambda p: (
                    p.pe_forward if p.pe_forward is not None and p.pe_forward > 0 else float("inf")
                )
            )
        elif key == "day_change_pct":
            # Computed on the fly from current_rate vs prev_close. Missing
            # prev_close → bottom. Biggest gain first.
            def _dc(p: Position) -> float:
                if p.prev_close is None or p.prev_close <= 0:
                    return float("-inf")
                return (p.current_rate - p.prev_close) / p.prev_close * 100

            rows.sort(key=_dc, reverse=True)
        elif key in ("upside_pct", "analyst_buy_pct"):
            # None → bottom. Higher first.
            rows.sort(
                key=lambda p: getattr(p, key) if getattr(p, key) is not None else float("-inf"),
                reverse=True,
            )
        else:
            rows.sort(key=lambda p: getattr(p, key), reverse=True)
        return rows

    def _row_cells(self, p: Position, eq: float) -> tuple:
        pct_eq = (p.value / eq * 100) if eq > 0 else 0.0
        price = p.quote_price if p.quote_price is not None else p.current_rate
        prev = p.quote_prev if p.quote_prev is not None else p.prev_close
        return (
            Text(p.symbol, style="bold"),
            _money(price),
            _currency(p.currency),
            _day_change_pct(price, prev),
            _money_int(p.value),
            _eq_pct(pct_eq),
            _pnl(p.pnl),
            _pe(p.pe_trailing, "PET"),
            _pe(p.pe_forward, "PEF"),
            _upside(p.upside_pct),
            _buy_pct(p.analyst_buy_pct),
            _buy_momentum(p.analyst_momentum),
            _pi(p.pi_pct),
            _signal(p.signal),
        )

    def _update_values(self) -> None:
        """In-place cell updates — preserves scroll and cursor."""
        table = self.query_one(DataTable)
        if table.row_count == 0:
            self._rebuild_table()
            return
        eq = self.equity if self.equity > 0 else 0
        col_keys = [spec[1] for spec in _COL_SPECS]
        pos_map = {str(p.position_id): p for p in self.positions}
        existing_keys = {str(rk.value) for rk in table.rows}
        if pos_map.keys() != existing_keys:
            self._rebuild_table()
            return
        for rk_str, p in pos_map.items():
            cells = self._row_cells(p, eq)
            for ck, val in zip(col_keys, cells, strict=False):
                table.update_cell(rk_str, ck, val, update_width=False)

    def _rebuild_table(self) -> None:
        """Full clear + re-add — used for sort/filter changes and row-set changes."""
        table = self.query_one(DataTable)
        table.clear()
        eq = self.equity if self.equity > 0 else 0
        for p in self._sorted_filtered_positions():
            cells = self._row_cells(p, eq)
            table.add_row(*cells, key=str(p.position_id))
