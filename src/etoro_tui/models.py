"""Frozen dataclasses representing application state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Signal = Literal["BUY", "SELL", "HOLD"]
Status = Literal["live", "degraded", "down"]
Direction = Literal["Buy", "Sell"]


@dataclass(frozen=True)
class Position:
    position_id: int
    symbol: str
    direction: Direction
    units: float
    open_rate: float
    current_rate: float
    value: float  # units * current_rate
    pnl: float  # eToro 'profit'
    pnl_pct: float  # eToro 'profitPercentage'
    open_ts: datetime
    # overlays — None means unavailable
    signal: Signal | None = None  # I (inconclusive) → None
    pi_pct: float | None = None  # 0.0–100.0
    position_count: int = 1  # >1 when this row aggregates several raw positions
    # Fundamentals (etorotrade CSV, daily refresh; None for ETFs/crypto/illiquid):
    pe_trailing: float | None = None  # trailing 12m P/E
    pe_forward: float | None = None  # forward 12m P/E
    upside_pct: float | None = None  # analyst target price implied % upside
    analyst_buy_pct: float | None = None  # % of analyst recommendations = Buy
    analyst_momentum: float | None = None  # Δ in buy% over 3 months (etorotrade AM)
    target_price: float | None = None  # consensus target price (issuer currency)
    # Yesterday's close (census priceData.currentPrice) — used for the Δday
    # column. None when the symbol is not in the census file. Stored in the
    # instrument's local listing currency, same as census.
    prev_close: float | None = None
    # Display fields for the Price column. The Price column shows the
    # listing-currency market quote (matches Yahoo / eToro web / issuer
    # pages) so a EUR-listed ETF doesn't read as a USD-converted number
    # nobody else publishes. Value/Profit columns stay USD (account
    # currency) so totals make sense. None → caller falls back to
    # current_rate / prev_close (which are USD).
    quote_price: float | None = None
    quote_prev: float | None = None
    currency: str = "USD"


@dataclass(frozen=True)
class AccountSummary:
    equity: float
    cash: float  # availableBalance
    unrealized: float  # totalProfit (open positions)
    realized: float  # realizedProfit (closed)
    fetched_at: datetime


@dataclass(frozen=True)
class IndexSummary:
    """One major index for the side-panel 'INDICES' block.

    `last`  = live price from /market-data/instruments/rates (lastExecution).
    `prev`  = census `currentPrice` (yesterday's close).
    `change_pct` = (last − prev) / prev × 100 — today's move.
    """

    name: str
    last: float
    change_pct: float


@dataclass(frozen=True)
class AppState:
    account: AccountSummary | None
    positions: tuple[Position, ...]
    last_error: str | None
    status: Status
    equity_sparkline: tuple[float, ...]  # last 24h, downsampled to ≤80 points
