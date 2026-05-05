# src/etoro_tui/app.py
"""EtoroTuiApp — the Textual application that owns AppState and timers."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal

from . import config, storage
from .clients.census import CensusReader
from .clients.etoro import (
    EtoroAuthError,
    EtoroClient,
    EtoroTransientError,
)
from .clients.news import NewsReader
from .clients.signals import SignalsReader
from .models import AccountSummary, AppState, Position, Status
from .widgets.detail_panel import DetailPanel
from .widgets.footer import Footer
from .widgets.header import Header
from .widgets.positions_table import PositionsTable

log = logging.getLogger(__name__)


def _to_position(raw: dict, signals: dict, census: dict, news: NewsReader) -> Position:
    sym = raw["symbol"].upper()
    cnt = news.count_24h(sym)
    return Position(
        position_id=raw["positionId"],
        symbol=sym,
        direction=raw["direction"],
        units=float(raw["units"]),
        open_rate=float(raw["openRate"]),
        current_rate=float(raw["currentRate"]),
        value=float(raw["units"]) * float(raw["currentRate"]),
        pnl=float(raw["profit"]),
        pnl_pct=float(raw["profitPercentage"]),
        open_ts=datetime.fromisoformat(raw["openTimestamp"].replace("Z", "+00:00")),
        signal=signals.get(sym),
        pi_pct=census.get(sym),
        news_24h=cnt,
        news_anomaly=news.is_anomaly(sym) if cnt is not None else False,
    )


def _to_account(raw: dict) -> AccountSummary:
    return AccountSummary(
        equity=float(raw["equity"]),
        cash=float(raw["availableBalance"]),
        unrealized=float(raw["unrealizedProfit"]),
        realized=float(raw["realizedProfit"]),
        fetched_at=datetime.now(timezone.utc),
    )


class EtoroTuiApp(App[None]):
    """Top-level Textual app."""

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "sort", "Sort"),
        Binding("slash", "filter", "Filter", key_display="/"),
        Binding("escape", "clear_filter", "Clear filter", show=False),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("enter", "toggle_detail", "Detail", show=False),
    ]

    def __init__(
        self,
        initial_state: Optional[AppState] = None,
        disable_polling: bool = False,
        etoro_client: Optional[EtoroClient] = None,
    ) -> None:
        super().__init__()
        self._state: AppState = initial_state or AppState(
            account=None, positions=(), last_error=None,
            status="live", equity_sparkline=(),
        )
        self._disable_polling = disable_polling
        self._etoro_client = etoro_client
        self._signals = SignalsReader(config.SIGNALS_CSV)
        self._census = CensusReader(config.CENSUS_GLOB_DIR, config.CENSUS_GLOB_PATTERN)
        self._news = NewsReader(config.NEWS_DB_PATH)
        self._db: Optional[sqlite3.Connection] = None
        self._opening_equity_today: Optional[float] = None
        self._show_detail = False

    # ------- composition -------

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        with Horizontal(id="main"):
            yield PositionsTable(id="table")
            yield DetailPanel(id="detail", classes="hidden")
        yield Footer(id="footer")

    async def on_mount(self) -> None:
        self._db = storage.init_db(config.SNAPSHOT_DB_PATH)
        self._render_state()
        if self._disable_polling:
            return
        # Auth-required: build client now if not injected.
        if self._etoro_client is None:
            try:
                pk, uk = config.get_credentials()
            except config.AuthMissingError as e:
                self._set_error(str(e), "down")
                return
            self._etoro_client = EtoroClient(public_key=pk, user_key=uk)
        self.set_interval(config.POLL_PORTFOLIO_S, self._tick_etoro)
        self.set_interval(config.POLL_SIGNALS_S, self._tick_overlays)
        self.set_interval(config.SNAPSHOT_S, self._tick_snapshot)
        self.set_interval(1.0, self._tick_footer_clock)
        await self._tick_etoro()

    async def on_unmount(self) -> None:
        if self._etoro_client is not None:
            await self._etoro_client.aclose()
        if self._db is not None:
            self._db.close()

    # ------- timers -------

    async def _tick_etoro(self) -> None:
        if self._etoro_client is None:
            return
        try:
            portfolio = await self._etoro_client.fetch_portfolio()
            account = await self._etoro_client.fetch_account()
        except EtoroAuthError as e:
            self._set_error(f"auth failed: {e}", "down")
            return
        except EtoroTransientError as e:
            self._set_error(f"transient: {e}", "degraded")
            return

        signals = self._signals.read()
        census = self._census.read()
        positions = tuple(
            _to_position(p, signals, census, self._news)
            for p in portfolio.get("positions", [])
        )
        acct = _to_account(account)
        if self._opening_equity_today is None:
            self._opening_equity_today = acct.equity

        spark = ()
        if self._db is not None:
            spark = storage.read_equity_sparkline(self._db, hours=24, max_points=80)

        self._state = AppState(
            account=acct, positions=positions, last_error=None,
            status="live", equity_sparkline=spark,
        )
        self._render_state()

    def _tick_overlays(self) -> None:
        # Re-attach current overlay values without re-fetching from eToro.
        if self._state.account is None:
            return
        signals = self._signals.read()
        census = self._census.read()
        new_positions = []
        for p in self._state.positions:
            cnt = self._news.count_24h(p.symbol)
            new_positions.append(replace(
                p,
                signal=signals.get(p.symbol),
                pi_pct=census.get(p.symbol),
                news_24h=cnt,
                news_anomaly=self._news.is_anomaly(p.symbol) if cnt is not None else False,
            ))
        self._state = AppState(
            account=self._state.account, positions=tuple(new_positions),
            last_error=self._state.last_error, status=self._state.status,
            equity_sparkline=self._state.equity_sparkline,
        )
        self._render_state()

    def _tick_snapshot(self) -> None:
        if self._db is None or self._state.account is None:
            return
        try:
            storage.write_snapshot(self._db, self._state.account, self._state.positions)
        except Exception as e:  # noqa: BLE001 — snapshot is best-effort
            log.warning("snapshot write failed: %s", e)

    def _tick_footer_clock(self) -> None:
        if self._state.account is not None:
            self.query_one(Footer).last_fetch = self._state.account.fetched_at

    # ------- rendering -------

    def _render_state(self) -> None:
        header = self.query_one(Header)
        header.account = self._state.account
        header.status = self._state.status
        header.sparkline_values = self._state.equity_sparkline
        if self._state.account is not None:
            header.open_pnl = self._state.account.unrealized
            if self._opening_equity_today is not None:
                delta = self._state.account.equity - self._opening_equity_today
                pct = (delta / self._opening_equity_today * 100
                       if self._opening_equity_today else 0)
                header.today_delta = (delta, pct)
        self.query_one(PositionsTable).positions = self._state.positions
        footer = self.query_one(Footer)
        footer.last_error = self._state.last_error

    def _set_error(self, msg: str, status: Status) -> None:
        self._state = AppState(
            account=self._state.account, positions=self._state.positions,
            last_error=msg, status=status, equity_sparkline=self._state.equity_sparkline,
        )
        self._render_state()

    # ------- actions -------

    async def action_refresh(self) -> None:
        await self._tick_etoro()

    def action_sort(self) -> None:
        self.query_one(PositionsTable).cycle_sort()

    def action_filter(self) -> None:
        self.query_one(PositionsTable).show_filter()

    def action_clear_filter(self) -> None:
        self.query_one(PositionsTable).hide_filter()

    def action_toggle_detail(self) -> None:
        self._show_detail = not self._show_detail
        panel = self.query_one(DetailPanel)
        panel.set_class(not self._show_detail, "hidden")

    def action_help(self) -> None:
        # v1 — help via footer briefly
        self._set_error(
            "keys: ↑↓ select · enter detail · s sort · / filter · r refresh · q quit",
            self._state.status,
        )

    # ------- messages -------

    def on_positions_table_position_selected(
        self, message: PositionsTable.PositionSelected
    ) -> None:
        panel = self.query_one(DetailPanel)
        panel.position = message.position
        if message.position is not None and self._db is not None:
            spark = storage.read_position_sparkline(
                self._db, message.position.symbol, hours=24, max_points=40
            )
            panel.intraday = spark
            week = storage.read_position_sparkline(
                self._db, message.position.symbol, hours=24 * 7, max_points=40
            )
            panel.seven_day = week
