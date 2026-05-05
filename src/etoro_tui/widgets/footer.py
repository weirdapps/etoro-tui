"""Footer: key legend + last-fetch time + error banner."""
from __future__ import annotations

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Static


KEY_LEGEND = (
    "[↑↓] select  [enter] detail  [s] sort  [/] filter  "
    "[r] refresh  [?] help  [q] quit"
)


class Footer(Vertical):
    """Renders key legend left, last-fetch right, error row when set."""

    last_fetch: reactive[datetime | None] = reactive(None)
    last_error: reactive[str | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Horizontal(id="footer-bar"):
            yield Static(KEY_LEGEND, id="footer-legend")
            yield Static("", id="footer-fetch")
        yield Static("", id="footer-error")

    def watch_last_fetch(self, value: datetime | None) -> None:
        widget = self.query_one("#footer-fetch", Static)
        if value is None:
            widget.update("never fetched")
            return
        delta = (datetime.now(timezone.utc) - value).total_seconds()
        widget.update(f"last fetch {int(delta)}s ago")

    def watch_last_error(self, value: str | None) -> None:
        widget = self.query_one("#footer-error", Static)
        widget.update(f"⚠ {value}" if value else "")
        widget.styles.display = "block" if value else "none"
