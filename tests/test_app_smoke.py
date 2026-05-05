# tests/test_app_smoke.py
from datetime import datetime, timezone

import pytest

from etoro_tui.app import EtoroTuiApp
from etoro_tui.models import AccountSummary, AppState, Position


def _make_state() -> AppState:
    pos = Position(
        position_id=1, symbol="AAPL", direction="Buy", units=10.0,
        open_rate=150.0, current_rate=160.0, value=1600.0,
        pnl=100.0, pnl_pct=6.67,
        open_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        signal="BUY", pi_pct=42.0, news_24h=3,
    )
    acct = AccountSummary(
        equity=50000.0, cash=10000.0, unrealized=500.0, realized=1500.0,
        fetched_at=datetime.now(timezone.utc),
    )
    return AppState(
        account=acct, positions=(pos,), last_error=None,
        status="live", equity_sparkline=(50000.0, 50100.0, 50000.0),
    )


@pytest.mark.asyncio
async def test_app_boots_with_injected_state():
    app = EtoroTuiApp(initial_state=_make_state(), disable_polling=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Header should reflect the equity
        header = app.query_one("#hdr-equity")
        assert "50,000" in str(header.render())


@pytest.mark.asyncio
async def test_quit_key_exits_cleanly():
    app = EtoroTuiApp(initial_state=_make_state(), disable_polling=True)
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
    # No assertion — passing means clean exit


@pytest.mark.asyncio
async def test_sort_key_cycles():
    app = EtoroTuiApp(initial_state=_make_state(), disable_polling=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("PositionsTable")
        before = table.sort_key
        await pilot.press("s")
        await pilot.pause()
        await pilot.pause()  # Give reactive time to update
        assert table.sort_key != before
