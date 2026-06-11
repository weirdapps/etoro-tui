"""Demo-mode synthetic data for `etoro-tui --demo`.

Lets people preview the UI without generating eToro API keys. Builds a
realistic 8-position portfolio + index quotes locally; no network calls.

Use:
    from etoro_tui.demo import build_demo_state
    state = build_demo_state()
"""

from __future__ import annotations

from datetime import UTC, datetime

from .models import (
    AccountSummary,
    AppState,
    IndexSummary,
    Position,
)


def _pos(
    pid: int,
    sym: str,
    units: float,
    open_rate: float,
    current: float,
    *,
    signal=None,
    pi_pct=None,
    pe_t=None,
    pe_f=None,
    upside=None,
    buy_pct=None,
    buy_mom=None,
    lots: int = 1,
    day_chg_pct: float = 0.0,
) -> Position:
    value = units * current
    pnl = (current - open_rate) * units
    pnl_pct = (current - open_rate) / open_rate * 100 if open_rate else 0.0
    # Synthesise yesterday's close from the desired Δday so demo Δday cells
    # render with realistic mixed greens/reds.
    prev_close = current / (1 + day_chg_pct / 100) if day_chg_pct != 0 else current
    return Position(
        position_id=pid,
        symbol=sym,
        direction="Buy",
        units=units,
        open_rate=open_rate,
        current_rate=current,
        value=value,
        pnl=pnl,
        pnl_pct=pnl_pct,
        open_ts=datetime(2025, 6, 1, tzinfo=UTC),
        signal=signal,
        pi_pct=pi_pct,
        position_count=lots,
        pe_trailing=pe_t,
        pe_forward=pe_f,
        upside_pct=upside,
        analyst_buy_pct=buy_pct,
        analyst_momentum=buy_mom,
        target_price=None,
        prev_close=prev_close,
    )


def build_demo_state() -> AppState:
    """8-position synthetic portfolio with realistic enough numbers."""
    positions = (
        _pos(
            1,
            "AAPL",
            150,
            180.00,
            195.40,
            signal="HOLD",
            pi_pct=22,
            pe_t=33.5,
            pe_f=29.0,
            upside=8.6,
            buy_pct=53,
            buy_mom=-1,
            lots=3,
            day_chg_pct=0.42,
        ),
        _pos(
            2,
            "NVDA",
            100,
            50.00,
            145.20,
            signal="BUY",
            pi_pct=35,
            pe_t=40.5,
            pe_f=17.7,
            upside=35.6,
            buy_pct=100,
            buy_mom=12,
            lots=5,
            day_chg_pct=2.81,
        ),
        _pos(
            3,
            "MSFT",
            80,
            380.00,
            410.50,
            signal="BUY",
            pi_pct=44,
            pe_t=24.6,
            pe_f=21.4,
            upside=35.6,
            buy_pct=96,
            buy_mom=5,
            lots=4,
            day_chg_pct=0.18,
        ),
        _pos(
            4,
            "GOOG",
            60,
            140.00,
            178.20,
            signal="HOLD",
            pi_pct=35,
            pe_t=29.0,
            pe_f=26.6,
            upside=3.9,
            buy_pct=100,
            buy_mom=0,
            lots=2,
            day_chg_pct=-0.34,
        ),
        _pos(
            5,
            "TSLA",
            40,
            220.00,
            198.80,
            signal="SELL",
            pi_pct=18,
            pe_t=72.4,
            pe_f=64.1,
            upside=-12.3,
            buy_pct=30,
            buy_mom=-8,
            lots=1,
            day_chg_pct=-3.12,
        ),
        _pos(
            6,
            "AMD",
            50,
            135.00,
            160.20,
            signal="BUY",
            pi_pct=20,
            pe_t=131.4,
            pe_f=30.4,
            upside=22.0,
            buy_pct=78,
            buy_mom=None,
            lots=2,
            day_chg_pct=1.55,
        ),
        _pos(
            7,
            "META",
            25,
            500.00,
            580.10,
            signal="BUY",
            pi_pct=35,
            pe_t=22.2,
            pe_f=16.9,
            upside=36.4,
            buy_pct=92,
            buy_mom=2,
            lots=2,
            day_chg_pct=0.91,
        ),
        _pos(
            8,
            "NKE",
            80,
            95.00,
            82.50,
            signal="SELL",
            pi_pct=11,
            pe_t=28.3,
            pe_f=23.3,
            upside=-5.2,
            buy_pct=48,
            buy_mom=-3,
            lots=1,
            day_chg_pct=-1.07,
        ),
    )
    invested = sum(p.value for p in positions)
    cash = 25_000.00
    equity = invested + cash
    unrealized = sum(p.pnl for p in positions)
    account = AccountSummary(
        equity=equity,
        cash=cash,
        unrealized=unrealized,
        realized=0.0,
        fetched_at=datetime.now(UTC),
    )
    return AppState(
        account=account,
        positions=positions,
        last_error=None,
        status="live",
        equity_sparkline=tuple(equity + i * 50 for i in range(20)),
    )


def build_demo_indices() -> tuple[IndexSummary, ...]:
    # Mirrors config.DEFAULT_INDICES (US + Europe). The header auto-fits as many
    # as the terminal width allows, always keeping the first three.
    return (
        IndexSummary(name="S&P 500", last=5_432.10, change_pct=0.34),
        IndexSummary(name="Dow 30", last=40_123.45, change_pct=-0.21),
        IndexSummary(name="NASDAQ", last=17_234.52, change_pct=0.45),
        IndexSummary(name="DAX", last=18_412.30, change_pct=0.27),
        IndexSummary(name="FTSE 100", last=8_204.55, change_pct=0.11),
        IndexSummary(name="EuroStx50", last=5_017.83, change_pct=0.18),
    )
