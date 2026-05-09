"""SQLite snapshot persistence for sparklines."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .models import AccountSummary, Position

_SCHEMA = """
CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts          TEXT PRIMARY KEY,
    equity      REAL NOT NULL,
    cash        REAL NOT NULL,
    unrealized  REAL NOT NULL,
    realized    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    ts            TEXT NOT NULL,
    position_id   INTEGER NOT NULL,
    symbol        TEXT NOT NULL,
    units         REAL NOT NULL,
    open_rate     REAL NOT NULL,
    current_rate  REAL NOT NULL,
    value         REAL NOT NULL,
    pnl           REAL NOT NULL,
    pnl_pct       REAL NOT NULL,
    PRIMARY KEY (ts, position_id)
);

CREATE INDEX IF NOT EXISTS idx_pos_symbol_ts
    ON position_snapshots(symbol, ts);
"""


def init_db(path: Path) -> sqlite3.Connection:
    """Open (or create) the snapshot DB and ensure schema. Idempotent.

    Tightens the DB file to 0o600 after creation — the file contains
    portfolio history (positions, equity, P&L) that should not be readable
    by other local users. No-op on Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return conn


def write_snapshot(
    conn: sqlite3.Connection,
    account: AccountSummary,
    positions: Iterable[Position],
) -> None:
    """Insert one snapshot row in equity_snapshots and one per position."""
    ts = datetime.now(UTC).isoformat(timespec="microseconds")
    conn.execute(
        "INSERT OR REPLACE INTO equity_snapshots VALUES (?, ?, ?, ?, ?)",
        (ts, account.equity, account.cash, account.unrealized, account.realized),
    )
    rows = [
        (
            ts,
            p.position_id,
            p.symbol,
            p.units,
            p.open_rate,
            p.current_rate,
            p.value,
            p.pnl,
            p.pnl_pct,
        )
        for p in positions
    ]
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO position_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
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


def read_position_sparkline(
    conn: sqlite3.Connection,
    symbol: str,
    hours: int = 24,
    max_points: int = 40,
) -> tuple[float, ...]:
    """Return per-position price time series."""
    rows = conn.execute(
        "SELECT current_rate FROM position_snapshots "
        "WHERE symbol = ? AND ts > datetime('now', ?) ORDER BY ts",
        (symbol, f"-{hours} hours"),
    ).fetchall()
    return _downsample([r[0] for r in rows], max_points)
