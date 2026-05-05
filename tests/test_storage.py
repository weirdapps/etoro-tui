from datetime import datetime, timedelta, timezone
from pathlib import Path

from etoro_tui import storage
from etoro_tui.models import AccountSummary, Position


def _account(equity: float = 50000.0) -> AccountSummary:
    return AccountSummary(
        equity=equity, cash=10000.0, unrealized=500.0, realized=1500.0,
        fetched_at=datetime.now(timezone.utc),
    )


def _position(symbol: str = "AAPL", current: float = 160.0) -> Position:
    return Position(
        position_id=1, symbol=symbol, direction="Buy", units=10.0,
        open_rate=150.0, current_rate=current, value=current * 10,
        pnl=(current - 150) * 10, pnl_pct=(current - 150) / 150 * 100,
        open_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_init_db_creates_tables(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "equity_snapshots" in tables
    assert "position_snapshots" in tables
    conn.close()


def test_init_db_idempotent(tmp_path: Path):
    db = tmp_path / "snap.db"
    storage.init_db(db).close()
    # second call must not raise
    conn = storage.init_db(db)
    conn.close()


def test_write_and_read_equity_sparkline(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    for eq in [50000.0, 50100.0, 50200.0]:
        storage.write_snapshot(conn, _account(eq), [_position()])
    spark = storage.read_equity_sparkline(conn, hours=24, max_points=80)
    assert len(spark) == 3
    assert spark[-1] == 50200.0


def test_sparkline_downsamples(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    # Insert 200 snapshots, each 1 minute apart
    base = datetime.now(timezone.utc) - timedelta(hours=4)
    for i in range(200):
        ts = (base + timedelta(minutes=i)).isoformat()
        conn.execute(
            "INSERT INTO equity_snapshots VALUES (?, ?, ?, ?, ?)",
            (ts, 50000.0 + i, 10000.0, 0.0, 0.0),
        )
    conn.commit()
    spark = storage.read_equity_sparkline(conn, hours=24, max_points=50)
    assert len(spark) == 50
    # First and last should still represent the range
    assert spark[0] == 50000.0
    assert spark[-1] == 50199.0


def test_write_snapshot_does_not_raise_on_empty_positions(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    storage.write_snapshot(conn, _account(), [])  # no positions
    # equity row written, no position rows
    eq_count = conn.execute("SELECT COUNT(*) FROM equity_snapshots").fetchone()[0]
    pos_count = conn.execute("SELECT COUNT(*) FROM position_snapshots").fetchone()[0]
    assert eq_count == 1
    assert pos_count == 0


def test_downsample_returns_input_when_fewer_than_max():
    """Early-return branch: no downsampling needed."""
    from etoro_tui.storage import _downsample
    assert _downsample([1.0, 2.0, 3.0], 10) == (1.0, 2.0, 3.0)


def test_downsample_returns_input_when_exactly_max():
    """Boundary: equal length is not downsampled."""
    from etoro_tui.storage import _downsample
    values = [float(i) for i in range(10)]
    assert _downsample(values, 10) == tuple(values)
