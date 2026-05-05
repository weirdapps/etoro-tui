"""Footer: key legend + sort indicator + last-fetch + error banner."""
from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Static


def _legend() -> Text:
    """Compact key legend with bright key chips and dim labels."""
    pairs = [
        ("↑↓", "select"),
        ("⏎", "detail"),
        ("s", "sort"),
        ("/", "filter"),
        ("r", "refresh"),
        ("?", "help"),
        ("q", "quit"),
    ]
    parts: list = []
    for i, (k, label) in enumerate(pairs):
        if i:
            parts.append(("  ", ""))
        parts.append((f"[{k}]", "bold cyan"))
        parts.append((f" {label}", "dim"))
    return Text.assemble(*parts)


class Footer(Vertical):
    """Renders key legend + sort indicator + last-fetch + error row when set."""

    last_fetch: reactive[datetime | None] = reactive(None)
    last_error: reactive[str | None] = reactive(None)
    sort_label: reactive[str] = reactive("Value ↓")

    def compose(self) -> ComposeResult:
        with Horizontal(id="footer-bar"):
            yield Static(_legend(), id="footer-legend")
            yield Static("", id="footer-sort")
            yield Static("", id="footer-fetch")
        yield Static("", id="footer-error")

    def on_mount(self) -> None:
        # Render initial sort label so the footer isn't half-empty on launch.
        self.watch_sort_label(self.sort_label)

    def watch_last_fetch(self, value: datetime | None) -> None:
        widget = self.query_one("#footer-fetch", Static)
        if value is None:
            widget.update(Text("waiting…", style="dim"))
            return
        delta = int((datetime.now(timezone.utc) - value).total_seconds())
        widget.update(Text(f"updated {delta}s ago", style="dim"))

    def watch_sort_label(self, value: str) -> None:
        self.query_one("#footer-sort", Static).update(
            Text.assemble(("sort  ", "dim"), (value, "bold"))
        )

    def watch_last_error(self, value: str | None) -> None:
        widget = self.query_one("#footer-error", Static)
        if value:
            widget.update(Text.assemble(("⚠ ", "red bold"), (value, "red")))
            widget.styles.display = "block"
        else:
            widget.update("")
            widget.styles.display = "none"
