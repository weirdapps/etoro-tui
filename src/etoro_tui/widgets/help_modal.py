"""Modal screen for the `?` help overlay."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

_BINDINGS_TABLE = (
    ("↑ / ↓", "select row"),
    ("s", "cycle sort"),
    ("/", "filter by symbol substring"),
    ("Esc", "clear filter / close modal"),
    ("r", "refresh now (bypass 5s timer)"),
    ("?", "this help"),
    ("q / Ctrl+C", "quit"),
)

# Each tuple: (column header, what it actually is, refresh cadence).
_DATA_LEGEND = (
    ("SYMBOL", "eToro instrument symbol", "live"),
    ("Price", "last execution (eToro /market-data/rates)", "live ~5s"),
    (
        "Δday",
        "(Price − prev_close) / prev_close · 100 — today's move; prev_close = census yesterday-close, FX-adjusted",
        "live ~5s",
    ),
    ("Value", "units × Price", "live"),
    ("Allocation", "Value / total equity", "live"),
    ("Profit", "(Price − Open) × units · dir — total since open, NOT today", "live"),
    ("PET", "trailing 12m P/E (etorotrade)", "daily ~22 UTC"),
    ("PEF", "forward 12m P/E (etorotrade)", "daily"),
    ("Upside", "analyst-target implied upside", "daily"),
    ("Buy %", "% of analyst recs = BUY", "daily"),
    ("ΔBuy", "Δ in Buy % over 3 months (etorotrade AM) — ▲ upgrades / ▼ downgrades", "daily"),
    ("PIs", "% of eToro popular investors holding", "daily"),
    ("Signal", "etorotrade BUY / SELL / HOLD", "daily"),
)


def _fmt_age(mtime: float | None) -> str:
    if mtime is None:
        return "(missing)"
    delta = datetime.now(UTC) - datetime.fromtimestamp(mtime, tz=UTC)
    hrs = delta.total_seconds() / 3600
    if hrs < 1:
        return f"{int(delta.total_seconds() / 60)} min ago"
    if hrs < 48:
        return f"{hrs:.1f} h ago"
    return f"{hrs / 24:.1f} d ago"


def _build_body(
    auth_source: str,
    snapshot_db: str,
    signals_mtime: float | None,
    census_mtime: float | None,
) -> Text:
    parts: list = []

    parts.append(("Key bindings\n", "bold cyan"))
    for keys, action in _BINDINGS_TABLE:
        parts.append((f"  {keys:<14}", "bold"))
        parts.append((f"{action}\n", "dim"))

    parts.append(("\nColumns\n", "bold cyan"))
    for label, what, when in _DATA_LEGEND:
        parts.append((f"  {label:<8}", "bold"))
        parts.append((f"{what}\n", ""))
        parts.append((f"          {when}\n", "dim"))

    parts.append(("\nWhat IS live\n", "bold cyan"))
    parts.append(("  • Position list  ", "dim"))
    parts.append(("(eToro REST every 5s — open/close/amend reflects within seconds)\n", ""))
    parts.append(("  • Cash credit    ", "dim"))
    parts.append(("(same fetch as positions)\n", ""))
    parts.append(("  • Price / Value / Δday / Profit  ", "dim"))
    parts.append(("(eToro /market-data/rates every 5s, batched all symbols)\n", ""))
    parts.append(("\nWhat is daily-refreshed\n", "bold cyan"))
    parts.append(
        ("  Fundamentals (PET, PEF, Upside, Buy %, ΔBuy, Signal) come from etorotrade's\n", "dim")
    )
    parts.append(
        ("  CSV, regenerated nightly. PIs and Δday's prev_close come from census,\n", "dim")
    )
    parts.append(("  regenerated daily.\n", "dim"))
    parts.append(("\nFallback behaviour\n", "bold cyan"))
    parts.append(("  If the live rates endpoint fails, prices fall back to census\n", "dim"))
    parts.append(("  (yesterday's close). The footer indicator turns yellow ('census\n", "dim"))
    parts.append(("  fallback') so you know your numbers are stale.\n", "dim"))

    parts.append(("\nData freshness\n", "bold cyan"))
    parts.append(("  Census priceData  ", "dim"))
    parts.append((f"{_fmt_age(census_mtime)}\n", ""))
    parts.append(("  etorotrade CSV    ", "dim"))
    parts.append((f"{_fmt_age(signals_mtime)}\n", ""))

    parts.append(("\nDiagnostics\n", "bold cyan"))
    parts.append(("  Auth source   ", "dim"))
    parts.append((f"{auth_source}", ""))
    parts.append(("  (env / envfile / keyring)\n", "dim"))
    parts.append(("  Snapshot DB   ", "dim"))
    parts.append((f"{snapshot_db}\n", ""))

    parts.append(("\nDisclaimer\n", "bold cyan"))
    parts.append(("  Unofficial open-source tool. Not affiliated with eToro.\n", "dim"))
    parts.append(("  Not financial advice. Use at your own risk.\n", "dim"))
    parts.append(("  Numbers may differ from your eToro app — verify there\n", "dim"))
    parts.append(("  before any trading decision.\n", "dim"))

    parts.append(("\nPress ", "dim"))
    parts.append(("?", "bold cyan"))
    parts.append((" or ", "dim"))
    parts.append(("Esc", "bold cyan"))
    parts.append((" to close.", "dim"))
    return Text.assemble(*parts)


class HelpModal(ModalScreen[None]):
    """Centered help dialog. Dismiss with `?`, Esc, or Enter."""

    BINDINGS = [
        Binding("question_mark", "dismiss", "close", show=False),
        Binding("escape", "dismiss", "close", show=False),
        Binding("enter", "dismiss", "close", show=False),
        Binding("q", "dismiss", "close", show=False),
    ]

    def __init__(
        self,
        auth_source: str,
        snapshot_db: str,
        signals_mtime: float | None = None,
        census_mtime: float | None = None,
    ) -> None:
        super().__init__()
        self._body = _build_body(auth_source, snapshot_db, signals_mtime, census_mtime)

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(self._body)

    def action_dismiss(self) -> None:
        self.dismiss()
