"""Modal screen for the `?` help overlay."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


_BINDINGS_TABLE = (
    ("↑ / ↓",     "select row"),
    ("Enter",     "toggle detail panel"),
    ("s",         "cycle sort (Value → P&L → Δ% → Symbol → Signal)"),
    ("/",         "filter by symbol substring"),
    ("Esc",       "clear filter / close modal"),
    ("r",         "refresh now (bypass 5s timer)"),
    ("?",         "this help"),
    ("q / Ctrl+C","quit"),
)


def _build_body(auth_source: str, snapshot_db: str) -> Text:
    parts: list = [
        ("Key bindings\n", "bold cyan"),
    ]
    for keys, action in _BINDINGS_TABLE:
        parts.append((f"  {keys:<14}", "bold"))
        parts.append((f"{action}\n", "dim"))
    parts.append(("\nDiagnostics\n", "bold cyan"))
    parts.append(("  Auth source   ", "dim"))
    parts.append((f"{auth_source}\n", ""))
    parts.append(("  Snapshot DB   ", "dim"))
    parts.append((f"{snapshot_db}\n", ""))
    parts.append(("\n", ""))
    parts.append(("Press ", "dim"))
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

    def __init__(self, auth_source: str, snapshot_db: str) -> None:
        super().__init__()
        self._body = _build_body(auth_source, snapshot_db)

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(self._body)

    def action_dismiss(self) -> None:
        self.dismiss()
