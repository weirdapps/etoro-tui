"""Modal screen for the `?` help overlay."""
from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


_BINDINGS_TABLE = (
    ("↑ / ↓",     "select row"),
    ("Enter",     "toggle detail panel"),
    ("s",         "cycle sort"),
    ("/",         "filter by symbol substring"),
    ("Esc",       "clear filter / close modal"),
    ("r",         "refresh now (bypass 5s timer)"),
    ("?",         "this help"),
    ("q / Ctrl+C","quit"),
)

# Each tuple: (column header, what it actually is, refresh cadence).
_DATA_LEGEND = (
    ("Symbol",  "eToro instrument symbol",                 "live"),
    ("Open",    "weighted-avg cost per unit, USD",         "static"),
    ("Last",    "last execution (eToro /market-data/rates)","live ~5s"),
    ("Δ%",      "(Last − Open) / Open · 100  — total since open, NOT today",  "live"),
    ("Value $", "units × Last",                            "live"),
    ("% Eq",    "Value / total equity",                    "live"),
    ("P&L $",   "(Last − Open) × units · dir — total since open, NOT today",  "live"),
    ("PE-T",    "trailing 12m P/E (etorotrade)",           "daily ~22 UTC"),
    ("PE-F",    "forward 12m P/E (etorotrade)",            "daily"),
    ("Up%",     "analyst-target implied upside",           "daily"),
    ("Buy%",    "% of analyst recs = BUY",                 "daily"),
    ("PI%",     "% of eToro popular investors holding",    "daily"),
    ("Sig",     "etorotrade BUY / SELL / HOLD",            "daily"),
)


def _fmt_age(mtime: float | None) -> str:
    if mtime is None:
        return "(missing)"
    delta = datetime.now(timezone.utc) - datetime.fromtimestamp(mtime, tz=timezone.utc)
    hrs = delta.total_seconds() / 3600
    if hrs < 1:
        return f"{int(delta.total_seconds() / 60)} min ago"
    if hrs < 48:
        return f"{hrs:.1f} h ago"
    return f"{hrs/24:.1f} d ago"


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
    parts.append(("  • Last / Value / Δ% / P&L  ", "dim"))
    parts.append(("(eToro /market-data/rates every 5s, batched all symbols)\n", ""))
    parts.append(("\nWhat is daily-refreshed\n", "bold cyan"))
    parts.append(("  Fundamentals (PE-T, PE-F, Up%, Buy%, Sig) come from etorotrade's\n", "dim"))
    parts.append(("  CSV, regenerated nightly. PI% comes from census, regenerated daily.\n", "dim"))
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
    parts.append((f"{auth_source}\n", ""))
    parts.append(("  Snapshot DB   ", "dim"))
    parts.append((f"{snapshot_db}\n", ""))

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
