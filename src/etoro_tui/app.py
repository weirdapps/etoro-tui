# src/etoro_tui/app.py
"""EtoroTuiApp — the Textual application that owns AppState and timers."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import TypedDict

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.timer import Timer

from . import config, storage
from .clients.census import CensusReader, InstrumentInfo
from .clients.etoro import (
    EtoroAuthError,
    EtoroClient,
    EtoroTransientError,
)
from .clients.price_stream import EtoroPriceStream
from .clients.signals import Fundamentals, SignalsReader
from .clients.yahoo import YahooClient
from .models import (
    AccountSummary,
    AppState,
    IndexSummary,
    Position,
    Signal,
    Status,
)
from .widgets.footer import Footer
from .widgets.header import Header
from .widgets.help_modal import HelpModal
from .widgets.positions_table import SORT_LABELS, PositionsTable

log = logging.getLogger(__name__)

_CSV_MAP_CACHE: dict[int, str] | None = None


def _load_portfolio_csv_map() -> dict[int, str]:
    """Load instrumentId→symbol from etorotrade portfolio.csv (static fallback)."""
    global _CSV_MAP_CACHE  # noqa: PLW0603
    if _CSV_MAP_CACHE is not None:
        return _CSV_MAP_CACHE
    import csv

    mapping: dict[int, str] = {}
    path = config.PORTFOLIO_CSV
    if path.exists():
        with path.open() as f:
            for row in csv.DictReader(f):
                iid = row.get("instrumentId", "").strip()
                sym = row.get("symbol", "").strip()
                if iid and sym:
                    try:
                        mapping[int(iid)] = sym
                    except ValueError:
                        pass
    _CSV_MAP_CACHE = mapping
    return mapping


class _OverlayKwargs(TypedDict):
    """Typed kwargs for the overlay fields on Position. Mirrors the field
    names exactly so `Position(..., **_overlay_fields(...))` typechecks.
    """

    signal: Signal | None
    pi_pct: float | None
    pe_trailing: float | None
    pe_forward: float | None
    upside_pct: float | None
    analyst_buy_pct: float | None
    analyst_momentum: float | None
    target_price: float | None


# Symbol-suffix → listing currency. Census doesn't expose currency; the
# eToro suffix is the next-most-reliable signal. London (.L) defaults to
# GBp because the vast majority of LSE equities (incl. user holding PRU.L)
# quote in pence; .L instruments in GBP would render with a GBp tag and
# look 100× too large — a known edge case worth handling if it surfaces.
_SUFFIX_CCY: dict[str, str] = {
    "DE": "EUR",
    "PA": "EUR",
    "AS": "EUR",
    "MI": "EUR",
    "MC": "EUR",
    "BR": "EUR",
    "VI": "EUR",
    "HE": "EUR",
    "LS": "EUR",
    "IR": "EUR",
    "L": "GBp",
    "HK": "HKD",
    "CO": "DKK",
    "ST": "SEK",
    "OL": "NOK",
    "SW": "CHF",
    "T": "JPY",
    "AX": "AUD",
    "TO": "CAD",
    "MX": "MXN",
}


def _currency_for(symbol: str, ocr: float) -> str:
    """Listing-currency code for the Price column tag.

    `ocr ≈ 1.0` → USD (covers US equities and crypto, both quoted in USD).
    Otherwise the suffix after the last '.' is looked up; unknown suffixes
    return "" so the Price column omits the tag rather than misleading.
    """
    if abs(ocr - 1.0) < 0.001:
        return "USD"
    if "." in symbol:
        return _SUFFIX_CCY.get(symbol.rsplit(".", 1)[-1].upper(), "")
    return ""


def _build_indices(
    specs: Sequence[tuple[str, str]],
    quotes: dict[str, tuple[float, float]],
) -> tuple[IndexSummary, ...]:
    """Build the header's index summaries from Yahoo quotes.

    `specs`  = configured (display_name, eToro_symbol) pairs, in priority order
               (config.get_indices()).
    `quotes` = {eToro_symbol_upper: (last, prev_close)} from
               YahooClient.fetch_index_quotes.

    Indices are priced straight from Yahoo, NOT the eToro popular-investor
    census. The census only contains instruments PIs actually hold, so CFD
    index codes (SPX500, DJ30, …) silently dropped out of it and the bar lost
    S&P/Dow — see git history. Yahoo is the canonical source for ^GSPC/^DJI/…,
    so standard indices now always render. Output preserves spec order so the
    header can show the first N that fit; a symbol Yahoo can't price is omitted
    rather than shown as a flat zero.

    The level is the index's native points value (S&P in index points, DAX in
    points, etc.) — what every external reference quotes — not an FX-converted
    number.
    """
    out: list[IndexSummary] = []
    for name, sym in specs:
        quote = quotes.get(sym.upper())
        if quote is None:
            continue
        last, prev = quote
        if last <= 0:
            continue
        change_pct = ((last - prev) / prev * 100) if prev > 0 else 0.0
        out.append(IndexSummary(name=name, last=last, change_pct=change_pct))
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
        "analyst_momentum": fund.analyst_momentum if fund else None,
        "target_price": fund.target_price if fund else None,
    }


def _extract_live_price(inst_id: int, rates: dict[int, dict] | None) -> tuple[float, float] | None:
    """Return (local_price, ocr) from the live rates endpoint, or None."""
    live = (rates or {}).get(inst_id)
    if live is None:
        return None
    for key in ("lastExecution", "Bid", "bid"):
        val = live.get(key)
        if val is None:
            continue
        try:
            candidate = float(val)
        except (TypeError, ValueError):
            continue
        if candidate > 0:
            return (candidate, float(live.get("conversionRateAsk", 1.0)))
    return None


def _to_position(
    raw: dict,
    instruments: dict[int, InstrumentInfo],
    fundamentals: dict[str, Fundamentals],
    pi_pct: dict,
    rates: dict[int, dict] | None = None,
    yahoo_prev: dict[str, float] | None = None,
    instrument_overrides: dict[int, str] | None = None,
) -> Position | None:
    """Build a Position from a raw eToro position record.

    When the instrumentID is missing from census, the position is still
    rendered using live rates (value/P&L) and a placeholder symbol (#ID)
    unless the user has mapped the ID to a ticker via [instruments.map]
    in config.toml. Fundamentals and Δday show "—" for unmapped
    instruments. Returns None only when we can't compute any price at all.
    """
    inst_id = raw["instrumentID"]
    info = instruments.get(inst_id)
    overrides = instrument_overrides or {}

    # Resolve symbol: census → config override → placeholder
    if info is not None:
        sym = info.symbol.upper()
    elif inst_id in overrides:
        sym = overrides[inst_id].upper()
    else:
        sym = f"#{inst_id}"

    units = float(raw["units"])
    open_ocr = float(raw.get("openConversionRate", 1.0))
    local_open = float(raw["openRate"])
    open_rate = local_open * open_ocr

    live_price_fx = _extract_live_price(inst_id, rates)

    if live_price_fx is not None:
        local_now, current_ocr = live_price_fx
        current_rate = local_now * current_ocr
    elif info is not None:
        current_ocr = open_ocr
        local_now = float(info.current_price) if info.current_price else 0.0
        current_rate = local_now * open_ocr
    else:
        # No census, no live rates — use open rate as best estimate.
        current_ocr = open_ocr
        local_now = local_open
        current_rate = open_rate

    local_prev: float | None = None
    if yahoo_prev is not None:
        yp = yahoo_prev.get(sym)
        if yp is not None and yp > 0:
            local_prev = yp
    if local_prev is None and info is not None and info.current_price:
        local_prev = float(info.current_price)
    prev_close = local_prev * current_ocr if local_prev else None
    is_buy = bool(raw["isBuy"])
    direction_sign = 1 if is_buy else -1
    value = current_rate * units
    pnl = (current_rate - open_rate) * units * direction_sign
    pnl_pct = (current_rate - open_rate) / open_rate * 100 * direction_sign if open_rate else 0.0
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
        quote_price=local_now if local_now > 0 else None,
        quote_prev=local_prev,
        currency=_currency_for(sym, current_ocr),
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
        cost = sum(p.units * p.open_rate for p in ps)  # USD invested
        value = sum(p.value for p in ps)
        pnl = sum(p.pnl for p in ps)
        avg_open = cost / units if units else first.open_rate
        avg_curr = value / units if units else first.current_rate
        pnl_pct = (pnl / cost * 100) if cost else 0.0
        oldest = min(p.open_ts for p in ps)
        out.append(
            Position(
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
                analyst_momentum=first.analyst_momentum,
                target_price=first.target_price,
                prev_close=first.prev_close,
                quote_price=first.quote_price,
                quote_prev=first.quote_prev,
                currency=first.currency,
            )
        )
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
        fetched_at=datetime.now(UTC),
    )


def _previous_close_equity(
    positions: Iterable[Position],
    cash: float,
    now: datetime,
) -> float:
    """Total equity as of the previous trading day's close — the baseline for
    today's Δ that matches eToro's daily P&L.

    Mirrors the SPX side-panel approach: per-instrument reference is census
    `currentPrice` (refreshed daily at ~00:00 UTC, so it IS the previous
    trading session's close through the whole UTC day).

    Per-position ref_rate:
      - open_rate if opened today (UTC) — the position didn't exist yesterday,
        so its contribution to today's delta is the post-open price move only
      - prev_close otherwise — yesterday's close in USD (same source SPX uses)
      - current_rate as last resort if prev_close is None — that position
        contributes 0 to the delta (conservative)

    Cash is added unchanged. Same-day deposits/withdrawals cancel out
    between equity_now and this baseline → delta is pure price movement.
    """
    today_utc = now.astimezone(UTC).date()
    total = cash
    for p in positions:
        if p.open_ts.astimezone(UTC).date() == today_utc:
            ref = p.open_rate
        elif p.prev_close is not None:
            ref = p.prev_close
        else:
            ref = p.current_rate
        total += p.units * ref
    return total


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
        initial_state: AppState | None = None,
        disable_polling: bool = False,
        etoro_client: EtoroClient | None = None,
        price_stream: EtoroPriceStream | None = None,
    ) -> None:
        super().__init__()
        self._state: AppState = initial_state or AppState(
            account=None,
            positions=(),
            last_error=None,
            status="live",
            equity_sparkline=(),
        )
        self._disable_polling = disable_polling
        self._etoro_client = etoro_client
        self._price_stream = price_stream
        self._signals = SignalsReader(config.SIGNALS_CSV)
        self._census = CensusReader(config.CENSUS_GLOB_DIR, config.CENSUS_GLOB_PATTERN)
        self._yahoo = YahooClient(ttl_seconds=1800)
        self._db: sqlite3.Connection | None = None
        self._fetch_task: asyncio.Task[None] | None = None
        self._etoro_timer: Timer | None = None
        self._render_timer: Timer | None = None
        self._market_open: bool = config.is_market_active()
        # Render-input cache: _tick_portfolio (slow REST) fills these; _tick_render
        # (fast) rebuilds positions from them + the live WS store.
        self._raw_positions: list[dict] = []
        self._credit: float = 0.0
        self._instruments: dict[int, InstrumentInfo] = {}
        self._fundamentals: dict[str, Fundamentals] = {}
        self._pi_pct: dict = {}
        self._yahoo_prev: dict[str, float] = {}
        self._inst_overrides: dict[int, str] = {}
        self._rest_rates: dict[int, dict] = {}
        self._api_symbol_cache: dict[int, str] = {}
        self._spark: tuple[float, ...] = ()
        self._prices_source: str = "—"
        self._have_portfolio: bool = False

    # ------- composition -------

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        with Horizontal(id="main"):
            yield PositionsTable(id="table")
        yield Footer(id="footer")

    async def on_mount(self) -> None:
        self._db = storage.init_db(config.SNAPSHOT_DB_PATH)
        storage.prune_old_snapshots(self._db)
        self._render_state()
        # Demo mode: __main__.py attaches synthetic indices before run().
        if hasattr(self, "_demo_indices"):
            self.query_one(Header).indices = self._demo_indices
        if self._disable_polling:
            return
        # Credentials drive both the REST client and the WS price stream.
        if self._etoro_client is None or (self._price_stream is None and config.WS_ENABLED):
            try:
                pk, uk = config.get_credentials()
            except config.AuthMissingError as e:
                self._set_error(str(e), "down")
                return
            if self._etoro_client is None:
                self._etoro_client = EtoroClient(public_key=pk, user_key=uk)
            if self._price_stream is None and config.WS_ENABLED:
                self._price_stream = EtoroPriceStream(public_key=pk, user_key=uk)
        if self._price_stream is not None:
            await self._price_stream.start()
        poll_s = config.POLL_PORTFOLIO_S if self._market_open else config.POLL_PORTFOLIO_IDLE_S
        self._etoro_timer = self.set_interval(poll_s, self._tick_portfolio)
        if self._price_stream is not None:
            self._render_timer = self.set_interval(config.RENDER_S, self._tick_render)
        self.set_interval(config.POLL_SIGNALS_S, self._tick_overlays)
        self.set_interval(config.SNAPSHOT_S, self._tick_snapshot)
        self.set_interval(1.0, self._tick_footer_clock)
        # Fire first fetch as background task so the UI renders immediately.
        self._fetch_task = asyncio.create_task(self._tick_portfolio())

    async def on_unmount(self) -> None:
        # Cancel any in-flight fetch (especially the yfinance to_thread) so
        # the event loop doesn't block waiting for it on shutdown.
        if self._fetch_task is not None and not self._fetch_task.done():
            self._fetch_task.cancel()
        if self._price_stream is not None:
            await self._price_stream.aclose()
        if self._etoro_client is not None:
            await self._etoro_client.aclose()
        if self._db is not None:
            self._db.close()

    # ------- timers -------

    def _current_rates(self) -> dict[int, dict]:
        """Live WS rates merged over the REST fallback (WS wins per instrument)."""
        ws = self._price_stream.latest() if self._price_stream is not None else {}
        if ws:
            merged = dict(self._rest_rates)
            merged.update(ws)
            return merged
        return self._rest_rates

    def _rerender_positions(self) -> None:
        """Rebuild Positions from cached portfolio + enrichment + current rates.

        Called by both _tick_portfolio (after a REST refresh) and _tick_render
        (fast, every RENDER_S) so the two paths can never drift. No network.
        """
        if not self._have_portfolio:
            return
        rates = self._current_rates()
        positions_list: list[Position] = []
        for raw in self._raw_positions:
            built = _to_position(
                raw,
                self._instruments,
                self._fundamentals,
                self._pi_pct,
                rates,
                self._yahoo_prev,
                self._inst_overrides,
            )
            if built is not None:
                positions_list.append(built)

        # Aggregate by symbol — eToro splits a holding into many lots; the
        # user wants one row per ticker with a Pos column showing lot count.
        positions = _aggregate_by_symbol(positions_list)
        acct = _account_from(positions, self._credit)

        # live when we have any rates (ws or rest); degraded on census fallback.
        status: Status = "live" if rates else "degraded"
        self._state = AppState(
            account=acct,
            positions=positions,
            last_error=None,
            status=status,
            equity_sparkline=self._spark,
        )
        footer = self.query_one(Footer)
        footer.prices_source = self._prices_source
        footer.census_stale = self._census.is_stale
        self._render_state()

    async def _tick_portfolio(self) -> None:
        # Track ourselves so on_unmount can cancel an in-flight fetch.
        self._fetch_task = asyncio.current_task()
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

        self._raw_positions = portfolio.get("positions", [])
        self._credit = float(portfolio.get("credit", 0.0))
        self._instruments = self._census.instruments()
        unique_ids = sorted({raw["instrumentID"] for raw in self._raw_positions})

        # Fill gaps: instrument IDs not in census → resolve via live API, cache result
        missing_ids = [
            iid
            for iid in unique_ids
            if iid not in self._instruments and iid not in self._api_symbol_cache
        ]
        if missing_ids:
            try:
                api_syms = await self._etoro_client.fetch_instrument_symbols(missing_ids)
                self._api_symbol_cache.update(api_syms)
            except Exception as e:
                log.warning("instrument symbol fetch failed: %s", e)
        # Merge cached API symbols into instruments (without price — that comes from rates)
        for iid, sym in self._api_symbol_cache.items():
            if iid not in self._instruments:
                self._instruments[iid] = InstrumentInfo(symbol=sym, current_price=0.0)
        # Final fallback: portfolio.csv static map
        csv_map = _load_portfolio_csv_map()
        for iid, sym in csv_map.items():
            if iid not in self._instruments:
                self._instruments[iid] = InstrumentInfo(symbol=sym, current_price=0.0)

        # Reconcile WS subscriptions to exactly what we hold.
        if self._price_stream is not None and unique_ids:
            await self._price_stream.set_instruments(set(unique_ids))

        # Choose the price source. The WS stream is authoritative when connected
        # AND it already has ticks for us; otherwise fall back to the REST rates
        # endpoint, then to census (handled downstream in _to_position).
        ws_live = (
            self._price_stream is not None
            and self._price_stream.is_connected()
            and bool(self._price_stream.latest())
        )
        if ws_live:
            self._rest_rates = {}
            self._prices_source = "live (ws)"
        elif unique_ids:
            try:
                self._rest_rates = await self._etoro_client.fetch_rates(unique_ids)
            except EtoroAuthError as e:
                self._set_error(f"auth failed (rates): {e}", "down")
                return
            except EtoroTransientError as e:
                # Don't block the whole tick on a transient rates failure;
                # just note it and let positions render with census prices.
                log.warning("rates fetch failed, using census fallback: %s", e)
                self._rest_rates = {}
            self._prices_source = "live (rest)" if self._rest_rates else "census"
        else:
            self._rest_rates = {}
            self._prices_source = "census"

        self._fundamentals = self._signals.fundamentals()
        self._pi_pct = self._census.read()
        self._inst_overrides = config.get_instrument_overrides()

        # Yahoo previous-closes for everything we hold (indices are fetched
        # separately). Include config-overridden symbols so they get Δday too.
        all_syms_set: set[str] = set()
        for iid in unique_ids:
            if iid in self._instruments:
                all_syms_set.add(self._instruments[iid].symbol)
            elif iid in self._inst_overrides:
                all_syms_set.add(self._inst_overrides[iid])
        try:
            self._yahoo_prev = await self._yahoo.fetch_prev_closes(sorted(all_syms_set))
        except Exception as e:  # noqa: BLE001 — yfinance throws diverse exceptions
            log.warning("yahoo fetch failed, using census fallback: %s", e)
            self._yahoo_prev = {}

        if self._db is not None:
            # Last 4 hours @ 1-min cadence = ~240 points downsampled to width.
            # Short window keeps any pre-fix-era polluted snapshots from
            # dominating the min-max scale and producing a single solid bar.
            self._spark = storage.read_equity_sparkline(self._db, hours=4, max_points=24)

        # Indices feed the header bar — priced from Yahoo (NOT the census), so
        # standard market indices always render regardless of whether a popular
        # investor happens to hold a CFD on them. The client guards its own
        # network/parse failures and returns whatever it has.
        index_specs = config.get_indices()
        index_quotes = await self._yahoo.fetch_index_quotes([sym for _, sym in index_specs])
        self.query_one(Header).indices = _build_indices(index_specs, index_quotes)

        self._have_portfolio = True
        self._rerender_positions()
        self._adjust_poll_interval()

    def _tick_render(self) -> None:
        # Fast path: repaint P&L from the live WS store with no network. Cached
        # enrichment from the last _tick_portfolio is reused.
        self._rerender_positions()

    def _adjust_poll_interval(self) -> None:
        """Swap the eToro timer when the market opens or closes."""
        now_open = config.is_market_active()
        if now_open == self._market_open:
            return
        self._market_open = now_open
        new_s = config.POLL_PORTFOLIO_S if now_open else config.POLL_PORTFOLIO_IDLE_S
        if self._etoro_timer is not None:
            self._etoro_timer.stop()
        self._etoro_timer = self.set_interval(new_s, self._tick_portfolio)
        tag = "market open" if now_open else "market closed"
        log.info("poll interval → %ss (%s)", new_s, tag)

    def _tick_overlays(self) -> None:
        # Re-attach current overlay values without re-fetching from eToro.
        # prev_close is intentionally NOT refreshed here — it requires the
        # current FX from live rates AND the Yahoo prev-close fetch (both only
        # happen in _tick_etoro). It will update on the next _tick_etoro cycle.
        if self._state.account is None:
            return
        fundamentals = self._signals.fundamentals()
        census = self._census.read()
        new_positions = tuple(
            replace(
                p,
                **_overlay_fields(
                    p.symbol,
                    fundamentals.get(p.symbol),
                    census,
                ),
            )
            for p in self._state.positions
        )
        self._state = AppState(
            account=self._state.account,
            positions=new_positions,
            last_error=self._state.last_error,
            status=self._state.status,
            equity_sparkline=self._state.equity_sparkline,
        )
        self._render_state()

    def _tick_snapshot(self) -> None:
        if self._db is None or self._state.account is None:
            return
        try:
            storage.write_snapshot(self._db, self._state.account)
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
            baseline = _previous_close_equity(
                self._state.positions,
                self._state.account.cash,
                datetime.now(UTC),
            )
            if baseline > 0:
                delta = self._state.account.equity - baseline
                pct = delta / baseline * 100
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
        # Distinct instruments held (one row per symbol), not eToro lots.
        footer.asset_count = len(self._state.positions)

    def _set_error(self, msg: str, status: Status) -> None:
        self._state = AppState(
            account=self._state.account,
            positions=self._state.positions,
            last_error=msg,
            status=status,
            equity_sparkline=self._state.equity_sparkline,
        )
        self._render_state()

    # ------- actions -------

    async def action_refresh(self) -> None:
        await self._tick_portfolio()

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
        self.push_screen(
            HelpModal(
                auth_source=source,
                snapshot_db=str(config.SNAPSHOT_DB_PATH),
                signals_mtime=self._signals.mtime(),
                census_mtime=census_mtime,
            )
        )

    # ------- messages -------

    def on_positions_table_sort_changed(self, message: PositionsTable.SortChanged) -> None:
        self.query_one(Footer).sort_label = SORT_LABELS.get(message.key, str(message.key))

    # NOTE: PositionsTable.PositionSelected message is no longer consumed —
    # the per-row dossier panel was removed. The message is still emitted by
    # the table on row highlight; we just don't act on it. Left in place in
    # case a future hover/popup feature wants it.
