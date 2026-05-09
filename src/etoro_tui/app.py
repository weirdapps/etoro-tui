# src/etoro_tui/app.py
"""EtoroTuiApp — the Textual application that owns AppState and timers."""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, TypedDict

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
from .clients.signals import Fundamentals, SignalsReader
from .models import (
    AccountSummary,
    AppState,
    IndexSummary,
    Position,
    Signal,
    Status,
)


class _OverlayKwargs(TypedDict):
    """Typed kwargs for the overlay fields on Position. Mirrors the field
    names exactly so `Position(..., **_overlay_fields(...))` typechecks.
    """
    signal: Optional[Signal]
    pi_pct: Optional[float]
    pe_trailing: Optional[float]
    pe_forward: Optional[float]
    upside_pct: Optional[float]
    analyst_buy_pct: Optional[float]
    target_price: Optional[float]
from .widgets.footer import Footer
from .widgets.header import Header
from .widgets.help_modal import HelpModal
from .widgets.positions_table import PositionsTable, SORT_LABELS

log = logging.getLogger(__name__)


def _resolve_index_ids(instruments: dict[int, InstrumentInfo]) -> list[tuple[str, int]]:
    """Map the configured display-name list to (display_name, instrumentId)
    pairs that actually exist in the census. The list comes from the user's
    TOML config or falls back to a curated default in config.DEFAULT_INDICES."""
    sym_to_id = {info.symbol.upper(): inst_id for inst_id, info in instruments.items()}
    return [(name, sym_to_id[sym.upper()])
            for name, sym in config.get_indices()
            if sym.upper() in sym_to_id]


def _build_indices(
    rates: dict[int, dict],
    instruments: dict[int, InstrumentInfo],
    pairs: list[tuple[str, int]],
) -> tuple[IndexSummary, ...]:
    """Build IndexSummary list. Prices are FX-converted to USD for consistency
    with the portfolio rows — otherwise the same ticker (e.g. LYXGRE.DE which
    is EUR-denominated) shows two different numbers in the two panels.

    live = lastExecution × conversionRateAsk  (USD)
    prev = census currentPrice × conversionRateAsk (USD, same FX as live)
    """
    out: list[IndexSummary] = []
    for name, inst_id in pairs:
        rate = rates.get(inst_id)
        info = instruments.get(inst_id)
        if not rate or not info:
            continue
        try:
            local_live = float(rate.get("lastExecution") or rate.get("bid") or 0)
        except (TypeError, ValueError):
            continue
        if local_live <= 0:
            continue
        ocr = float(rate.get("conversionRateAsk", 1.0))
        live = local_live * ocr
        prev = (float(info.current_price) * ocr) if info.current_price else 0.0
        change_pct = ((live - prev) / prev * 100) if prev > 0 else 0.0
        out.append(IndexSummary(name=name, last=live, change_pct=change_pct))
    return tuple(out)


def _overlay_fields(
    sym: str,
    fund: Fundamentals | None,
    pi_holdings: dict[str, float],
) -> _OverlayKwargs:
    """Build the overlay-kwargs dict for Position.

    Single source of truth for the fields that come from etorotrade
    fundamentals + census PI%. Both `_to_position` (initial build) and
    `_tick_overlays` (overlay-only refresh) call this so the two paths
    can never drift. Adding a new overlay field is a one-line change here.
    """
    return {
        "signal": fund.signal if fund else None,
        "pi_pct": pi_holdings.get(sym),
        "pe_trailing": fund.pe_trailing if fund else None,
        "pe_forward": fund.pe_forward if fund else None,
        "upside_pct": fund.upside_pct if fund else None,
        "analyst_buy_pct": fund.analyst_buy_pct if fund else None,
        "target_price": fund.target_price if fund else None,
    }


def _to_position(
    raw: dict,
    instruments: dict[int, InstrumentInfo],
    fundamentals: dict[str, Fundamentals],
    pi_pct: dict,
    rates: dict[int, dict] | None = None,
) -> Position | None:
    """Build a Position from a raw eToro position record.

    Returns None when the instrumentID can't be resolved via census (skip the
    row rather than render with bogus data). eToro returns no symbol/price/pnl
    so we compute them from the census instruments map.

    Both eToro's `openRate` and the price feeds (live `lastExecution` from
    rates endpoint, or census `currentPrice` as fallback) are in the
    instrument's listing currency (USD for US stocks, GBp for .L, HKD for
    .HK, DKK for .CO, EUR for .DE, etc.).

    For OPEN price we use the position's stored `openConversionRate` (FX rate
    at open time) — that's the only number that reproduces the original cost
    basis correctly.

    For CURRENT price we prefer the live rate's `conversionRateAsk` (current
    FX) when available — most accurate. Fall back to per-position OCR only
    when both live rates AND census are unavailable (shouldn't happen, but
    keeps the row honest).

    The `amount` field already comes back in USD; verification holds across
    the board: units × openRate × openConversionRate ≈ amount.
    """
    inst_id = raw["instrumentID"]
    info = instruments.get(inst_id)
    if info is None:
        return None
    sym = info.symbol.upper()
    units = float(raw["units"])
    open_ocr = float(raw.get("openConversionRate", 1.0))
    open_rate = float(raw["openRate"]) * open_ocr        # local→USD (cost basis)

    # Pick the first sensible live (price, FX) pair. Walk keys explicitly so
    # a 0.0 (briefly possible during corp actions / data glitches) doesn't
    # silently cascade to the next key, and so all-missing → falls back to
    # census without ever calling float(None).
    live = (rates or {}).get(inst_id)
    live_price_fx: tuple[float, float] | None = None
    if live is not None:
        for key in ("lastExecution", "Bid", "bid"):
            val = live.get(key)
            if val is None:
                continue
            try:
                candidate = float(val)
            except (TypeError, ValueError):
                continue
            if candidate > 0:
                live_price_fx = (candidate, float(live.get("conversionRateAsk", 1.0)))
                break

    if live_price_fx is not None:
        # Live last-trade price × current FX (more accurate than per-position OCR).
        local_now, current_ocr = live_price_fx
        current_rate = local_now * current_ocr
    else:
        # Fall back to yesterday's close from census, FX'd at open rate.
        current_ocr = open_ocr
        current_rate = float(info.current_price) * open_ocr
    # Yesterday's close (USD), for Δday. Census stores prices in the local
    # listing currency, so FX it at the same OCR used for current_rate to
    # keep the Δday calculation pure-price (FX neutralises across both
    # sides). When live rates fail we fall back to current_ocr=open_ocr.
    prev_close = float(info.current_price) * current_ocr if info.current_price else None
    is_buy = bool(raw["isBuy"])
    direction_sign = 1 if is_buy else -1
    value = current_rate * units
    pnl = (current_rate - open_rate) * units * direction_sign
    pnl_pct = ((current_rate - open_rate) / open_rate * 100 * direction_sign
               if open_rate else 0.0)
    fund = fundamentals.get(sym)
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
        prev_close=prev_close,
        **_overlay_fields(sym, fund, pi_pct),
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
    - direction, signal, pi_pct, pe_*, upside_pct, analyst_*, target_price:
      taken from the first position (per-instrument, identical across group).
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
            position_count=len(ps),
            pe_trailing=first.pe_trailing,
            pe_forward=first.pe_forward,
            upside_pct=first.upside_pct,
            analyst_buy_pct=first.analyst_buy_pct,
            target_price=first.target_price,
            prev_close=first.prev_close,
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
        self._db: Optional[sqlite3.Connection] = None
        self._opening_equity_today: Optional[float] = None

    # ------- composition -------

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        with Horizontal(id="main"):
            yield PositionsTable(id="table")
        yield Footer(id="footer")

    async def on_mount(self) -> None:
        self._db = storage.init_db(config.SNAPSHOT_DB_PATH)
        # Bootstrap today's reference equity from snapshot history so the
        # "today's Δ" doesn't start at 0% every session. We use the oldest
        # snapshot in the trailing 24h as a proxy for "yesterday's close".
        self._opening_equity_today = self._bootstrap_today_baseline()
        self._render_state()
        # Demo mode: __main__.py attaches synthetic indices before run().
        if hasattr(self, "_demo_indices"):
            self.query_one(Header).indices = self._demo_indices
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

        raw_positions = portfolio.get("positions", [])
        credit = float(portfolio.get("credit", 0.0))

        instruments = self._census.instruments()
        index_pairs = _resolve_index_ids(instruments)

        # Live prices for everything we hold + the index instruments. If this
        # fails, degrade to census (yesterday's close) silently so the UI
        # doesn't break.
        unique_ids = sorted(
            {raw["instrumentID"] for raw in raw_positions}
            | {iid for _, iid in index_pairs}
        )
        rates: dict[int, dict] = {}
        prices_live = False
        if unique_ids:
            try:
                rates = await self._etoro_client.fetch_rates(unique_ids)
                prices_live = bool(rates)
            except EtoroAuthError as e:
                self._set_error(f"auth failed (rates): {e}", "down")
                return
            except EtoroTransientError as e:
                # Don't block the whole tick on a transient rates failure;
                # just note it and let positions render with census prices.
                log.warning("rates fetch failed, using census fallback: %s", e)

        fundamentals = self._signals.fundamentals()
        pi_pct = self._census.read()

        positions_list: list[Position] = []
        skipped = 0
        for raw in raw_positions:
            built = _to_position(raw, instruments, fundamentals, pi_pct, rates)
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
        # If snapshot DB had no history at startup, use first live equity as a
        # last-resort baseline. Subsequent sessions will pick up from snapshots.
        if self._opening_equity_today is None:
            self._opening_equity_today = acct.equity

        spark = ()
        if self._db is not None:
            # Last 4 hours @ 1-min cadence = ~240 points downsampled to width.
            # Short window keeps any pre-fix-era polluted snapshots from
            # dominating the min-max scale and producing a single solid bar.
            spark = storage.read_equity_sparkline(self._db, hours=4, max_points=24)

        # Indices (live levels) feed the header bar. Actions / dossier panel
        # were removed because they depended on local-only data sources
        # (etorotrade signals + census PIs) that other users won't have.
        indices = _build_indices(rates, instruments, index_pairs)
        self.query_one(Header).indices = indices

        # Status reflects rates-fetch outcome too: live only when prices
        # are also live; degraded when we fell back to census silently.
        status: Status = "live" if prices_live else "degraded"
        self._state = AppState(
            account=acct, positions=positions, last_error=None,
            status=status, equity_sparkline=spark,
        )
        self.query_one(Footer).prices_source = "live" if prices_live else "census"
        self._render_state()

    def _tick_overlays(self) -> None:
        # Re-attach current overlay values without re-fetching from eToro.
        # prev_close is intentionally NOT refreshed here — it requires the
        # current FX from live rates (only available in _tick_etoro). It will
        # update on the next _tick_etoro cycle (every 5s).
        if self._state.account is None:
            return
        fundamentals = self._signals.fundamentals()
        census = self._census.read()
        new_positions = tuple(
            replace(p, **_overlay_fields(
                p.symbol, fundamentals.get(p.symbol), census,
            ))
            for p in self._state.positions
        )
        self._state = AppState(
            account=self._state.account, positions=new_positions,
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
        equity_now = self._state.account.equity if self._state.account else 0.0
        if self._state.account is not None:
            header.open_pnl = self._state.account.unrealized
            if self._opening_equity_today is not None:
                delta = self._state.account.equity - self._opening_equity_today
                pct = (delta / self._opening_equity_today * 100
                       if self._opening_equity_today else 0)
                header.today_delta = (delta, pct)
                header.today_baseline_known = True
            else:
                header.today_baseline_known = False
        # Push positions + equity to widgets that need both for context.
        table = self.query_one(PositionsTable)
        table.equity = equity_now
        table.positions = self._state.positions
        footer = self.query_one(Footer)
        footer.last_error = self._state.last_error

    def _bootstrap_today_baseline(self) -> Optional[float]:
        """Return a 'reference equity' for today's Δ from snapshot history.

        Strategy: oldest snapshot in the trailing 24h. This approximates
        'yesterday's close' continuously and survives sessions. Returns None
        if there's no snapshot history yet (first run).
        """
        if self._db is None:
            return None
        row = self._db.execute(
            "SELECT equity FROM equity_snapshots "
            "WHERE ts > datetime('now', '-24 hours') "
            "ORDER BY ts ASC LIMIT 1"
        ).fetchone()
        return float(row[0]) if row else None

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

    def action_help(self) -> None:
        try:
            source = config.get_credentials_source()
        except Exception:
            source = "unknown"
        # Census mtime: read newest matching file on disk.
        census_mtime: float | None = None
        try:
            files = sorted(config.CENSUS_GLOB_DIR.glob(config.CENSUS_GLOB_PATTERN))
            if files:
                census_mtime = files[-1].stat().st_mtime
        except OSError:
            pass
        self.push_screen(HelpModal(
            auth_source=source,
            snapshot_db=str(config.SNAPSHOT_DB_PATH),
            signals_mtime=self._signals.mtime(),
            census_mtime=census_mtime,
        ))

    # ------- messages -------

    def on_positions_table_sort_changed(
        self, message: PositionsTable.SortChanged
    ) -> None:
        self.query_one(Footer).sort_label = SORT_LABELS.get(message.key, str(message.key))

    # NOTE: PositionsTable.PositionSelected message is no longer consumed —
    # the per-row dossier panel was removed. The message is still emitted by
    # the table on row highlight; we just don't act on it. Left in place in
    # case a future hover/popup feature wants it.
