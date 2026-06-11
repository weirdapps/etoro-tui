"""SQLite snapshot persistence for sparklines."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import AccountSummary

_SCHEMA = """
CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts          TEXT PRIMARY KEY,
    equity      REAL NOT NULL,
    cash        REAL NOT NULL,
    unrealized  REAL NOT NULL,
    realized    REAL NOT NULL
);
"""

_RETENTION_DAYS = 7


def init_db(path: Path) -> sqlite3.Connection:
    """Open (or create) the snapshot DB and ensure schema. Idempotent.

    Tightens the DB file to 0o600 after creation — the file contains
    portfolio history (positions, equity, P&L) that should not be readable
    by other local users. No-op on Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    _migrate_drop_position_snapshots(conn)
    conn.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return conn


def _migrate_drop_position_snapshots(conn: sqlite3.Connection) -> None:
    """One-time migration: drop the defunct position_snapshots table and reclaim space."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "position_snapshots" not in tables:
        return
    conn.execute("DROP TABLE position_snapshots")
    conn.execute("VACUUM")
    import logging

    logging.getLogger(__name__).info("migrated: dropped position_snapshots + VACUUM")


def write_snapshot(
    conn: sqlite3.Connection,
    account: AccountSummary,
) -> None:
    """Insert one equity snapshot row."""
    ts = datetime.now(UTC).isoformat(timespec="microseconds")
    conn.execute(
        "INSERT OR REPLACE INTO equity_snapshots VALUES (?, ?, ?, ?, ?)",
        (ts, account.equity, account.cash, account.unrealized, account.realized),
    )
    conn.commit()


def _downsample(values: list[float], max_points: int) -> tuple[float, ...]:
    """Stride-sample to at most max_points, always preserving first and last."""
    if len(values) <= max_points:
        return tuple(values)
    stride = len(values) / max_points
    indexes = [int(i * stride) for i in range(max_points)]
    if indexes[-1] != len(values) - 1:
        indexes[-1] = len(values) - 1
    return tuple(values[i] for i in indexes)


def read_equity_sparkline(
    conn: sqlite3.Connection,
    hours: int = 24,
    max_points: int = 80,
) -> tuple[float, ...]:
    """Return equity time series (oldest → newest), downsampled."""
    rows = conn.execute(
        "SELECT equity FROM equity_snapshots WHERE ts > datetime('now', ?) ORDER BY ts",
        (f"-{hours} hours",),
    ).fetchall()
    return _downsample([r[0] for r in rows], max_points)


def prune_old_snapshots(conn: sqlite3.Connection) -> int:
    """Delete equity snapshots older than _RETENTION_DAYS. Returns rows deleted."""
    cur = conn.execute(
        "DELETE FROM equity_snapshots WHERE ts < datetime('now', ?)",
        (f"-{_RETENTION_DAYS} days",),
    )
    conn.commit()
    return cur.rowcount
