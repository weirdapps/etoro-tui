"""Frozen dataclasses representing application state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


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
    value: float           # units * current_rate
    pnl: float             # eToro 'profit'
    pnl_pct: float         # eToro 'profitPercentage'
    open_ts: datetime
    # overlays — None means unavailable
    signal: Optional[Signal] = None        # I (inconclusive) → None
    pi_pct: Optional[float] = None         # 0.0–100.0
    news_24h: Optional[int] = None
    news_anomaly: bool = False             # True when count > 1.5 × 7d avg
    position_count: int = 1                # >1 when this row aggregates several raw positions
    # Fundamentals (etorotrade CSV, daily refresh; None for ETFs/crypto/illiquid):
    pe_trailing: Optional[float] = None    # trailing 12m P/E
    pe_forward: Optional[float] = None     # forward 12m P/E
    upside_pct: Optional[float] = None     # analyst target price implied % upside
    analyst_buy_pct: Optional[float] = None  # % of analyst recommendations = Buy
    target_price: Optional[float] = None   # consensus target price (issuer currency)


@dataclass(frozen=True)
class AccountSummary:
    equity: float
    cash: float            # availableBalance
    unrealized: float      # totalProfit (open positions)
    realized: float        # realizedProfit (closed)
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
class ActionsSummary:
    """Buckets of portfolio actions inferred from etorotrade signals + holdings.

    buy   — top etorotrade BUY signals NOT held (new ideas, by upside)
    add   — currently held positions with BUY signal (build up)
    hold  — currently held positions with HOLD signal (steady)
    trim  — currently held with SELL signal AND <3% of equity (small concern)
    sell  — currently held with SELL signal AND ≥3% of equity (urgent)
    """
    buy: tuple[str, ...]
    add: tuple[str, ...]
    hold: tuple[str, ...]
    trim: tuple[str, ...]
    sell: tuple[str, ...]


@dataclass(frozen=True)
class AppState:
    account: Optional[AccountSummary]
    positions: tuple[Position, ...]
    last_error: Optional[str]
    status: Status
    equity_sparkline: tuple[float, ...]   # last 24h, downsampled to ≤80 points
