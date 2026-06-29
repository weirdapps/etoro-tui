"""Footer: key legend + sort indicator + last-fetch + error banner."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Static


def _legend() -> Text:
    """Compact key legend with bright key chips and dim labels."""
    pairs = [
        ("↑↓", "select"),
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
    """Renders key legend + sort indicator + price-source + last-fetch + errors."""

    last_fetch: reactive[datetime | None] = reactive(None)
    last_error: reactive[str | None] = reactive(None)
    sort_label: reactive[str] = reactive("Value ↓")
    prices_source: reactive[str] = reactive("—")  # "live" | "census" | "—"
    census_stale: reactive[bool] = reactive(False)
    asset_count: reactive[int] = reactive(0)  # distinct instruments held (not lots)

    def compose(self) -> ComposeResult:
        with Horizontal(id="footer-bar"):
            yield Static(_legend(), id="footer-legend")
            yield Static("", id="footer-sort")
            yield Static("", id="footer-assets")
            yield Static("", id="footer-prices")
            yield Static("", id="footer-census")
            yield Static("", id="footer-fetch")
        yield Static("", id="footer-error")

    def on_mount(self) -> None:
        # Render initial labels so the footer isn't half-empty on launch.
        self.watch_sort_label(self.sort_label)
        self.watch_prices_source(self.prices_source)
        self.watch_census_stale(self.census_stale)
        self.watch_asset_count(self.asset_count)

    def watch_last_fetch(self, value: datetime | None) -> None:
        widget = self.query_one("#footer-fetch", Static)
        if value is None:
            widget.update(Text("waiting…", style="dim"))
            return
        delta = int((datetime.now(UTC) - value).total_seconds())
        widget.update(Text(f"updated {delta}s ago", style="dim"))

    def watch_sort_label(self, value: str) -> None:
        # "by Value ↓" reads as a label; avoids saying "sort" twice (the key
        # legend already has "[s] sort").
        self.query_one("#footer-sort", Static).update(
            Text.assemble(("by  ", "dim"), (value, "bold"))
        )

    def watch_asset_count(self, value: int) -> None:
        # Count of distinct instruments held (table rows), not eToro lots — the
        # per-row "Pos" column already shows lot counts.
        noun = "asset" if value == 1 else "assets"
        self.query_one("#footer-assets", Static).update(
            Text.assemble((f"{value}", "bold"), (f" {noun}", "dim"))
        )

    def watch_prices_source(self, value: str) -> None:
        # Color the indicator: green=live (ws/rest), yellow=census fallback,
        # dim=unknown. The value carries the source, e.g. "live (ws)".
        if value.startswith("live"):
            label = Text.assemble(("prices  ", "dim"), (f"● {value}", "green"))
        elif value.startswith("census"):
            label = Text.assemble(("prices  ", "dim"), ("● census fallback", "yellow"))
        else:
            label = Text.assemble(("prices  ", "dim"), (value, "dim"))
        self.query_one("#footer-prices", Static).update(label)

    def watch_census_stale(self, value: bool) -> None:
        # Invisible when fresh — no footer noise during normal operation. Yellow
        # 'census stale' when the latest archive file failed to parse and we're
        # serving the previous cache (typically a ~1s race with the daily writer).
        widget = self.query_one("#footer-census", Static)
        if value:
            widget.update(Text.assemble(("census  ", "dim"), ("● stale", "yellow")))
        else:
            widget.update("")

    def watch_last_error(self, value: str | None) -> None:
        widget = self.query_one("#footer-error", Static)
        if value:
            widget.update(Text.assemble(("⚠ ", "red bold"), (value, "red")))
            widget.styles.display = "block"
        else:
            widget.update("")
            widget.styles.display = "none"
