from datetime import UTC, datetime

import pytest

from etoro_tui.models import AccountSummary, AppState, Position


def test_position_immutable():
    p = Position(
        position_id=1,
        symbol="AAPL",
        direction="Buy",
        units=10.0,
        open_rate=150.0,
        current_rate=160.0,
        value=1600.0,
        pnl=100.0,
        pnl_pct=6.67,
        open_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises((AttributeError, TypeError)):  # frozen dataclass
        p.symbol = "MSFT"  # type: ignore[misc]


def test_position_overlay_defaults_none():
    p = Position(
        position_id=1,
        symbol="AAPL",
        direction="Buy",
        units=10.0,
        open_rate=150.0,
        current_rate=160.0,
        value=1600.0,
        pnl=100.0,
        pnl_pct=6.67,
        open_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert p.signal is None
    assert p.pi_pct is None
    assert p.prev_close is None  # Δday column shows "—" when missing


def test_account_summary_fields():
    a = AccountSummary(
        equity=50000.0,
        cash=10000.0,
        unrealized=500.0,
        realized=1500.0,
        fetched_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
    assert a.equity == 50000.0


def test_appstate_default_status():
    s = AppState(
        account=None,
        positions=(),
        last_error=None,
        status="live",
        equity_sparkline=(),
    )
    assert s.status == "live"
    assert s.positions == ()
