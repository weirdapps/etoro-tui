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


@dataclass(frozen=True)
class AccountSummary:
    equity: float
    cash: float            # availableBalance
    unrealized: float      # totalProfit (open positions)
    realized: float        # realizedProfit (closed)
    fetched_at: datetime


@dataclass(frozen=True)
class AppState:
    account: Optional[AccountSummary]
    positions: tuple[Position, ...]
    last_error: Optional[str]
    status: Status
    equity_sparkline: tuple[float, ...]   # last 24h, downsampled to ≤80 points
