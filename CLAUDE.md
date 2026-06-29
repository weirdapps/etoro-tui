# etoro-tui

Bloomberg-style terminal dashboard (TUI) for a live eToro portfolio. Shows positions with P&L, day-change, analyst fundamentals, and market indices. Read-only — no trading. Published on PyPI.

## Tech Stack

- Python 3.13+ (required)
- Textual >=0.86 (TUI framework), httpx (async HTTP), yfinance, keyring
- uv for dependency management (`uv.lock`), hatchling build
- ruff (lint + format), pytest + pytest-asyncio + respx

## Running

```bash
uv pip install -e .
etoro-tui                    # live mode (requires credentials)
etoro-tui --demo             # synthetic 8-position portfolio, no credentials needed
etoro-tui setup              # interactive credential wizard
```

Credentials resolve in order: env vars > `~/.etoro-tui/.env` (chmod 600) > system keyring.

## Testing

```bash
pytest -v                    # ~54 tests, ~1s runtime
```

## Code Organization

```
src/etoro_tui/
├── __main__.py
├── app.py                  ← Textual App, 5s poll timers, AppState, key bindings
├── models.py               ← frozen dataclasses (Position, AccountSummary, IndexSummary)
├── config.py               ← TOML + env vars + keyring credential resolution
├── storage.py              ← SQLite snapshots at ~/.etoro-tui/snapshots.db (1-min equity)
├── demo.py                 ← --demo mode with synthetic data
├── setup_wizard.py         ← `etoro-tui setup` interactive wizard
├── styles.tcss             ← Textual CSS
├── clients/
│   ├── etoro.py            ← async REST client (eToro Public API, retry+backoff)
│   ├── signals.py          ← etorotrade CSV reader (local → GitHub fallback)
│   ├── census.py           ← etoro_census JSON reader (local → GitHub fallback, 6h cache)
│   ├── yahoo.py            ← yfinance wrapper
│   └── remote_fetch.py     ← stdlib urllib + 6h cache at ~/.etoro-tui/cache/
└── widgets/
    ├── header.py           ← equity + indices + clock + status bar
    ├── positions_table.py  ← parametric flex-column DataTable
    ← footer.py            ← key legend + sort indicator
    └── help_modal.py
tests/
├── conftest.py
├── test_app_logic.py / test_app_smoke.py
├── test_clients_{census,etoro,signals,yahoo}.py
├── test_config.py / test_models.py / test_storage.py / test_widgets_header.py
```

## Architecture Rules (strict layering)

- `clients/` — I/O only, no rendering
- `widgets/` — rendering only, no I/O
- `app.py` — only file that imports both layers

## Data Sources

- Live prices + portfolio: eToro Public API, polled every 5s
- Analyst fundamentals: `etorotrade` CSV + `etoro_census` JSON (daily refresh)
- Local files take priority; GitHub raw is a 6h-cached fallback

## eToro API

Canonical domain: `https://www.etoro.com/api/public/v1`
Legacy alias: `https://www.etoro.com/api/public/v1` (works but not canonical)
Auth: X-API-KEY + X-USER-KEY (regular, not PERSONAL) + X-REQUEST-ID (UUID) + User-Agent

## Column Sort Cycle

Value → Profit → Δday → Upside → Buy% → PEF → Signal → Symbol

## CI

- `ci.yml`: 4 jobs — gitleaks secrets scan → ruff lint/format → pip-audit CVE scan → pytest matrix (ubuntu + macos, Python 3.13)
- `sonarcloud.yml`: pytest --cov → SonarCloud scan

## Key Conventions

- Line length: 100 chars
- ruff rules: E, F, W, I, B, UP
- Logs: `~/.etoro-tui/etoro-tui.log` (WARNING level, 4 MB rotation)
- Columns fill any terminal width (parametric widths, verified at 140–240 cols)
- `[keyring]` optional extra for OS-native credential storage
