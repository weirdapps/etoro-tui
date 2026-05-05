# etoro-tui Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python+Textual TUI that displays the user's eToro portfolio in real-time, enriched with overlays from etorotrade signals, etoro_census popular-investor holdings, and news-reader article counts.

**Architecture:** Single Python package run as `python -m etoro_tui`. eToro REST polled every 5s. Three local data sources (CSV, JSON, SQLite) read with mtime/bucket caching. Textual App owns timers and merges everything into a single `AppState` dataclass; widgets render reactively. SQLite snapshots every 5 min for sparklines. Strict layering: `clients/` does I/O only, `widgets/` does rendering only, `app.py` glues them together.

**Tech Stack:** Python 3.13+, Textual ≥0.86, httpx ≥0.28, sqlite3 (stdlib), pytest + pytest-asyncio + respx for tests, uv for env management.

**Spec:** `docs/superpowers/specs/2026-05-05-etoro-tui-design.md`

---

## File Map

| File | Purpose | Task |
|---|---|---|
| `pyproject.toml` | uv-managed package config, deps, entry point | 1 |
| `src/etoro_tui/__init__.py` | package marker (empty) | 1 |
| `src/etoro_tui/__main__.py` | `python -m etoro_tui` entry; auth check then launch app | 1, 14 |
| `tests/conftest.py` | shared fixtures: tmp SQLite, sample CSV/JSON, respx mock | 1 |
| `src/etoro_tui/config.py` | credentials, paths, constants | 2 |
| `src/etoro_tui/models.py` | frozen dataclasses: `Position`, `AccountSummary`, `Overlay`, `AppState` | 3 |
| `src/etoro_tui/storage.py` | SQLite schema init, write_snapshot, sparkline reads | 4 |
| `src/etoro_tui/clients/__init__.py` | package marker | 5 |
| `src/etoro_tui/clients/signals.py` | mtime-cached CSV reader → `{TKR: BUY/SELL/HOLD/None}` | 5 |
| `src/etoro_tui/clients/census.py` | newest-JSON reader → `{symbol: pi_pct}` | 6 |
| `src/etoro_tui/clients/news.py` | SQLite reader with hourly cache → `count_24h`, `is_anomaly` | 7 |
| `src/etoro_tui/clients/etoro.py` | async httpx client with retry/backoff for `/portfolio` and `/account` | 8 |
| `src/etoro_tui/widgets/__init__.py` | package marker | 9 |
| `src/etoro_tui/widgets/footer.py` | key legend + last-fetch + error banner | 9 |
| `src/etoro_tui/widgets/header.py` | equity, today's Δ, sparkline, cash, status dot, clock | 10 |
| `src/etoro_tui/widgets/positions_table.py` | `DataTable` + sort + filter | 11 |
| `src/etoro_tui/widgets/detail_panel.py` | right-side per-position dossier | 12 |
| `src/etoro_tui/app.py` | `EtoroTuiApp`: layout, key bindings, timers, AppState owner, merge logic | 13 |
| `README.md` | install + auth pointer + screenshot | 15 |

---

## Task 1: Project Scaffolding & Dev Environment

**Files:**
- Create: `pyproject.toml`
- Create: `src/etoro_tui/__init__.py`
- Create: `src/etoro_tui/__main__.py` (stub)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "etoro-tui"
version = "0.1.0"
description = "Terminal UI for eToro portfolio with intelligence overlays"
requires-python = ">=3.13"
dependencies = [
    "textual>=0.86",
    "httpx>=0.28",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
]

[project.scripts]
etoro-tui = "etoro_tui.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/etoro_tui"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create empty package marker**

```python
# src/etoro_tui/__init__.py
"""etoro-tui — terminal UI for eToro portfolio."""
__version__ = "0.1.0"
```

- [ ] **Step 3: Create stub `__main__.py`**

```python
# src/etoro_tui/__main__.py
"""Entry point for `python -m etoro_tui`."""


def main() -> int:
    print("etoro-tui — not yet implemented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Create `tests/__init__.py` and conftest stub**

```python
# tests/__init__.py
```

```python
# tests/conftest.py
"""Shared pytest fixtures."""
import pytest
from pathlib import Path


@pytest.fixture
def tmp_signals_csv(tmp_path: Path) -> Path:
    """Sample etoro.csv with TKR and BS columns."""
    p = tmp_path / "etoro.csv"
    p.write_text(
        "TKR,NAME,BS\n"
        "AAPL,Apple Inc,B\n"
        "MSFT,Microsoft,H\n"
        "TSLA,Tesla Inc,S\n"
        "TM,Toyota,I\n"
    )
    return p


@pytest.fixture
def tmp_census_dir(tmp_path: Path) -> Path:
    """Sample census archive dir with one JSON file."""
    import json
    d = tmp_path / "census"
    d.mkdir()
    sample = {
        "instruments": {
            "details": [
                {"instrumentId": 1001, "symbolFull": "AAPL"},
                {"instrumentId": 1002, "symbolFull": "MSFT"},
                {"instrumentId": 1007, "symbolFull": "TSLA"},
            ]
        },
        "investors": [
            {"portfolio": {"positions": [{"instrumentId": 1001}, {"instrumentId": 1002}]}},
            {"portfolio": {"positions": [{"instrumentId": 1001}]}},
            {"portfolio": {"positions": [{"instrumentId": 1007}]}},
            {"portfolio": {"positions": [{"instrumentId": 1001}, {"instrumentId": 1007}]}},
        ],
    }
    (d / "etoro-data-2026-05-04-03-34.json").write_text(json.dumps(sample))
    return d


@pytest.fixture
def tmp_news_db(tmp_path: Path) -> Path:
    """Sample news.db with articles + article_tickers."""
    import sqlite3
    p = tmp_path / "news.db"
    conn = sqlite3.connect(p)
    conn.executescript("""
        CREATE TABLE articles (
            url TEXT PRIMARY KEY, title TEXT, source TEXT, published_at TEXT
        );
        CREATE TABLE article_tickers (article_url TEXT, ticker TEXT);
    """)
    # 5 AAPL articles in last 24h, 1 in last 7d (older), 0 for MSFT
    conn.execute(
        "INSERT INTO articles VALUES ('u1', 't1', 's', datetime('now','-1 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('u2', 't2', 's', datetime('now','-2 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('u3', 't3', 's', datetime('now','-3 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('u4', 't4', 's', datetime('now','-4 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('u5', 't5', 's', datetime('now','-5 hour'))"
    )
    conn.execute(
        "INSERT INTO articles VALUES ('uold', 't_old', 's', datetime('now','-3 days'))"
    )
    for url in ["u1", "u2", "u3", "u4", "u5", "uold"]:
        conn.execute("INSERT INTO article_tickers VALUES (?, 'AAPL')", (url,))
    conn.commit()
    conn.close()
    return p
```

- [ ] **Step 5: Set up uv venv and install**

Run:
```bash
cd ~/SourceCode/etoro-tui
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Expected: clean install, no errors. `pip list` shows `textual`, `httpx`, `pytest`, `respx`.

- [ ] **Step 6: Verify scaffolding**

Run:
```bash
python -m etoro_tui
```

Expected output: `etoro-tui — not yet implemented`

Run:
```bash
pytest -q
```

Expected: `no tests ran in 0.0Xs` (no tests yet, but pytest discovers conftest without errors).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "chore: scaffold project structure and dev env"
```

---

## Task 2: `config.py` — Credentials and Paths

**Files:**
- Create: `src/etoro_tui/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from etoro_tui import config


def test_credentials_from_env(monkeypatch):
    monkeypatch.setenv("ETORO_PUBLIC_KEY", "pk_env")
    monkeypatch.setenv("ETORO_USER_KEY", "uk_env")
    pk, uk = config.get_credentials()
    assert pk == "pk_env"
    assert uk == "uk_env"


def test_credentials_source_env(monkeypatch):
    monkeypatch.setenv("ETORO_PUBLIC_KEY", "pk")
    monkeypatch.setenv("ETORO_USER_KEY", "uk")
    assert config.get_credentials_source() == "env"


def test_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("ETORO_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    # Mock the keychain shell-out to fail
    with patch("etoro_tui.config._keychain_lookup", return_value=None):
        with pytest.raises(config.AuthMissingError):
            config.get_credentials()


def test_paths_are_absolute():
    assert config.SNAPSHOT_DB_PATH.is_absolute()
    assert config.SIGNALS_CSV.is_absolute()
    assert config.NEWS_DB_PATH.is_absolute()


def test_intervals_are_positive():
    assert config.POLL_PORTFOLIO_S > 0
    assert config.POLL_SIGNALS_S > 0
    assert config.SNAPSHOT_S > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: ImportError or ModuleNotFoundError for `etoro_tui.config`.

- [ ] **Step 3: Implement `config.py`**

```python
# src/etoro_tui/config.py
"""Credentials lookup, file paths, refresh intervals."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

ETORO_BASE_URL = "https://api.etoro.com"

# Refresh intervals (seconds)
POLL_PORTFOLIO_S = 5
POLL_SIGNALS_S = 30
POLL_CENSUS_S = 60
POLL_NEWS_S = 300
SNAPSHOT_S = 300

# Paths (all absolute)
SNAPSHOT_DB_PATH = Path.home() / ".etoro-tui" / "snapshots.db"
SIGNALS_CSV = Path.home() / "SourceCode" / "etorotrade" / "yahoofinance" / "output" / "etoro.csv"
CENSUS_GLOB_DIR = Path.home() / "SourceCode" / "etoro_census" / "archive" / "data"
CENSUS_GLOB_PATTERN = "etoro-data-*.json"
NEWS_DB_PATH = Path(
    os.environ.get(
        "NEWS_READER_DB",
        str(Path.home() / "SourceCode" / "news" / "data" / "news.db"),
    )
)

CredSource = Literal["env", "keychain"]


class AuthMissingError(RuntimeError):
    """Raised when neither env vars nor keychain provide credentials."""


def _keychain_lookup(service: str) -> str | None:
    """Read a generic password from macOS Keychain. Returns None if not found."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", "etoro-api", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_credentials() -> tuple[str, str]:
    """Return (public_key, user_key). Env first, then macOS Keychain."""
    pk = os.environ.get("ETORO_PUBLIC_KEY") or _keychain_lookup("etoro-public-key")
    uk = os.environ.get("ETORO_USER_KEY") or _keychain_lookup("etoro-user-key")
    if not pk or not uk:
        raise AuthMissingError(
            "Set ETORO_PUBLIC_KEY and ETORO_USER_KEY env vars, or store them "
            "in macOS Keychain under service names "
            "'etoro-public-key' / 'etoro-user-key' (account 'etoro-api')."
        )
    return pk, uk


def get_credentials_source() -> CredSource:
    """Report whether credentials came from env or keychain (for ? help modal)."""
    if os.environ.get("ETORO_PUBLIC_KEY") and os.environ.get("ETORO_USER_KEY"):
        return "env"
    return "keychain"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/etoro_tui/config.py tests/test_config.py
git commit -m "feat(config): credentials lookup and constants"
```

---

## Task 3: `models.py` — Dataclasses

**Files:**
- Create: `src/etoro_tui/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py
from datetime import datetime, timezone

import pytest

from etoro_tui.models import AccountSummary, AppState, Position


def test_position_immutable():
    p = Position(
        position_id=1, symbol="AAPL", direction="Buy", units=10.0,
        open_rate=150.0, current_rate=160.0, value=1600.0,
        pnl=100.0, pnl_pct=6.67,
        open_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises((AttributeError, TypeError)):  # frozen dataclass
        p.symbol = "MSFT"  # type: ignore[misc]


def test_position_overlay_defaults_none():
    p = Position(
        position_id=1, symbol="AAPL", direction="Buy", units=10.0,
        open_rate=150.0, current_rate=160.0, value=1600.0,
        pnl=100.0, pnl_pct=6.67,
        open_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert p.signal is None
    assert p.pi_pct is None
    assert p.news_24h is None
    assert p.news_anomaly is False


def test_account_summary_fields():
    a = AccountSummary(
        equity=50000.0, cash=10000.0, unrealized=500.0, realized=1500.0,
        fetched_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
    )
    assert a.equity == 50000.0


def test_appstate_default_status():
    s = AppState(
        account=None, positions=(), last_error=None,
        status="live", equity_sparkline=(),
    )
    assert s.status == "live"
    assert s.positions == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `models.py`**

```python
# src/etoro_tui/models.py
"""Frozen dataclasses representing application state."""
from __future__ import annotations

from dataclasses import dataclass, field
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/etoro_tui/models.py tests/test_models.py
git commit -m "feat(models): frozen dataclasses for positions and app state"
```

---

## Task 4: `storage.py` — SQLite Snapshots

**Files:**
- Create: `src/etoro_tui/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_storage.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `storage.py`**

```python
# src/etoro_tui/storage.py
"""SQLite snapshot persistence for sparklines."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

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
    """Open (or create) the snapshot DB and ensure schema. Idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def write_snapshot(
    conn: sqlite3.Connection,
    account: AccountSummary,
    positions: Iterable[Position],
) -> None:
    """Insert one snapshot row in equity_snapshots and one per position."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR REPLACE INTO equity_snapshots VALUES (?, ?, ?, ?, ?)",
        (ts, account.equity, account.cash, account.unrealized, account.realized),
    )
    rows = [
        (ts, p.position_id, p.symbol, p.units, p.open_rate,
         p.current_rate, p.value, p.pnl, p.pnl_pct)
        for p in positions
    ]
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO position_snapshots VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        "SELECT equity FROM equity_snapshots "
        "WHERE ts > datetime('now', ?) ORDER BY ts",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/etoro_tui/storage.py tests/test_storage.py
git commit -m "feat(storage): SQLite snapshots with sparkline downsampling"
```

---

## Task 5: `clients/signals.py` — CSV Reader

**Files:**
- Create: `src/etoro_tui/clients/__init__.py`
- Create: `src/etoro_tui/clients/signals.py`
- Create: `tests/test_clients_signals.py`

- [ ] **Step 1: Create clients package marker**

```python
# src/etoro_tui/clients/__init__.py
"""I/O clients for external data sources."""
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_clients_signals.py
import time
from pathlib import Path

from etoro_tui.clients.signals import SignalsReader


def test_reads_known_signals(tmp_signals_csv: Path):
    r = SignalsReader(tmp_signals_csv)
    out = r.read()
    assert out["AAPL"] == "BUY"
    assert out["MSFT"] == "HOLD"
    assert out["TSLA"] == "SELL"
    assert out["TM"] is None  # 'I' inconclusive maps to None


def test_missing_file_returns_empty(tmp_path: Path):
    r = SignalsReader(tmp_path / "nope.csv")
    assert r.read() == {}


def test_mtime_cache_no_reread(tmp_signals_csv: Path, monkeypatch):
    r = SignalsReader(tmp_signals_csv)
    r.read()
    # Force a second call. Mutate file content WITHOUT updating mtime to prove cache.
    new_text = "TKR,NAME,BS\nXXX,X,B\n"
    tmp_signals_csv.write_text(new_text)
    # Reset mtime to original to simulate "no change"
    stat = (tmp_signals_csv.stat().st_atime, r._cache_mtime)
    import os
    os.utime(tmp_signals_csv, stat)
    out = r.read()
    # Cached, so XXX should NOT appear
    assert "XXX" not in out
    assert "AAPL" in out


def test_mtime_change_triggers_reread(tmp_signals_csv: Path):
    r = SignalsReader(tmp_signals_csv)
    r.read()
    time.sleep(0.01)  # ensure mtime advances
    tmp_signals_csv.write_text("TKR,NAME,BS\nXXX,X,B\n")
    out = r.read()
    assert out == {"XXX": "BUY"}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_clients_signals.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `signals.py`**

```python
# src/etoro_tui/clients/signals.py
"""Read etorotrade signals CSV with mtime-based caching."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional

from ..models import Signal


_BS_MAP: dict[str, Optional[Signal]] = {
    "B": "BUY",
    "S": "SELL",
    "H": "HOLD",
    "I": None,  # inconclusive
}

log = logging.getLogger(__name__)


class SignalsReader:
    """Reads `etoro.csv`, caches by mtime."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: dict[str, Optional[Signal]] = {}
        self._cache_mtime: float | None = None
        self._missing_logged = False

    def read(self) -> dict[str, Optional[Signal]]:
        """Return {symbol: signal or None}."""
        if not self.path.exists():
            if not self._missing_logged:
                log.info("signals CSV not found at %s", self.path)
                self._missing_logged = True
            return {}
        mtime = self.path.stat().st_mtime
        if self._cache_mtime == mtime:
            return self._cache
        result: dict[str, Optional[Signal]] = {}
        with self.path.open(newline="") as f:
            for row in csv.DictReader(f):
                tkr = row.get("TKR", "").strip().upper()
                bs = row.get("BS", "").strip()
                if not tkr:
                    continue
                result[tkr] = _BS_MAP.get(bs)
        self._cache = result
        self._cache_mtime = mtime
        return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_clients_signals.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/etoro_tui/clients/__init__.py src/etoro_tui/clients/signals.py tests/test_clients_signals.py
git commit -m "feat(clients): signals CSV reader with mtime cache"
```

---

## Task 6: `clients/census.py` — JSON Reader

**Files:**
- Create: `src/etoro_tui/clients/census.py`
- Create: `tests/test_clients_census.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clients_census.py
import json
import time
from pathlib import Path

from etoro_tui.clients.census import CensusReader


def test_aggregates_pi_holdings(tmp_census_dir: Path):
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    out = r.read()
    # 4 investors total. AAPL held by 3 → 75%, TSLA by 2 → 50%, MSFT by 1 → 25%
    assert out["AAPL"] == 75.0
    assert out["TSLA"] == 50.0
    assert out["MSFT"] == 25.0


def test_picks_newest_file(tmp_census_dir: Path):
    # Add a newer file (later date) with different data
    newer = tmp_census_dir / "etoro-data-2026-05-05-03-00.json"
    sample = {
        "instruments": {
            "details": [{"instrumentId": 1001, "symbolFull": "AAPL"}]
        },
        "investors": [
            {"portfolio": {"positions": [{"instrumentId": 1001}]}},
            {"portfolio": {"positions": []}},
        ],
    }
    newer.write_text(json.dumps(sample))
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    out = r.read()
    # Should reflect the newer file: 1/2 = 50%
    assert out == {"AAPL": 50.0}


def test_no_files_returns_empty(tmp_path: Path):
    r = CensusReader(tmp_path, "etoro-data-*.json")
    assert r.read() == {}


def test_cache_hit_when_unchanged(tmp_census_dir: Path):
    r = CensusReader(tmp_census_dir, "etoro-data-*.json")
    first = r.read()
    second = r.read()
    assert first is second  # identity, not just equality — proves cache hit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_clients_census.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `census.py`**

```python
# src/etoro_tui/clients/census.py
"""Read newest etoro_census JSON and aggregate PI holdings per symbol."""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

log = logging.getLogger(__name__)


class CensusReader:
    """Picks newest `etoro-data-*.json` in dir; mtime-cached."""

    def __init__(self, directory: Path, pattern: str) -> None:
        self.directory = directory
        self.pattern = pattern
        self._cache: dict[str, float] = {}
        self._cache_key: tuple[Path, float] | None = None
        self._missing_logged = False

    def _newest_file(self) -> Path | None:
        if not self.directory.exists():
            return None
        files = sorted(self.directory.glob(self.pattern))
        return files[-1] if files else None

    def read(self) -> dict[str, float]:
        """Return {symbol: pct_of_PIs_holding}."""
        newest = self._newest_file()
        if newest is None:
            if not self._missing_logged:
                log.info("no census file found in %s", self.directory)
                self._missing_logged = True
            return {}
        mtime = newest.stat().st_mtime
        cache_key = (newest, mtime)
        if self._cache_key == cache_key:
            return self._cache
        with newest.open() as f:
            data = json.load(f)
        id_to_symbol = {
            item["instrumentId"]: item["symbolFull"]
            for item in data["instruments"]["details"]
        }
        investors = data["investors"]
        if not investors:
            self._cache = {}
            self._cache_key = cache_key
            return self._cache
        counter: Counter[int] = Counter()
        for inv in investors:
            held_ids = {
                pos["instrumentId"] for pos in inv["portfolio"]["positions"]
            }
            counter.update(held_ids)
        total = len(investors)
        result: dict[str, float] = {}
        for inst_id, count in counter.items():
            sym = id_to_symbol.get(inst_id)
            if sym:
                result[sym.upper()] = round(count / total * 100, 2)
        self._cache = result
        self._cache_key = cache_key
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_clients_census.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/etoro_tui/clients/census.py tests/test_clients_census.py
git commit -m "feat(clients): census JSON reader with PI holding aggregation"
```

---

## Task 7: `clients/news.py` — SQLite Reader

**Files:**
- Create: `src/etoro_tui/clients/news.py`
- Create: `tests/test_clients_news.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clients_news.py
from pathlib import Path

from etoro_tui.clients.news import NewsReader


def test_count_24h_for_known_ticker(tmp_news_db: Path):
    r = NewsReader(tmp_news_db)
    assert r.count_24h("AAPL") == 5


def test_count_24h_for_missing_ticker(tmp_news_db: Path):
    r = NewsReader(tmp_news_db)
    assert r.count_24h("ZZZZ") == 0


def test_anomaly_when_above_threshold(tmp_news_db: Path):
    # AAPL: 5 in last 24h. 7d total = 6 → daily avg ≈ 0.857.
    # 5 > 0.857 * 1.5 (≈1.29) → anomaly = True.
    r = NewsReader(tmp_news_db)
    assert r.is_anomaly("AAPL") is True


def test_no_anomaly_when_no_articles(tmp_news_db: Path):
    r = NewsReader(tmp_news_db)
    assert r.is_anomaly("ZZZZ") is False


def test_missing_db_returns_none(tmp_path: Path):
    r = NewsReader(tmp_path / "nope.db")
    assert r.count_24h("AAPL") is None
    assert r.is_anomaly("AAPL") is False


def test_hourly_cache_hit(tmp_news_db: Path, monkeypatch):
    r = NewsReader(tmp_news_db)
    r.count_24h("AAPL")
    # Delete the DB file. Next call should hit cache, not error.
    tmp_news_db.unlink()
    assert r.count_24h("AAPL") == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_clients_news.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `news.py`**

```python
# src/etoro_tui/clients/news.py
"""Read news-reader SQLite for per-ticker article counts; hourly cache."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class NewsReader:
    """Read-only access to news.db with hourly per-ticker cache."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        # cache key: (ticker_upper, hour_bucket_iso)
        self._count_cache: dict[tuple[str, str], int] = {}
        self._anomaly_cache: dict[tuple[str, str], bool] = {}
        self._missing_logged = False

    def _hour_bucket(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    def _connect(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            if not self._missing_logged:
                log.info("news DB not found at %s", self.db_path)
                self._missing_logged = True
            return None
        uri = f"file:{self.db_path}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=2.0)

    def count_24h(self, ticker: str) -> Optional[int]:
        """Articles in last 24h tagged with this ticker. None if DB unavailable."""
        ticker = ticker.upper()
        key = (ticker, self._hour_bucket())
        if key in self._count_cache:
            return self._count_cache[key]
        conn = self._connect()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM article_tickers at "
                "JOIN articles a ON a.url = at.article_url "
                "WHERE at.ticker = ? AND a.published_at > datetime('now', '-1 day')",
                (ticker,),
            ).fetchone()
            count = int(row[0])
        finally:
            conn.close()
        self._count_cache[key] = count
        return count

    def is_anomaly(self, ticker: str) -> bool:
        """True if 24h count exceeds 1.5 × 7d daily average."""
        ticker = ticker.upper()
        key = (ticker, self._hour_bucket())
        if key in self._anomaly_cache:
            return self._anomaly_cache[key]
        conn = self._connect()
        if conn is None:
            self._anomaly_cache[key] = False
            return False
        try:
            seven_day_total = conn.execute(
                "SELECT COUNT(*) FROM article_tickers at "
                "JOIN articles a ON a.url = at.article_url "
                "WHERE at.ticker = ? AND a.published_at > datetime('now', '-7 days')",
                (ticker,),
            ).fetchone()[0]
            count_24h = self.count_24h(ticker) or 0
        finally:
            conn.close()
        avg = seven_day_total / 7.0
        result = count_24h > avg * 1.5 if avg > 0 else count_24h > 0
        # Special case: if there are no articles at all, never anomaly.
        if seven_day_total == 0 and count_24h == 0:
            result = False
        self._anomaly_cache[key] = result
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_clients_news.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/etoro_tui/clients/news.py tests/test_clients_news.py
git commit -m "feat(clients): news.db reader with hourly bucket cache"
```

---

## Task 8: `clients/etoro.py` — Async REST Client

**Files:**
- Create: `src/etoro_tui/clients/etoro.py`
- Create: `tests/test_clients_etoro.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clients_etoro.py
import httpx
import pytest
import respx

from etoro_tui.clients.etoro import (
    EtoroAuthError,
    EtoroClient,
    EtoroTransientError,
)


@pytest.mark.asyncio
async def test_fetch_portfolio_sets_headers():
    async with respx.mock(base_url="https://api.etoro.com") as mock:
        route = mock.get("/api/v1/portfolio").respond(
            200, json={"positions": [], "totalEquity": 0, "availableBalance": 0, "totalProfit": 0}
        )
        client = EtoroClient(public_key="pk", user_key="uk")
        await client.fetch_portfolio()
        await client.aclose()
        sent = route.calls.last.request
        assert sent.headers["x-api-key"] == "pk"
        assert sent.headers["x-user-key"] == "uk"
        assert "x-request-id" in sent.headers


@pytest.mark.asyncio
async def test_401_raises_auth_error_no_retry():
    async with respx.mock(base_url="https://api.etoro.com") as mock:
        route = mock.get("/api/v1/portfolio").respond(401, json={"error": "Unauthorized"})
        client = EtoroClient("pk", "uk")
        with pytest.raises(EtoroAuthError):
            await client.fetch_portfolio()
        await client.aclose()
        assert route.call_count == 1  # no retry on 401


@pytest.mark.asyncio
async def test_429_retries_then_raises_transient():
    async with respx.mock(base_url="https://api.etoro.com") as mock:
        route = mock.get("/api/v1/portfolio").respond(429, json={"error": "RateLimited"})
        client = EtoroClient("pk", "uk", max_retries=3, backoff_seconds=(0, 0, 0))
        with pytest.raises(EtoroTransientError):
            await client.fetch_portfolio()
        await client.aclose()
        assert route.call_count == 3


@pytest.mark.asyncio
async def test_429_then_200_succeeds():
    async with respx.mock(base_url="https://api.etoro.com") as mock:
        route = mock.get("/api/v1/portfolio")
        route.side_effect = [
            httpx.Response(429, json={"error": "RateLimited"}),
            httpx.Response(200, json={"positions": [], "totalEquity": 100, "availableBalance": 50, "totalProfit": 0}),
        ]
        client = EtoroClient("pk", "uk", max_retries=3, backoff_seconds=(0, 0, 0))
        data = await client.fetch_portfolio()
        await client.aclose()
        assert data["totalEquity"] == 100
        assert route.call_count == 2


@pytest.mark.asyncio
async def test_fetch_account_returns_payload():
    async with respx.mock(base_url="https://api.etoro.com") as mock:
        mock.get("/api/v1/account").respond(
            200, json={"username": "x", "equity": 50000, "availableBalance": 10000, "realizedProfit": 1000, "unrealizedProfit": 500}
        )
        client = EtoroClient("pk", "uk")
        data = await client.fetch_account()
        await client.aclose()
        assert data["equity"] == 50000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_clients_etoro.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `etoro.py`**

```python
# src/etoro_tui/clients/etoro.py
"""Async eToro REST client with retry+backoff.

Returns raw dicts from `/portfolio` and `/account`. Conversion to dataclasses
happens in app.py so this module stays free of model dependencies.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx

from ..config import ETORO_BASE_URL

log = logging.getLogger(__name__)

DEFAULT_BACKOFF = (5, 15, 60)


class EtoroAuthError(RuntimeError):
    """401 from eToro — credentials invalid. No retry."""


class EtoroTransientError(RuntimeError):
    """Retries exhausted (429 / 5xx / network)."""


class EtoroClient:
    def __init__(
        self,
        public_key: str,
        user_key: str,
        base_url: str = ETORO_BASE_URL,
        max_retries: int = 3,
        backoff_seconds: tuple[int, ...] = DEFAULT_BACKOFF,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._pk = public_key
        self._uk = user_key
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._pk,
            "x-user-key": self._uk,
            "x-request-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

    async def _get(self, path: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.get(path, headers=self._headers())
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                await self._sleep(attempt)
                continue
            if resp.status_code == 401:
                raise EtoroAuthError(f"401 Unauthorized on {path}")
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_error = httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp
                )
                await self._sleep(attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        raise EtoroTransientError(
            f"{path}: exhausted {self._max_retries} retries: {last_error}"
        )

    async def _sleep(self, attempt: int) -> None:
        delay = self._backoff[min(attempt, len(self._backoff) - 1)]
        if delay > 0:
            await asyncio.sleep(delay)

    async def fetch_portfolio(self) -> dict[str, Any]:
        return await self._get("/api/v1/portfolio")

    async def fetch_account(self) -> dict[str, Any]:
        return await self._get("/api/v1/account")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_clients_etoro.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/etoro_tui/clients/etoro.py tests/test_clients_etoro.py
git commit -m "feat(clients): async eToro REST client with retry+backoff"
```

---

## Task 9: `widgets/footer.py` — Status Bar

**Files:**
- Create: `src/etoro_tui/widgets/__init__.py`
- Create: `src/etoro_tui/widgets/footer.py`

This widget is pure rendering; no separate test file (covered by smoke test in Task 13).

- [ ] **Step 1: Create widgets package marker**

```python
# src/etoro_tui/widgets/__init__.py
"""Textual widgets — pure rendering, no I/O."""
```

- [ ] **Step 2: Implement `footer.py`**

```python
# src/etoro_tui/widgets/footer.py
"""Footer: key legend + last-fetch time + error banner."""
from __future__ import annotations

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Static


KEY_LEGEND = (
    "[↑↓] select  [enter] detail  [s] sort  [/] filter  "
    "[r] refresh  [?] help  [q] quit"
)


class Footer(Vertical):
    """Renders key legend left, last-fetch right, error row when set."""

    last_fetch: reactive[datetime | None] = reactive(None)
    last_error: reactive[str | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with Horizontal(id="footer-bar"):
            yield Static(KEY_LEGEND, id="footer-legend")
            yield Static("", id="footer-fetch")
        yield Static("", id="footer-error")

    def watch_last_fetch(self, value: datetime | None) -> None:
        widget = self.query_one("#footer-fetch", Static)
        if value is None:
            widget.update("never fetched")
            return
        delta = (datetime.now(timezone.utc) - value).total_seconds()
        widget.update(f"last fetch {int(delta)}s ago")

    def watch_last_error(self, value: str | None) -> None:
        widget = self.query_one("#footer-error", Static)
        widget.update(f"⚠ {value}" if value else "")
        widget.styles.display = "block" if value else "none"
```

- [ ] **Step 3: Smoke check via REPL**

Run:
```bash
python -c "from etoro_tui.widgets.footer import Footer; print(Footer)"
```

Expected: prints `<class 'etoro_tui.widgets.footer.Footer'>` with no import errors.

- [ ] **Step 4: Commit**

```bash
git add src/etoro_tui/widgets/__init__.py src/etoro_tui/widgets/footer.py
git commit -m "feat(widgets): footer with key legend and status"
```

---

## Task 10: `widgets/header.py` — Equity Header

**Files:**
- Create: `src/etoro_tui/widgets/header.py`

- [ ] **Step 1: Implement `header.py`**

```python
# src/etoro_tui/widgets/header.py
"""Header: equity, today's Δ, sparkline, cash, status dot, clock."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Sparkline, Static

from ..models import AccountSummary, Status


def _fmt_eur(v: float) -> str:
    return f"€{v:,.2f}"


def _fmt_delta(v: float, pct: float) -> str:
    arrow = "▲" if v >= 0 else "▼"
    sign = "+" if v >= 0 else "−"
    return f"{arrow} {sign}€{abs(v):,.2f} ({sign}{abs(pct):.2f}%)"


_STATUS_DOT = {
    "live": "[green]●[/green] live",
    "degraded": "[yellow]●[/yellow] degraded",
    "down": "[red]●[/red] down",
}


class Header(Horizontal):
    """Three-cell header row + sparkline."""

    account: reactive[AccountSummary | None] = reactive(None)
    status: reactive[Status] = reactive("live")
    sparkline_values: reactive[tuple[float, ...]] = reactive(())
    open_pnl: reactive[float] = reactive(0.0)
    today_delta: reactive[float] = reactive(0.0)
    today_delta_pct: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        yield Static("", id="hdr-equity")
        yield Static("", id="hdr-delta")
        yield Sparkline([], id="hdr-spark", summary_function=max)
        yield Static("", id="hdr-cash")
        yield Static("", id="hdr-pnl")
        yield Static("", id="hdr-clock")
        yield Static("", id="hdr-status")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick_clock)
        self._tick_clock()
        self._render_status()

    def _tick_clock(self) -> None:
        now = datetime.now().astimezone()
        self.query_one("#hdr-clock", Static).update(now.strftime("%H:%M:%S %Z"))

    def watch_account(self, a: AccountSummary | None) -> None:
        if a is None:
            self.query_one("#hdr-equity", Static).update("Equity —")
            self.query_one("#hdr-cash", Static).update("Cash —")
            return
        self.query_one("#hdr-equity", Static).update(f"Equity {_fmt_eur(a.equity)}")
        self.query_one("#hdr-cash", Static).update(f"Cash {_fmt_eur(a.cash)}")

    def watch_today_delta(self, _: float) -> None:
        self._render_delta()

    def watch_today_delta_pct(self, _: float) -> None:
        self._render_delta()

    def _render_delta(self) -> None:
        text = "Today " + _fmt_delta(self.today_delta, self.today_delta_pct)
        self.query_one("#hdr-delta", Static).update(text)

    def watch_open_pnl(self, v: float) -> None:
        sign = "+" if v >= 0 else "−"
        self.query_one("#hdr-pnl", Static).update(f"Open P&L {sign}€{abs(v):,.2f}")

    def watch_sparkline_values(self, values: tuple[float, ...]) -> None:
        self.query_one("#hdr-spark", Sparkline).data = list(values)

    def watch_status(self, _: Status) -> None:
        self._render_status()

    def _render_status(self) -> None:
        self.query_one("#hdr-status", Static).update(_STATUS_DOT[self.status])
```

- [ ] **Step 2: Smoke check**

Run:
```bash
python -c "from etoro_tui.widgets.header import Header; print(Header)"
```

Expected: imports without error.

- [ ] **Step 3: Commit**

```bash
git add src/etoro_tui/widgets/header.py
git commit -m "feat(widgets): header with equity, delta, sparkline, status"
```

---

## Task 11: `widgets/positions_table.py` — Main Table

**Files:**
- Create: `src/etoro_tui/widgets/positions_table.py`

- [ ] **Step 1: Implement `positions_table.py`**

```python
# src/etoro_tui/widgets/positions_table.py
"""Main DataTable: positions with overlay columns, sortable + filterable."""
from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, Input

from ..models import Position


SortKey = Literal["pnl_pct", "pnl", "value", "symbol", "signal"]
_SORT_CYCLE: list[SortKey] = ["pnl_pct", "pnl", "value", "symbol", "signal"]

_SIG_STYLE = {
    "BUY": "[green]BUY[/green]",
    "SELL": "[red]SELL[/red]",
    "HOLD": "[dim]HOLD[/dim]",
}

_COLS = (
    "Symbol", "Units", "Open", "Now", "Δ%", "Value", "P&L €",
    "Sig", "PI%", "News",
)


def _fmt_signal(s: str | None) -> str:
    if s is None:
        return "[dim]—[/dim]"
    return _SIG_STYLE.get(s, str(s))


def _fmt_pi(p: float | None) -> str:
    return f"{p:.0f}%" if p is not None else "[dim]—[/dim]"


def _fmt_news(n: int | None, anomaly: bool) -> str:
    if n is None:
        return "[dim]—[/dim]"
    prefix = "▴" if anomaly else " "
    return f"{prefix}{n}"


def _delta_pct_styled(pct: float) -> str:
    if pct >= 0:
        return f"[green]+{pct:.2f}[/green]"
    return f"[red]{pct:.2f}[/red]"


def _pnl_styled(pnl: float) -> str:
    sign = "+" if pnl >= 0 else "−"
    color = "green" if pnl >= 0 else "red"
    return f"[{color}]{sign}{abs(pnl):,.2f}[/{color}]"


class PositionsTable(Vertical):
    """Container for the table + filter input."""

    positions: reactive[tuple[Position, ...]] = reactive(())
    sort_key: reactive[SortKey] = reactive("pnl_pct")
    filter_text: reactive[str] = reactive("")

    class PositionSelected(Message):
        def __init__(self, position: Position | None) -> None:
            self.position = position
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter symbol…", id="filter", classes="hidden")
        yield DataTable(id="positions-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for c in _COLS:
            table.add_column(c, key=c)

    def cycle_sort(self) -> None:
        idx = _SORT_CYCLE.index(self.sort_key)
        self.sort_key = _SORT_CYCLE[(idx + 1) % len(_SORT_CYCLE)]

    def show_filter(self) -> None:
        f = self.query_one("#filter", Input)
        f.remove_class("hidden")
        f.focus()

    def hide_filter(self) -> None:
        f = self.query_one("#filter", Input)
        f.add_class("hidden")
        f.value = ""
        self.filter_text = ""

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.query_one(DataTable).focus()

    def watch_positions(self, _: tuple[Position, ...]) -> None:
        self._refresh_table()

    def watch_sort_key(self, _: SortKey) -> None:
        self._refresh_table()

    def watch_filter_text(self, _: str) -> None:
        self._refresh_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        rows = self._sorted_filtered_positions()
        if 0 <= idx < len(rows):
            self.post_message(self.PositionSelected(rows[idx]))
        else:
            self.post_message(self.PositionSelected(None))

    def _sorted_filtered_positions(self) -> list[Position]:
        rows = list(self.positions)
        f = self.filter_text.upper()
        if f:
            rows = [p for p in rows if f in p.symbol.upper()]
        key = self.sort_key
        if key == "symbol":
            rows.sort(key=lambda p: p.symbol)
        elif key == "signal":
            rows.sort(key=lambda p: (p.signal or "ZZZ"))
        else:
            rows.sort(key=lambda p: getattr(p, key), reverse=True)
        return rows

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for p in self._sorted_filtered_positions():
            table.add_row(
                p.symbol,
                f"{p.units:g}",
                f"{p.open_rate:,.2f}",
                f"{p.current_rate:,.2f}",
                _delta_pct_styled(p.pnl_pct),
                f"{p.value:,.2f}",
                _pnl_styled(p.pnl),
                _fmt_signal(p.signal),
                _fmt_pi(p.pi_pct),
                _fmt_news(p.news_24h, p.news_anomaly),
                key=str(p.position_id),
            )
```

- [ ] **Step 2: Smoke check**

Run:
```bash
python -c "from etoro_tui.widgets.positions_table import PositionsTable; print(PositionsTable)"
```

Expected: imports without error.

- [ ] **Step 3: Commit**

```bash
git add src/etoro_tui/widgets/positions_table.py
git commit -m "feat(widgets): positions table with sort, filter, overlays"
```

---

## Task 12: `widgets/detail_panel.py` — Right-Side Dossier

**Files:**
- Create: `src/etoro_tui/widgets/detail_panel.py`

- [ ] **Step 1: Implement `detail_panel.py`**

```python
# src/etoro_tui/widgets/detail_panel.py
"""Right-side panel: deep-dive on selected position."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Sparkline, Static

from ..models import Position


class DetailPanel(Vertical):
    """Shown when a position is selected and width ≥ 100."""

    position: reactive[Position | None] = reactive(None)
    intraday: reactive[tuple[float, ...]] = reactive(())
    seven_day: reactive[tuple[float, ...]] = reactive(())

    def compose(self) -> ComposeResult:
        yield Static("Select a position", id="dp-title")
        yield Static("", id="dp-position")
        yield Static("", id="dp-now")
        yield Static("", id="dp-overlay")
        yield Static("Today", id="dp-today-label")
        yield Sparkline([], id="dp-today")
        yield Static("7-day", id="dp-week-label")
        yield Sparkline([], id="dp-week")

    def watch_position(self, p: Position | None) -> None:
        title = self.query_one("#dp-title", Static)
        if p is None:
            title.update("Select a position")
            for sel in ("#dp-position", "#dp-now", "#dp-overlay"):
                self.query_one(sel, Static).update("")
            return
        title.update(f"{p.symbol}")
        self.query_one("#dp-position", Static).update(
            f"#{p.position_id} · {p.direction} · {p.units:g} units @ {p.open_rate:,.2f}"
        )
        sign = "+" if p.pnl >= 0 else "−"
        color = "green" if p.pnl >= 0 else "red"
        self.query_one("#dp-now", Static).update(
            f"Now [{color}]{p.current_rate:,.2f}[/{color}]   "
            f"Δopen [{color}]{sign}{abs(p.pnl_pct):.2f}%[/{color}] "
            f"([{color}]{sign}€{abs(p.pnl):,.2f}[/{color}])   "
            f"Value €{p.value:,.2f}"
        )
        sig = "—" if p.signal is None else p.signal
        pi = "—" if p.pi_pct is None else f"{p.pi_pct:.0f}%"
        news = "—" if p.news_24h is None else f"{p.news_24h}{' ▴' if p.news_anomaly else ''}"
        self.query_one("#dp-overlay", Static).update(
            f"Signal {sig}   Census {pi} of PIs hold   News (24h) {news}"
        )

    def watch_intraday(self, vals: tuple[float, ...]) -> None:
        self.query_one("#dp-today", Sparkline).data = list(vals)

    def watch_seven_day(self, vals: tuple[float, ...]) -> None:
        self.query_one("#dp-week", Sparkline).data = list(vals)
```

- [ ] **Step 2: Smoke check**

Run:
```bash
python -c "from etoro_tui.widgets.detail_panel import DetailPanel; print(DetailPanel)"
```

Expected: imports without error.

- [ ] **Step 3: Commit**

```bash
git add src/etoro_tui/widgets/detail_panel.py
git commit -m "feat(widgets): detail panel with position dossier and sparklines"
```

---

## Task 13: `app.py` — Wire Everything Together

**Files:**
- Create: `src/etoro_tui/app.py`
- Create: `src/etoro_tui/styles.tcss`
- Create: `tests/test_app_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

```python
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
        assert table.sort_key != before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app_smoke.py -v`
Expected: ImportError.

- [ ] **Step 3: Create `styles.tcss`**

```css
/* src/etoro_tui/styles.tcss */

Screen {
    layout: vertical;
}

Header {
    height: 1;
}

Header > Static {
    margin: 0 1;
}

#hdr-spark {
    width: 14;
}

#main {
    height: 1fr;
    layout: horizontal;
}

PositionsTable {
    width: 1fr;
}

DetailPanel {
    width: 40;
    border-left: solid $accent;
    padding: 0 1;
}

DetailPanel.hidden {
    display: none;
}

#footer-bar {
    height: 1;
    layout: horizontal;
}

#footer-legend {
    width: 1fr;
}

#footer-fetch {
    width: auto;
}

#footer-error {
    height: auto;
    color: $error;
}

Input.hidden {
    display: none;
}
```

- [ ] **Step 4: Implement `app.py`**

```python
# src/etoro_tui/app.py
"""EtoroTuiApp — the Textual application that owns AppState and timers."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal

from . import config, storage
from .clients.census import CensusReader
from .clients.etoro import (
    EtoroAuthError,
    EtoroClient,
    EtoroTransientError,
)
from .clients.news import NewsReader
from .clients.signals import SignalsReader
from .models import AccountSummary, AppState, Position
from .widgets.detail_panel import DetailPanel
from .widgets.footer import Footer
from .widgets.header import Header
from .widgets.positions_table import PositionsTable

log = logging.getLogger(__name__)


def _to_position(raw: dict, signals: dict, census: dict, news: NewsReader) -> Position:
    sym = raw["symbol"].upper()
    cnt = news.count_24h(sym)
    return Position(
        position_id=raw["positionId"],
        symbol=sym,
        direction=raw["direction"],
        units=float(raw["units"]),
        open_rate=float(raw["openRate"]),
        current_rate=float(raw["currentRate"]),
        value=float(raw["units"]) * float(raw["currentRate"]),
        pnl=float(raw["profit"]),
        pnl_pct=float(raw["profitPercentage"]),
        open_ts=datetime.fromisoformat(raw["openTimestamp"].replace("Z", "+00:00")),
        signal=signals.get(sym),
        pi_pct=census.get(sym),
        news_24h=cnt,
        news_anomaly=news.is_anomaly(sym) if cnt is not None else False,
    )


def _to_account(raw: dict) -> AccountSummary:
    return AccountSummary(
        equity=float(raw["equity"]),
        cash=float(raw["availableBalance"]),
        unrealized=float(raw["unrealizedProfit"]),
        realized=float(raw["realizedProfit"]),
        fetched_at=datetime.now(timezone.utc),
    )


class EtoroTuiApp(App[None]):
    """Top-level Textual app."""

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "sort", "Sort"),
        Binding("slash", "filter", "Filter", key_display="/"),
        Binding("escape", "clear_filter", "Clear filter", show=False),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("enter", "toggle_detail", "Detail", show=False),
    ]

    def __init__(
        self,
        initial_state: Optional[AppState] = None,
        disable_polling: bool = False,
        etoro_client: Optional[EtoroClient] = None,
    ) -> None:
        super().__init__()
        self._state: AppState = initial_state or AppState(
            account=None, positions=(), last_error=None,
            status="live", equity_sparkline=(),
        )
        self._disable_polling = disable_polling
        self._etoro_client = etoro_client
        self._signals = SignalsReader(config.SIGNALS_CSV)
        self._census = CensusReader(config.CENSUS_GLOB_DIR, config.CENSUS_GLOB_PATTERN)
        self._news = NewsReader(config.NEWS_DB_PATH)
        self._db: Optional[sqlite3.Connection] = None
        self._opening_equity_today: Optional[float] = None
        self._show_detail = False

    # ------- composition -------

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        with Horizontal(id="main"):
            yield PositionsTable(id="table")
            yield DetailPanel(id="detail", classes="hidden")
        yield Footer(id="footer")

    async def on_mount(self) -> None:
        self._db = storage.init_db(config.SNAPSHOT_DB_PATH)
        self._render_state()
        if self._disable_polling:
            return
        # Auth-required: build client now if not injected.
        if self._etoro_client is None:
            try:
                pk, uk = config.get_credentials()
            except config.AuthMissingError as e:
                self._set_error(str(e), "down")
                return
            self._etoro_client = EtoroClient(public_key=pk, user_key=uk)
        self.set_interval(config.POLL_PORTFOLIO_S, self._tick_etoro)
        self.set_interval(config.POLL_SIGNALS_S, self._tick_overlays)
        self.set_interval(config.POLL_NEWS_S, self._tick_overlays)
        self.set_interval(config.SNAPSHOT_S, self._tick_snapshot)
        self.set_interval(1.0, self._tick_footer_clock)
        await self._tick_etoro()

    async def on_unmount(self) -> None:
        if self._etoro_client is not None:
            await self._etoro_client.aclose()
        if self._db is not None:
            self._db.close()

    # ------- timers -------

    async def _tick_etoro(self) -> None:
        if self._etoro_client is None:
            return
        try:
            portfolio = await self._etoro_client.fetch_portfolio()
            account = await self._etoro_client.fetch_account()
        except EtoroAuthError as e:
            self._set_error(f"auth failed: {e}", "down")
            return
        except EtoroTransientError as e:
            self._set_error(f"transient: {e}", "degraded")
            return

        signals = self._signals.read()
        census = self._census.read()
        positions = tuple(
            _to_position(p, signals, census, self._news)
            for p in portfolio.get("positions", [])
        )
        acct = _to_account(account)
        if self._opening_equity_today is None:
            self._opening_equity_today = acct.equity

        spark = ()
        if self._db is not None:
            spark = storage.read_equity_sparkline(self._db, hours=24, max_points=80)

        self._state = AppState(
            account=acct, positions=positions, last_error=None,
            status="live", equity_sparkline=spark,
        )
        self._render_state()

    def _tick_overlays(self) -> None:
        # Re-attach current overlay values without re-fetching from eToro.
        if self._state.account is None:
            return
        from dataclasses import replace
        signals = self._signals.read()
        census = self._census.read()
        new_positions = []
        for p in self._state.positions:
            cnt = self._news.count_24h(p.symbol)
            new_positions.append(replace(
                p,
                signal=signals.get(p.symbol),
                pi_pct=census.get(p.symbol),
                news_24h=cnt,
                news_anomaly=self._news.is_anomaly(p.symbol) if cnt is not None else False,
            ))
        new_positions = tuple(new_positions)
        self._state = AppState(
            account=self._state.account, positions=new_positions,
            last_error=self._state.last_error, status=self._state.status,
            equity_sparkline=self._state.equity_sparkline,
        )
        self._render_state()

    def _tick_snapshot(self) -> None:
        if self._db is None or self._state.account is None:
            return
        try:
            storage.write_snapshot(self._db, self._state.account, self._state.positions)
        except Exception as e:  # noqa: BLE001 — snapshot is best-effort
            log.warning("snapshot write failed: %s", e)

    def _tick_footer_clock(self) -> None:
        if self._state.account is not None:
            self.query_one(Footer).last_fetch = self._state.account.fetched_at

    # ------- rendering -------

    def _render_state(self) -> None:
        header = self.query_one(Header)
        header.account = self._state.account
        header.status = self._state.status
        header.sparkline_values = self._state.equity_sparkline
        if self._state.account is not None:
            header.open_pnl = self._state.account.unrealized
            if self._opening_equity_today is not None:
                delta = self._state.account.equity - self._opening_equity_today
                pct = (delta / self._opening_equity_today * 100
                       if self._opening_equity_today else 0)
                header.today_delta = delta
                header.today_delta_pct = pct
        self.query_one(PositionsTable).positions = self._state.positions
        footer = self.query_one(Footer)
        footer.last_error = self._state.last_error

    def _set_error(self, msg: str, status: str) -> None:
        self._state = AppState(
            account=self._state.account, positions=self._state.positions,
            last_error=msg, status=status, equity_sparkline=self._state.equity_sparkline,
        )
        self._render_state()

    # ------- actions -------

    async def action_refresh(self) -> None:
        await self._tick_etoro()

    def action_sort(self) -> None:
        self.query_one(PositionsTable).cycle_sort()

    def action_filter(self) -> None:
        self.query_one(PositionsTable).show_filter()

    def action_clear_filter(self) -> None:
        self.query_one(PositionsTable).hide_filter()

    def action_toggle_detail(self) -> None:
        self._show_detail = not self._show_detail
        panel = self.query_one(DetailPanel)
        panel.set_class(not self._show_detail, "hidden")

    def action_help(self) -> None:
        # v1 — help via footer briefly
        self._set_error(
            "keys: ↑↓ select · enter detail · s sort · / filter · r refresh · q quit",
            self._state.status,
        )

    # ------- messages -------

    def on_positions_table_position_selected(
        self, message: PositionsTable.PositionSelected
    ) -> None:
        panel = self.query_one(DetailPanel)
        panel.position = message.position
        if message.position is not None and self._db is not None:
            spark = storage.read_position_sparkline(
                self._db, message.position.symbol, hours=24, max_points=40
            )
            panel.intraday = spark
            week = storage.read_position_sparkline(
                self._db, message.position.symbol, hours=24 * 7, max_points=40
            )
            panel.seven_day = week
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_app_smoke.py -v`
Expected: 3 passed.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/etoro_tui/app.py src/etoro_tui/styles.tcss tests/test_app_smoke.py
git commit -m "feat(app): wire clients, widgets, timers, and key bindings"
```

---

## Task 14: `__main__.py` — Real Entry Point

**Files:**
- Modify: `src/etoro_tui/__main__.py`

- [ ] **Step 1: Replace stub with real entry**

```python
# src/etoro_tui/__main__.py
"""Entry point: `python -m etoro_tui` or `etoro-tui`."""
from __future__ import annotations

import logging
import sys

from . import config
from .app import EtoroTuiApp


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        # Validate credentials before launching the UI so the error message
        # is visible in the terminal, not buried in the TUI.
        config.get_credentials()
    except config.AuthMissingError as e:
        print(f"etoro-tui: {e}", file=sys.stderr)
        return 2
    EtoroTuiApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke run with bad credentials**

Run:
```bash
ETORO_PUBLIC_KEY="" ETORO_USER_KEY="" python -m etoro_tui
```

Expected: stderr message about credentials, exit code 2.

- [ ] **Step 3: Smoke run with credentials (real or fake)**

Run with real keys (or temporarily fake ones — eToro will 401 and the app will still launch and show the error in the footer):
```bash
ETORO_PUBLIC_KEY=fake ETORO_USER_KEY=fake python -m etoro_tui
```

Expected: TUI launches; status dot turns red; footer shows "auth failed". Press `q` to exit.

- [ ] **Step 4: Commit**

```bash
git add src/etoro_tui/__main__.py
git commit -m "feat(cli): real entry point with pre-flight credential check"
```

---

## Task 15: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

```markdown
# etoro-tui

Terminal UI for an eToro portfolio. Polls the eToro REST API every 5 seconds and
overlays per-position intelligence from your other repos:

- **Signal** (BUY/SELL/HOLD) from `etorotrade/yahoofinance/output/etoro.csv`
- **PI%** (popular-investor holding rate) from `etoro_census/archive/data/etoro-data-*.json`
- **News (24h)** count from `news/data/news.db`

Stores 5-minute equity + position snapshots in `~/.etoro-tui/snapshots.db` for
sparklines.

## Install

```bash
cd ~/SourceCode/etoro-tui
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Auth

Set the same env vars used by the `etoro-trading` plugin:

```bash
export ETORO_PUBLIC_KEY="…"
export ETORO_USER_KEY="…"
```

Or store in macOS Keychain:

```bash
security add-generic-password -a etoro-api -s etoro-public-key -w "…"
security add-generic-password -a etoro-api -s etoro-user-key -w "…"
```

## Run

```bash
etoro-tui   # or: python -m etoro_tui
```

## Keys

| Key | Action |
|---|---|
| ↑/↓ | Select row |
| Enter | Toggle detail panel |
| s | Cycle sort |
| / | Filter by symbol |
| r | Refresh now |
| ? | Help |
| q | Quit |

## Tests

```bash
pytest -v
```

## Spec

`docs/superpowers/specs/2026-05-05-etoro-tui-design.md`
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with install, auth, keys, tests"
```

---

## Final Verification

- [ ] **Step 1: Full test suite passes**

Run: `pytest -v`
Expected: every test green; no warnings about asyncio mode or deprecations.

- [ ] **Step 2: App launches and renders against real eToro**

Run: `etoro-tui` (with real credentials)
Expected: header shows equity within 5s; positions populate; status dot is green.

- [ ] **Step 3: Quit and re-launch — verify snapshot persistence**

After ~5 minutes of running, quit (`q`) and re-launch. Within seconds the
header sparkline should populate with the prior snapshot points.

- [ ] **Step 4: Tag v0.1.0**

```bash
git tag v0.1.0
git log --oneline | head
```

---

## Plan Self-Review

| Spec section | Covered by task |
|---|---|
| §3 Constraints (auth, paths) | Task 2 |
| §4 Architecture (file map) | All tasks |
| §5.1 config | Task 2 |
| §5.2 models | Task 3 |
| §5.3 etoro client | Task 8 |
| §5.4 signals | Task 5 |
| §5.5 census | Task 6 |
| §5.6 news | Task 7 |
| §5.7 storage | Task 4 |
| §5.8 widgets (footer/header/table/detail) | Tasks 9–12 |
| §6 data flow / timers | Task 13 |
| §7 layout / key bindings | Tasks 11, 13 |
| §8 error handling | Tasks 8 (client), 13 (app) |
| §9 testing strategy | Embedded in each task |
| §10 dependencies / setup | Task 1 |

No placeholders. Type names consistent across tasks (Position, AccountSummary, AppState, Signal, Status). All file paths absolute or src-relative. Every code step shows the code; every command step shows the command and expected output.
