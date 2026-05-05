# src/etoro_tui/app.py
"""EtoroTuiApp — the Textual application that owns AppState and timers."""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal

from . import config, storage
from .clients.census import CensusReader, InstrumentInfo
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
from .widgets.help_modal import HelpModal
from .widgets.positions_table import PositionsTable, SORT_LABELS

log = logging.getLogger(__name__)


def _to_position(
    raw: dict,
    instruments: dict[int, InstrumentInfo],
    signals: dict,
    pi_pct: dict,
    news: NewsReader,
) -> Position | None:
    """Build a Position from a raw eToro position record.

    Returns None when the instrumentID can't be resolved via census (skip the
    row rather than render with bogus data). eToro returns no symbol/price/pnl
    so we compute them from the census instruments map.

    Census `currentPrice` AND eToro's `openRate` are both in the instrument's
    listing currency (USD for US stocks, GBp for .L, HKD for .HK, DKK for .CO,
    EUR for .DE, etc.). Each eToro position carries an `openConversionRate`
    that is "USD per local currency unit" at the time the position was opened.
    We multiply BOTH openRate and currentPrice by it to convert to USD. This
    is approximate (FX drifts since open) but close enough for a dashboard —
    verified against eToro's own equity figure within ~0.3%.

    The `amount` field already comes back in USD; for verification:
    units × openRate × ocr ≈ amount holds across the board.
    """
    inst_id = raw["instrumentID"]
    info = instruments.get(inst_id)
    if info is None:
        return None
    sym = info.symbol.upper()
    units = float(raw["units"])
    ocr = float(raw.get("openConversionRate", 1.0))
    open_rate = float(raw["openRate"]) * ocr        # local→USD
    current_rate = float(info.current_price) * ocr  # local→USD
    is_buy = bool(raw["isBuy"])
    direction_sign = 1 if is_buy else -1
    value = current_rate * units
    pnl = (current_rate - open_rate) * units * direction_sign
    pnl_pct = ((current_rate - open_rate) / open_rate * 100 * direction_sign
               if open_rate else 0.0)
    cnt = news.count_24h(sym)
    return Position(
        position_id=raw["positionID"],
        symbol=sym,
        direction="Buy" if is_buy else "Sell",
        units=units,
        open_rate=open_rate,
        current_rate=current_rate,
        value=value,
        pnl=pnl,
        pnl_pct=pnl_pct,
        open_ts=datetime.fromisoformat(raw["openDateTime"].replace("Z", "+00:00")),
        signal=signals.get(sym),
        pi_pct=pi_pct.get(sym),
        news_24h=cnt,
        news_anomaly=news.is_anomaly(sym) if cnt is not None else False,
    )


def _aggregate_by_symbol(positions: Iterable[Position]) -> tuple[Position, ...]:
    """Group positions by symbol; produce one synthetic Position per ticker.

    Aggregated fields:
    - units, value, pnl: summed across underlying positions.
    - open_rate: weighted-average USD cost per unit (cost basis ÷ units).
    - current_rate: implied USD per unit (total value ÷ total units).
    - pnl_pct: total_pnl ÷ total_cost × 100.
    - open_ts: earliest open across the group.
    - position_count: how many raw positions were aggregated.
    - direction, signal, pi_pct, news_*: taken from the first position
      (these are per-instrument, identical across the group).
    - position_id: kept as the first position's id, used as a stable key for
      DataTable rows and the snapshot table — has no semantic meaning here.
    """
    groups: dict[str, list[Position]] = defaultdict(list)
    for p in positions:
        groups[p.symbol].append(p)
    out: list[Position] = []
    for sym, ps in groups.items():
        first = ps[0]
        units = sum(p.units for p in ps)
        cost = sum(p.units * p.open_rate for p in ps)   # USD invested
        value = sum(p.value for p in ps)
        pnl = sum(p.pnl for p in ps)
        avg_open = cost / units if units else first.open_rate
        avg_curr = value / units if units else first.current_rate
        pnl_pct = (pnl / cost * 100) if cost else 0.0
        oldest = min(p.open_ts for p in ps)
        out.append(Position(
            position_id=first.position_id,
            symbol=sym,
            direction=first.direction,
            units=units,
            open_rate=avg_open,
            current_rate=avg_curr,
            value=value,
            pnl=pnl,
            pnl_pct=pnl_pct,
            open_ts=oldest,
            signal=first.signal,
            pi_pct=first.pi_pct,
            news_24h=first.news_24h,
            news_anomaly=first.news_anomaly,
            position_count=len(ps),
        ))
    return tuple(out)


def _account_from(positions: tuple[Position, ...], credit: float) -> AccountSummary:
    """Compute account summary from positions + cash. eToro doesn't return one."""
    invested_value = sum(p.value for p in positions)
    unrealized = sum(p.pnl for p in positions)
    return AccountSummary(
        equity=credit + invested_value,
        cash=credit,
        unrealized=unrealized,
        realized=0.0,  # not exposed by the public-api endpoint we use
        fetched_at=datetime.now(timezone.utc),
    )


class EtoroTuiApp(App[None]):
    """Top-level Textual app."""

    CSS_PATH = "styles.tcss"
    TITLE = "etoro-tui"
    SUB_TITLE = "live portfolio"

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
        except EtoroAuthError as e:
            self._set_error(f"auth failed: {e}", "down")
            return
        except EtoroTransientError as e:
            self._set_error(f"transient: {e}", "degraded")
            return

        signals = self._signals.read()
        pi_pct = self._census.read()
        instruments = self._census.instruments()

        raw_positions = portfolio.get("positions", [])
        credit = float(portfolio.get("credit", 0.0))

        positions_list: list[Position] = []
        skipped = 0
        for raw in raw_positions:
            built = _to_position(raw, instruments, signals, pi_pct, self._news)
            if built is None:
                skipped += 1
            else:
                positions_list.append(built)
        if skipped:
            log.info("skipped %d positions (instrumentID not in census)", skipped)

        # Aggregate by symbol — eToro splits a holding into many lots; the
        # user wants one row per ticker with a Pos column showing lot count.
        positions = _aggregate_by_symbol(positions_list)

        acct = _account_from(positions, credit)
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
        try:
            source = config.get_credentials_source()
        except Exception:
            source = "unknown"
        self.push_screen(HelpModal(
            auth_source=source,
            snapshot_db=str(config.SNAPSHOT_DB_PATH),
        ))

    # ------- messages -------

    def on_positions_table_sort_changed(
        self, message: PositionsTable.SortChanged
    ) -> None:
        self.query_one(Footer).sort_label = SORT_LABELS.get(message.key, str(message.key))

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
