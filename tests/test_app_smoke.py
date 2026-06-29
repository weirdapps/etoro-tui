# tests/test_app_smoke.py
from datetime import UTC, datetime

import pytest

from etoro_tui.app import EtoroTuiApp
from etoro_tui.models import AccountSummary, AppState, Position


def _make_state() -> AppState:
    pos = Position(
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
        signal="BUY",
        pi_pct=42.0,
    )
    acct = AccountSummary(
        equity=50000.0,
        cash=10000.0,
        unrealized=500.0,
        realized=1500.0,
        fetched_at=datetime.now(UTC),
    )
    return AppState(
        account=acct,
        positions=(pos,),
        last_error=None,
        status="live",
        equity_sparkline=(50000.0, 50100.0, 50000.0),
    )


@pytest.mark.asyncio
async def test_app_boots_with_injected_state():
    app = EtoroTuiApp(initial_state=_make_state(), disable_polling=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Header is two Statics (#hdr-left + #hdr-right). Equity sits in left.
        left = app.query_one("#hdr-left")
        assert "50,000" in str(left.render())


@pytest.mark.asyncio
async def test_footer_shows_asset_count_not_lot_count():
    """The footer reports distinct instruments (one row per symbol), NOT eToro
    lots. A 2-symbol portfolio where AAPL aggregates 3 lots still reads
    '2 assets'."""

    def _pos(symbol: str, lots: int, pid: int) -> Position:
        return Position(
            position_id=pid,
            symbol=symbol,
            direction="Buy",
            units=10.0,
            open_rate=150.0,
            current_rate=160.0,
            value=1600.0,
            pnl=100.0,
            pnl_pct=6.67,
            open_ts=datetime(2026, 1, 1, tzinfo=UTC),
            position_count=lots,
        )

    state = AppState(
        account=AccountSummary(
            equity=50000.0,
            cash=10000.0,
            unrealized=500.0,
            realized=1500.0,
            fetched_at=datetime.now(UTC),
        ),
        positions=(_pos("AAPL", lots=3, pid=1), _pos("MSFT", lots=1, pid=2)),
        last_error=None,
        status="live",
        equity_sparkline=(),
    )
    app = EtoroTuiApp(initial_state=state, disable_polling=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "2 assets" in str(app.query_one("#footer-assets").render())


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


@pytest.mark.asyncio
async def test_footer_prices_source_ws_label_is_green():
    app = EtoroTuiApp(initial_state=_make_state(), disable_polling=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        footer = app.query_one("Footer")
        footer.prices_source = "live (ws)"
        await pilot.pause()
        text = str(app.query_one("#footer-prices").render())
        # The "●" bullet is added only by the green live/census branches, never
        # the dim "unknown" else-branch — so it proves "live (ws)" is recognised
        # as a live source rather than rendered as an unknown literal.
        assert "● live (ws)" in text
