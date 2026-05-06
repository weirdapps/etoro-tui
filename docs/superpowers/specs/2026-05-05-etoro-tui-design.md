# etoro-tui — Design Spec

**Date:** 2026-05-05
**Status:** Approved for implementation planning
**Owner:** Dimitrios Plessas

## 1. Goal

A terminal UI that shows the user's eToro portfolio as a live, "professional trading desk" view, enriched with intelligence already produced by the user's other repos (etorotrade signals, etoro_census popular-investor holdings, news-reader corpus).

Run as `python -m etoro_tui` (or `etoro-tui` after `pip install -e .`).

## 2. Non-Goals

- **No trade execution.** Open/close/modify stays in the existing `etoro-trading` plugin (`/trade`, `/close`).
- **No demo-mode toggle in v1.** Live account only. Demo can be added by extending `config.py` later.
- **No web/REST API surface.** This is a single-user local TUI.
- **No alerts/notifications.** No popups, no email, no Telegram. Pure observation.
- **No history beyond local SQLite snapshots.** No analytics dashboards, no exports — both are out-of-scope here and live in other tools.

## 3. Constraints & Assumptions

- **eToro API is REST-only.** No WebSocket exists for retail/PI accounts. Live-feel is achieved by 5s polling.
- **Rate limit:** 60 req/min on `api.etoro.com`. Our 5s portfolio + 5s account polling = 24 req/min, leaving headroom for retries and `r` manual refreshes.
- **Auth:** `ETORO_PUBLIC_KEY` / `ETORO_USER_KEY` env vars first, macOS Keychain (`etoro-api` / `etoro-public-key`, `etoro-user-key`) as fallback. Same contract as the `etoro-trading` plugin — zero new credential setup.
- **Python 3.13+** required (matches user's other repos).
- **Terminal:** assumes 256-color or truecolor support; degrades gracefully on 16-color.
- **Snapshot store path:** `~/.etoro-tui/snapshots.db`. Directory created on first run.
- **Existing data files (read-only):**
  - Signals: `~/SourceCode/etorotrade/yahoofinance/output/etoro.csv`
  - Census archive: `~/SourceCode/etoro_census/archive/data/etoro-data-*.json` (newest by filename)
  - News SQLite: `~/SourceCode/news/data/news.db` (overridable via `NEWS_READER_DB` env var) — if absent, news column hides silently. Schema: `articles(url, published_at, ...)` joined to `article_tickers(article_url, ticker)`.

## 4. Architecture

```
etoro-tui/
├── pyproject.toml              # uv-managed; deps: textual, httpx; sqlite3 stdlib
├── README.md                   # install + auth pointer to etoro-api setup
├── src/etoro_tui/
│   ├── __init__.py
│   ├── __main__.py             # `python -m etoro_tui` entry
│   ├── app.py                  # EtoroTuiApp (Textual App): layout, bindings, timers, AppState owner
│   ├── config.py               # auth lookup (env → Keychain), paths, constants
│   ├── models.py               # frozen dataclasses: Position, AccountSummary, Overlay, AppState
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── etoro.py            # async REST client (httpx); retry+backoff; parses portfolio + account
│   │   ├── signals.py          # mtime-cached CSV reader → {symbol: "BUY"|"SELL"|"HOLD"}
│   │   ├── census.py           # mtime-cached newest-JSON reader → {symbol: pi_pct_holding}
│   │   └── news.py             # SQLite COUNT(*) per ticker; bucketed cache
│   ├── storage.py              # SQLite snapshots: schema init, write, sparkline query
│   └── widgets/
│       ├── __init__.py
│       ├── header.py           # equity, today's Δ, equity sparkline, cash, open P&L, clock, ●status
│       ├── positions_table.py  # main DataTable + sort + filter
│       ├── detail_panel.py     # right-side: position deep-dive + per-ticker sparklines
│       └── footer.py           # key legend + last-fetch ago + error banner
└── tests/
    ├── conftest.py             # fixtures: respx mock, tmp_path SQLite, fake CSV/JSON
    ├── test_clients_etoro.py
    ├── test_clients_signals.py
    ├── test_clients_census.py
    ├── test_clients_news.py
    ├── test_storage.py
    └── test_app_smoke.py       # Textual App.run_test() pilot
```

**Layering rules (enforced by code review, not by import linter in v1):**

1. `widgets/` may NOT import `clients/` or `httpx` or `sqlite3`. Widgets read `AppState` only.
2. `clients/` may NOT import `widgets/` or `textual`. Clients return dataclasses or dicts.
3. `app.py` is the only file allowed to wire clients → widgets via `AppState` updates.
4. `storage.py` has no dependency on `clients/` or `widgets/` — it persists whatever `app.py` hands it.

## 5. Components

### 5.1 `config.py`

- `ETORO_BASE_URL = "https://api.etoro.com"`
- `def get_credentials() -> tuple[str, str]` — returns `(public_key, user_key)`. Order: env vars → `security find-generic-password` shell-out. Raises `AuthMissingError` if neither found.
- `SNAPSHOT_DB_PATH = Path.home() / ".etoro-tui" / "snapshots.db"`
- `SIGNALS_CSV = Path.home() / "SourceCode/etorotrade/yahoofinance/output/etoro.csv"`
- `CENSUS_GLOB = Path.home() / "SourceCode/etoro_census/archive/data" / "etoro-data-*.json"`
- `NEWS_DB_PATH = Path(os.environ.get("NEWS_READER_DB", Path.home() / "SourceCode/news/data/news.db"))`
- Refresh intervals as named constants: `POLL_PORTFOLIO_S = 5`, `POLL_SIGNALS_S = 30`, `POLL_CENSUS_S = 60`, `POLL_NEWS_S = 300`, `SNAPSHOT_S = 300`.

### 5.2 `models.py`

```python
@dataclass(frozen=True)
class Position:
    position_id: int
    symbol: str
    direction: Literal["Buy", "Sell"]
    units: float
    open_rate: float
    current_rate: float
    value: float          # units * current_rate
    pnl: float            # eToro's `profit`
    pnl_pct: float        # eToro's `profitPercentage`
    open_ts: datetime
    # overlays — None means "not available"
    signal: Optional[Literal["BUY", "SELL", "HOLD"]] = None  # I→None (inconclusive)
    pi_pct: Optional[float] = None
    news_24h: Optional[int] = None
    news_anomaly: bool = False  # True if news_24h > 7d avg

@dataclass(frozen=True)
class AccountSummary:
    equity: float
    cash: float            # availableBalance
    unrealized: float      # totalProfit
    realized: float        # realizedProfit
    fetched_at: datetime

@dataclass(frozen=True)
class AppState:
    account: Optional[AccountSummary]
    positions: tuple[Position, ...]
    last_error: Optional[str]
    status: Literal["live", "degraded", "down"]
    equity_sparkline: tuple[float, ...]   # last 24h points from SQLite
```

### 5.3 `clients/etoro.py`

- `class EtoroClient` (httpx.AsyncClient wrapper).
- `async def fetch_portfolio() -> list[dict]` and `async def fetch_account() -> dict`.
- Headers built per request: `x-api-key`, `x-user-key`, `x-request-id` (UUID4), `Content-Type: application/json`.
- Retry policy: on 429 or 5xx, exponential backoff 5s → 15s → 60s, max 3 attempts, then raise `EtoroTransientError`.
- On 401: raise `EtoroAuthError` immediately (no retry).
- Public methods return raw dicts; conversion to `Position` / `AccountSummary` happens in `app.py` so clients stay pure.

### 5.4 `clients/signals.py`

- `class SignalsReader` with mtime cache.
- `def read() -> dict[str, Optional[Literal["BUY","SELL","HOLD"]]]` — returns `{symbol: signal}`.
- Strategy: stat the file; if mtime unchanged since last read, return cached dict. Otherwise re-parse.
- CSV columns (verified): `TKR` is the ticker, `BS` is the signal column with values `B|S|H|I` — mapped to `BUY|SELL|HOLD|None` (`I` = inconclusive, treated as no signal).
- Missing file → returns `{}` and logs once.

### 5.5 `clients/census.py`

- `class CensusReader` with newest-file mtime cache.
- `def read() -> dict[str, float]` — returns `{symbol_uppercase: pi_pct_holding_0_to_100}`.
- Strategy: glob for `etoro-data-*.json`, take newest by filename (filename embeds `YYYY-MM-DD-HH-MM`), stat it, mtime cache.
- Parse (verified against 2026-05-04 file, 1500 investors × 4720 instruments):
  1. Build `id_to_symbol = {item["instrumentId"]: item["symbolFull"] for item in data["instruments"]["details"]}`.
  2. For each investor in `data["investors"]`, collect unique `instrumentId`s from `investor["portfolio"]["positions"]`.
  3. Count investors per `instrumentId`, divide by `len(data["investors"])`, multiply by 100.
  4. Map `instrumentId` → `symbol` via `id_to_symbol`.
- Missing file or empty glob → returns `{}`.

### 5.6 `clients/news.py`

- `class NewsReader` with hourly bucket cache (key: `(symbol, current_hour_utc)`).
- `def count_24h(symbol: str) -> int | None` — returns count or `None` if DB unavailable.
- `def is_anomaly(symbol: str) -> bool` — `count_24h > avg(daily_count_last_7_days) * 1.5`.
- DB schema (verified at `~/SourceCode/news/data/news.db`):
  - `articles(url PRIMARY KEY, title, source, published_at, ...)`
  - `article_tickers(article_url, ticker)` — junction table.
- Concrete queries:
  ```sql
  -- count_24h
  SELECT COUNT(*) FROM article_tickers at
    JOIN articles a ON a.url = at.article_url
    WHERE at.ticker = ? AND a.published_at > datetime('now', '-1 day');
  -- 7-day daily average for anomaly check
  SELECT COUNT(*) * 1.0 / 7 FROM article_tickers at
    JOIN articles a ON a.url = at.article_url
    WHERE at.ticker = ? AND a.published_at > datetime('now', '-7 days');
  ```
- DB opened read-only (`uri=true&mode=ro`) so we can't conflict with the writer.
- Missing DB file → all methods return `None`/`False`; news column hidden in `positions_table.py`.

### 5.7 `storage.py`

```python
def init_db(path: Path) -> sqlite3.Connection
def write_snapshot(conn, account: AccountSummary, positions: Iterable[Position]) -> None
def read_equity_sparkline(conn, hours: int = 24, max_points: int = 80) -> tuple[float, ...]
def read_position_sparkline(conn, symbol: str, hours: int = 24, max_points: int = 40) -> tuple[float, ...]
```

Schema (idempotent `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts          TEXT PRIMARY KEY,        -- ISO-8601 UTC
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
```

Sparkline query downsamples to `max_points` via `WHERE ts > ? ORDER BY ts` then Python-side stride sample.

### 5.8 `widgets/`

Widgets are pure renderers. Each receives the slice of `AppState` it needs via Textual reactivity.

- **`header.py`** — three-line header: equity + today's Δ + sparkline; cash + open P&L; clock + status dot.
- **`positions_table.py`** — `DataTable` with columns: Symbol, Units, Open, Now, Δ%, Value, P&L €, Sig, PI%, News. Sortable. Filterable via `/`. Color rules: positive Δ green, negative red, BUY green, SELL red, HOLD dim, news anomaly ▴ prefix.
- **`detail_panel.py`** — visible when terminal width ≥ 100 cols and a row is selected. Renders position dossier + intraday + 7-day sparkline.
- **`footer.py`** — key legend left, "last fetch Ns ago" right, error banner row when `app_state.last_error` set.

## 6. Data Flow & Refresh Cadence

| Source | Cadence | Driver | Failure mode |
|---|---|---|---|
| eToro `/portfolio` + `/account` | 5s + manual `r` | `app.set_interval(5, fetch_etoro)` | Status → degraded → down; last-good state retained |
| Signals CSV | 30s (mtime check) | `app.set_interval(30, refresh_signals)` | Returns `{}`, signal column shows `—` |
| Census JSON | 60s (mtime check) | `app.set_interval(60, refresh_census)` | Returns `{}`, PI% column shows `—` |
| News SQLite | timer every 5min over held tickers; hourly bucket cache means real DB hits ≤1/ticker/hour | `app.set_interval(300, refresh_news)` | News column hidden if DB missing |
| Snapshot writer | 5min | `app.set_interval(300, write_snapshot)` | Logged, never blocks |

`app.py` owns all timers. Each timer callback updates a slice of `AppState`. Widgets are subscribed to `AppState` reactively (Textual's `reactive` attribute).

**Merge:** eToro positions are the spine. For each `Position`, lookup `signals[symbol]`, `census[symbol]`, `news.count_24h(symbol)` and attach. Lookups are `dict.get(symbol)` → `None` if missing.

## 7. Layout & Interactions

### 7.1 Layout (120×35 reference; responsive)

```
┌─ etoro-tui ──────────────────────────────────────────────────────────────────────────────────────────────── ●live ─┐
│ Equity €52,847.30   Today ▲ +€423.18 (+0.81%)   ▁▂▃▅▆▇▇▆▅▆▇█  Cash €12,400.00   Open P&L +€1,247   13:42:05 EET  │
├─────────────────────────────────────────────────────────────────────────────────────┬───────────────────────────────┤
│ Symbol  Units   Open      Now      Δ%      Value     P&L €    Sig  PI%   News      │ NVDA · NVIDIA Corp            │
│ ▶ NVDA   8.5    420.00   445.10   +5.98   3,783.35   +213.35  BUY  73%   ▴12       │ Position #N                   │
│   AAPL  25.3    145.20   148.91   +2.55   3,767.42    +93.85  BUY  61%    8        │ Long · 8.5 units              │
│   ...                                                                              │ ...                           │
├────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────┤
│ [↑↓] select  [enter] toggle detail  [s] sort  [/] filter  [r] refresh  [?] help  [q] quit  ·  last fetch 3s ago  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Responsive rules:**
- Width < 100: detail panel hidden, table takes full width.
- Width < 80: header collapses to one line (equity + status only).
- Height < 20: footer key legend abbreviated to `[r] [?] [q]`.

### 7.2 Visual conventions

- ▲ green / ▼ red: today's change for equity and per-row Δ%.
- Signal column: BUY green, SELL red, HOLD dim grey, missing/inconclusive `—` very-dim grey.
- News ▴ prefix when count exceeds 1.5× the 7-day average.
- ●status dot: green=live (last fetch <10s), yellow=degraded (10–60s or backoff), red=down (>60s or auth error).

### 7.3 Key bindings

| Key | Action |
|---|---|
| `↑` `↓` | Move row selection |
| `Enter` | Toggle detail panel for selected position |
| `s` | Cycle sort: P&L% → P&L€ → Value → Symbol → Signal |
| `/` | Filter input: type to narrow rows by symbol substring; `Esc` clears |
| `r` | Force refresh now (resets timer) |
| `?` | Help overlay (modal) — lists all bindings + diagnostics: auth source (`env` or `keychain`), last successful fetch timestamp, snapshot DB path, overlay file paths and their last-modified times |
| `q` / `Ctrl+C` | Quit cleanly (close httpx client, close SQLite) |

## 8. Error Handling

| Failure | Behavior | User-visible |
|---|---|---|
| eToro 401 | `EtoroAuthError` → status=down, no further fetches | Footer banner: "auth failed — check ETORO_USER_KEY", `?` modal shows current key source |
| eToro 429 | Backoff 5→15→60s; status=degraded during backoff | Status dot yellow; no popup |
| eToro 5xx / timeout | Same backoff as 429 | Same |
| eToro 3 retries exhausted | status=down; last-good state retained; resume polling at next interval | Status dot red; banner shows last error |
| Signals CSV missing | `clients/signals.py` returns `{}` | Sig column shows `—`; logged once on startup |
| Census JSON missing | Same | PI% column shows `—` |
| News DB missing | `news_24h` is `None` for all rows | News column hidden entirely |
| Snapshot write fails | Logged via `app.log()`; retry next tick | Silent |
| Terminal too small (<60 cols) | App refuses to start | Friendly stderr message |

## 9. Testing Strategy

**TDD discipline:** clients, storage, and merge logic are written test-first. Widgets get smoke coverage only (visual fidelity is owned by Textual).

| File | Tested with | Key assertions |
|---|---|---|
| `test_clients_etoro.py` | `respx` mock | Headers correct; 200 parses to expected dict; 401 raises `EtoroAuthError` no-retry; 429 retries with backoff then raises `EtoroTransientError` |
| `test_clients_signals.py` | `tmp_path` CSV | Parses sample; mtime cache hit when unchanged; cache miss when mtime advances; missing file returns `{}` |
| `test_clients_census.py` | `tmp_path` JSONs | Picks newest by filename; aggregates PI% correctly; mtime cache invalidates on new file |
| `test_clients_news.py` | `tmp_path` SQLite | COUNT query correct; bucket cache hits within same hour; missing DB returns `None` |
| `test_storage.py` | `tmp_path` SQLite | Schema idempotent; round-trip insert+read; sparkline downsampling stride correct |
| `test_app_smoke.py` | `App.run_test()` pilot | App boots with injected fake state; table populates; `r` triggers fetch; `q` exits cleanly |

**Not tested:** live eToro integration (manual smoke after build); pixel-level widget rendering.

## 10. Dependencies & Setup

`pyproject.toml`:

```toml
[project]
name = "etoro-tui"
version = "0.1.0"
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
```

Setup:

```bash
cd ~/SourceCode/etoro-tui
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
# Auth already configured via etoro-trading plugin's env vars or Keychain.
etoro-tui
```

## 11. Open Questions

None. All design choices are committed. Implementation discoveries (exact CSV column name, exact news DB schema) are flagged as runtime detection rather than design unknowns.
