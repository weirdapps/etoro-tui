from datetime import UTC, datetime, timedelta
from pathlib import Path

from etoro_tui import storage
from etoro_tui.models import AccountSummary


def _account(equity: float = 50000.0) -> AccountSummary:
    return AccountSummary(
        equity=equity,
        cash=10000.0,
        unrealized=500.0,
        realized=1500.0,
        fetched_at=datetime.now(UTC),
    )


def test_init_db_creates_tables(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "equity_snapshots" in tables
    conn.close()


def test_init_db_idempotent(tmp_path: Path):
    db = tmp_path / "snap.db"
    storage.init_db(db).close()
    conn = storage.init_db(db)
    conn.close()


def test_write_and_read_equity_sparkline(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    for eq in [50000.0, 50100.0, 50200.0]:
        storage.write_snapshot(conn, _account(eq))
    spark = storage.read_equity_sparkline(conn, hours=24, max_points=80)
    assert len(spark) == 3
    assert spark[-1] == 50200.0


def test_sparkline_downsamples(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    base = datetime.now(UTC) - timedelta(hours=4)
    for i in range(200):
        ts = (base + timedelta(minutes=i)).isoformat()
        conn.execute(
            "INSERT INTO equity_snapshots VALUES (?, ?, ?, ?, ?)",
            (ts, 50000.0 + i, 10000.0, 0.0, 0.0),
        )
    conn.commit()
    spark = storage.read_equity_sparkline(conn, hours=24, max_points=50)
    assert len(spark) == 50
    assert spark[0] == 50000.0
    assert spark[-1] == 50199.0


def test_write_snapshot_equity_only(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    storage.write_snapshot(conn, _account())
    eq_count = conn.execute("SELECT COUNT(*) FROM equity_snapshots").fetchone()[0]
    assert eq_count == 1


def test_prune_old_snapshots(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    old_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    recent_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO equity_snapshots VALUES (?, ?, ?, ?, ?)", (old_ts, 50000, 10000, 0, 0)
    )
    conn.execute(
        "INSERT INTO equity_snapshots VALUES (?, ?, ?, ?, ?)", (recent_ts, 51000, 10000, 0, 0)
    )
    conn.commit()
    deleted = storage.prune_old_snapshots(conn)
    assert deleted == 1
    remaining = conn.execute("SELECT COUNT(*) FROM equity_snapshots").fetchone()[0]
    assert remaining == 1


def test_migrate_drops_position_snapshots(tmp_path: Path):
    db = tmp_path / "snap.db"
    conn = storage.init_db(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS position_snapshots (ts TEXT, position_id INTEGER, PRIMARY KEY (ts, position_id))"
    )
    conn.execute("INSERT INTO position_snapshots VALUES ('2026-01-01', 1)")
    conn.commit()
    conn.close()
    conn = storage.init_db(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "position_snapshots" not in tables
    conn.close()


def test_downsample_returns_input_when_fewer_than_max():
    from etoro_tui.storage import _downsample

    assert _downsample([1.0, 2.0, 3.0], 10) == (1.0, 2.0, 3.0)


def test_downsample_returns_input_when_exactly_max():
    from etoro_tui.storage import _downsample

    values = [float(i) for i in range(10)]
    assert _downsample(values, 10) == tuple(values)
