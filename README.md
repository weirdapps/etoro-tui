# etoro-tui

> Live eToro portfolio in your terminal. Bloomberg-style table with color-graded P&L, day-change, and inline indices.

[![ci](https://github.com/weirdapps/etoro-tui/actions/workflows/ci.yml/badge.svg)](https://github.com/weirdapps/etoro-tui/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

![etoro-tui screenshot: Bloomberg-style portfolio dashboard in the terminal](docs/screenshot.png)

*Screenshot captured in `--demo` mode (synthetic 8-position portfolio, no credentials required).*

## Overview

`etoro-tui` is a Textual-based terminal dashboard that reads a live eToro portfolio through the official read-only Public API, overlays open-source analyst signals and popular-investor census data, and paints the result as a single aggregated positions table. It is intended for personal use by a single eToro account holder on their own machine.

> [!IMPORTANT]
> ## Generate a READ-ONLY API key
>
> When you create your eToro Public API key (Settings, Trading, API Key Management), set the permission to `Read` only. Do not grant `Write`.
>
> - `etoro-tui` only ever calls read endpoints (`GET /portfolio`, `GET /market-data/instruments/rates`). Write access is never required.
> - With a read-only key, even if the credential leaks, an attacker cannot place trades, withdraw funds, or modify positions on your behalf. They only see what you would see.
> - The setup wizard reminds you of this at key-creation time. There is no "default to least privilege" toggle on eToro's side, so the choice is yours to make.

## What this tool does, and what it does not do

**Does:**

- Reads the live portfolio: positions, cash, equity, open P&L.
- Streams live prices via the eToro WebSocket (`wss://ws.etoro.com/ws`) with a REST poll fallback every 30 seconds. Price column shows the listing-currency quote; Value, Profit, and Allocation roll up in USD.
- Overlays analyst fundamentals (trailing / forward P/E, target upside, buy%, 3-month buy-% change) and BUY / HOLD / SELL signals from `weirdapps/etorotrade`.
- Overlays popular-investor holding rate from `weirdapps/etoro_census`.
- Displays yesterday's close and USD-adjusted day change from the census `priceData` payload.
- Stores 1-minute equity snapshots locally in `~/.etoro-tui/snapshots.db` for the header sparkline and today's baseline.

**Does NOT:**

- Place trades. Read-only endpoints, no exception.
- Deposit or withdraw funds. eToro Public API does not expose those endpoints.
- Modify stop-loss, take-profit, or any other order parameters.
- Send notifications, post to social, or share data with third parties.
- Store or transmit API keys anywhere except your local machine (env vars, `~/.etoro-tui/.env` at mode 600, or your OS keyring).
- Phone home. No telemetry, no analytics, no error reporting service.

## Features

- **Live prices via WebSocket.** `wss://ws.etoro.com/ws` streams price ticks in the background; the UI re-renders at ~1.5 s cadence. REST polling of `/portfolio` and `/market-data/instruments/rates` runs every 30 s during market hours (10 minutes off-hours and weekends).
- **Bloomberg-style color grading.** Three-tier intensity (bold bright, normal, dim) on Δday and Profit so magnitude reads at a glance. Magnitude-coded triangles (▲, ▴, ▾, ▼) encode direction and size in one glyph.
- **Honest day-change.** Δday computed from yesterday's close (census `priceData`) with FX-adjustment to USD, not lifetime return relabeled.
- **Parametric flex columns.** Table fills any terminal width via per-column minimum plus flex weights. Verified at 140, 180, 220, and 240 columns.
- **Inline header indices.** S&P 500, Dow 30, NASDAQ, DAX, FTSE 100, EuroStx50 (order + selection configurable). Up to 3 fit the top bar; the bar auto-fits based on terminal width.
- **Aggregated by ticker.** Multiple lots per symbol collapse into one row with weighted-average open and total P&L.
- **Fundamentals overlay.** Trailing / forward P/E, analyst target upside, % buy ratings, 3-month change in buy% (ΔBuy), popular-investor holding rate (PIs).
- **Honest labels.** "Δday" (today) is distinct from "Profit" (lifetime). Missing values render as "..." rather than fake zeros.
- **Local-first with GitHub fallback.** If you have `weirdapps/etorotrade` and `weirdapps/etoro_census` cloned under `~/SourceCode/`, the local files are used directly; otherwise, the public GitHub raw / Contents API is consulted and results are cached under `~/.etoro-tui/cache/`.
- **Single-line footer.** Key legend, current sort, last-fetch, status. The table is the dashboard.

## Install

Requires Python 3.13+.

From the [latest GitHub Release](https://github.com/weirdapps/etoro-tui/releases/latest) wheel:

```bash
pipx install https://github.com/weirdapps/etoro-tui/releases/download/v0.4.0/etoro_tui-0.4.0-py3-none-any.whl
```

From source (editable, with dev extras and OS-keyring support):

```bash
git clone https://github.com/weirdapps/etoro-tui.git
cd etoro-tui
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
```

The `keyring` dependency is already declared in the core install (no extra required).

## Credentials

Credentials resolve in priority order: **environment variables, then `~/.etoro-tui/.env`, then the system keyring.** The setup wizard picks the best storage option available on your platform.

### Per-platform credential storage

| Platform | Backend | Just works? | Notes |
|---|---|---|---|
| macOS | Keychain | Yes | Keys appear in Keychain Access under service `etoro-public-key` / `etoro-user-key`, account `etoro-api`. |
| Windows | Credential Manager | Yes | Keys appear in Control Panel, Credential Manager, Generic Credentials. Persists across logins. |
| Linux desktop (GNOME / KDE) | Secret Service, GNOME Keyring, KWallet | Usually | Needs an unlocked keyring. First call may prompt for the keyring password. |
| Linux headless / SSH / Docker | n/a | No | No D-Bus, so keyring fails. Wizard falls back to `~/.etoro-tui/.env` (chmod 600). |
| CI / GitHub Actions | n/a | n/a | Inject `ETORO_PUBLIC_KEY` / `ETORO_USER_KEY` as repository secrets. Env vars take priority. |

If `keyring` fails on Linux without D-Bus, the app still works via env vars or the `.env` file. The wizard detects what is available and offers the right options.

### Setup wizard

```bash
etoro-tui setup
```

Walks you through:

1. **Generating an eToro API key.** Settings, Trading, API Key Management. Set the permission to `Read` only. Copy both keys immediately; eToro shows the user-key only once.
2. **Pasting both keys.** Public Key and User Key.
3. **Choosing where to store them.** `~/.etoro-tui/.env` file (chmod 600), system keyring, or a printout of `export` lines for your shell profile.
4. **Optionally seeding `~/.etoro-tui/config.toml`** from the documented template at [`docs/config.example.toml`](docs/config.example.toml).

If credentials already exist, the wizard offers to either keep them (and only change where they are stored) or rotate them.

### Without the wizard

```bash
export ETORO_PUBLIC_KEY="..."
export ETORO_USER_KEY="..."
```

Or write the same lines to `~/.etoro-tui/.env`:

```bash
mkdir -p ~/.etoro-tui
chmod 700 ~/.etoro-tui
cat > ~/.etoro-tui/.env <<EOF
ETORO_PUBLIC_KEY=...
ETORO_USER_KEY=...
EOF
chmod 600 ~/.etoro-tui/.env
```

## Usage

```bash
etoro-tui             # launch the dashboard
etoro-tui --demo      # preview the UI with synthetic data (no credentials needed)
etoro-tui --version   # print version and exit
etoro-tui setup       # interactive credential wizard
```

Logs go to `~/.etoro-tui/etoro-tui.log` (httpx pinned to WARNING, rotated at 4 MB total across 4 files). Tail it if you need to debug an auth or rate-limit issue.

### Key bindings

| Key | Action |
|---|---|
| `s` | Cycle sort order |
| `/` | Filter rows by symbol substring |
| `Esc` | Clear filter |
| `r` | Refresh now (bypass poll timer) |
| `?` | Help modal (column docs + data freshness) |
| `q` / `Ctrl-C` | Quit |

Row navigation follows the standard Textual `DataTable` bindings (arrow keys, PageUp / PageDown, Home / End).

## Configuration

Optional file at `~/.etoro-tui/config.toml`. Every section is optional; missing keys fall back to baked-in defaults. See [`docs/config.example.toml`](docs/config.example.toml) for the full template.

```toml
[indices]
# Header bar auto-fits as many as the terminal width allows.
# The default list already includes 6 indices in priority order.
list = [
  ["S&P 500",   "SPX500"],
  ["Dow 30",    "DJ30"],
  ["NASDAQ",    "NSDQ100"],
  ["DAX",       "GER40"],
  ["FTSE 100",  "UK100"],
  ["EuroStx50", "EUSTX50"],
]

[paths]
# Override only if you keep local copies of the public datasets outside their defaults:
# signals_csv = "~/SourceCode/etorotrade/yahoofinance/output/etoro.csv"
# census_dir  = "~/SourceCode/etoro_census/archive/data"

[intervals]
# All values are seconds; commented lines show the baked-in defaults.
# poll_portfolio      = 30
# poll_portfolio_idle = 600
# poll_signals        = 30
# snapshot            = 60
# render              = 1.5
# market_open_utc     = 7
# market_close_utc    = 22

[websocket]
# enabled = true    # false forces the pure-REST price path
```

## Data sources

| Source | What it provides | Refresh cadence |
|---|---|---|
| `wss://ws.etoro.com/ws` | Streaming price ticks per position | live (WebSocket) |
| `https://www.etoro.com/api/public/api/v1/trading/info/portfolio` | Open positions and cash balance | 30 s (10 min off-hours) |
| `https://www.etoro.com/api/public/api/v1/market-data/instruments/rates` | Last / bid / ask and FX rates | 30 s (10 min off-hours) |
| [`weirdapps/etorotrade`](https://github.com/weirdapps/etorotrade) `etoro.csv` | Analyst signals, P/E, upside, buy%, 3-month buy-% change | daily (~22:00 UTC) |
| [`weirdapps/etoro_census`](https://github.com/weirdapps/etoro_census) `etoro-data-*.json` | Popular-investor holding rate, yesterday's close | daily |
| Yahoo Finance (index quotes) | Header index prices via `yfinance` | 30 min TTL |

Local files (if you have the source repos cloned under `~/SourceCode/`) take priority. Otherwise the daily-refreshed datasets are pulled from the GitHub raw URL / Contents API and cached under `~/.etoro-tui/cache/`.

A 1-minute equity snapshot is written to `~/.etoro-tui/snapshots.db` for the header sparkline and today's baseline.

### Architecture

```
src/etoro_tui/
├── __main__.py          entry point: CLI, logging setup, disclaimer
├── app.py               Textual App: timers, AppState, key bindings
├── models.py            frozen dataclasses
├── config.py            TOML + env + keyring credential resolution
├── storage.py           SQLite equity snapshots + retention
├── demo.py              --demo synthetic data
├── setup_wizard.py      `etoro-tui setup`
├── styles.tcss          Textual CSS
├── clients/
│   ├── etoro.py         async REST client with retry + backoff
│   ├── price_stream.py  async WebSocket price ticker
│   ├── yahoo.py         Yahoo index quotes (TTL cache)
│   ├── signals.py       etorotrade CSV (local, GitHub fallback)
│   ├── census.py        etoro_census JSON (local, GitHub Contents API)
│   └── remote_fetch.py  stdlib urllib + `~/.etoro-tui/cache/`
└── widgets/
    ├── header.py            single-row equity, indices, clock, status
    ├── positions_table.py   parametric flex-column DataTable
    ├── footer.py            key legend + sort + status
    └── help_modal.py
```

Strict layering: `clients/` does I/O only, `widgets/` does rendering only, `app.py` is the only module that imports both.

### Column widths are parametric

Each column has a minimum inner width (hard floor) and a flex weight (proportion of leftover terminal width). On mount and on terminal resize, `compute_widths(available)` distributes spare space proportionally so the table fills your screen (verified at 140, 180, 220, and 240 columns). Profit, Value, and Price get higher weights because their numbers benefit from breathing room; PET, PIs, Buy%, and ΔBuy get lower weights because those values are 4 to 5 characters and would look sparse otherwise.

## Security hardening

The "does / does not" section and the "read-only key" note above capture the design-time scope contract. This section documents the implementation hardening layered on top.

**Personal portfolio dashboard. Single-user, runs locally on your machine.**

What is hardened:

- Sensitive files in `~/.etoro-tui/` (`snapshots.db`, `.env`, `etoro-tui.log`) are written at mode `0o600`; the directory itself is `0o700`. POSIX-only; Windows users should rely on user-account isolation or the system keyring instead of the `.env` file.
- `.env` writes use `os.open(O_CREAT|O_EXCL, mode=0o600)` to avoid TOCTOU.
- HTTPS hardcoded, no plaintext fallback.
- All SQL queries parameterized.
- httpx logs pinned to WARNING (no request URLs, no headers in the log file).
- File-only logging with rotation (1 MB per file, 4 files kept, ~4 MB total).
- CI runs `ruff`, `pip-audit`, and `gitleaks` on every push and PR.
- Pre-commit `gitleaks` hook (custom rules in [`.gitleaks.toml`](.gitleaks.toml)) blocks committing secrets locally; the same scan runs in CI as a backstop.
- GitHub native secret scanning and push protection enabled on this repo.
- Dependabot enabled for `uv` and GitHub Actions.

What is **not** done:

- No third-party security audit.
- No penetration testing.
- No certificate pinning.
- Single maintainer (bus factor 1).
- No SLSA provenance or signed releases.

If your threat model requires any of these, do not run `etoro-tui` in that environment. Vulnerability reports: see [`SECURITY.md`](SECURITY.md).

## Disclaimer

**Unofficial open-source tool. Not affiliated with eToro.**
**Not financial advice. Use at your own risk.**

Numbers shown may differ from your eToro app; verify in the official platform before any trading decision. Common reasons for small discrepancies:

- FX conversion uses the rate at position-open time for the cost basis (a few percent drift over months); current value uses live FX.
- Census prices update once daily and are used as fallback when live rates fail.
- Open P&L excludes realized profit (eToro's "Total P&L" includes both).

## Development

```bash
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"

pytest -v                         # full test suite
ruff check .                      # lint
ruff format --check .             # format check
python -m etoro_tui --demo        # smoke-test the UI
```

CI runs on Python 3.13 against Ubuntu and macOS for every push and PR (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)). The test job is gated on the secret scan, lint, and vulnerability audit passing.

### Pre-commit secret scanning

The repo ships a `gitleaks` pre-commit hook (custom rules in [`.gitleaks.toml`](.gitleaks.toml)) that blocks any commit containing API keys or account-fingerprint dollar amounts. Install once after cloning:

```bash
pip install pre-commit
pre-commit install
```

The same scan also runs in CI as a backstop on every push and PR.

## Contributing

Issues and PRs welcome. Areas where contributions would land cleanly:

- More built-in indices (FTSE 250, ASX 200, KOSPI, and similar).
- Localized number formatting (EUR-style `1.234,56`).
- Additional fundamentals columns (dividend yield, ROE, debt / equity are already in the source CSV).
- Per-row hover popup with a full position dossier.

## License

MIT. See [LICENSE](LICENSE).
