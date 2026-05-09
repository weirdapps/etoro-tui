# etoro-tui

> Live eToro portfolio in your terminal — Bloomberg-style table with color-graded P&L, day-change, and inline indices.

[![ci](https://github.com/weirdapps/etoro-tui/actions/workflows/ci.yml/badge.svg)](https://github.com/weirdapps/etoro-tui/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![pypi](https://img.shields.io/pypi/v/etoro-tui.svg)](https://pypi.org/project/etoro-tui/)

```text
$100,000.00 ▲+0.01%   Cash $20K   P&L +$5K   ▆▅▅▆▆▆▇▇   S&P 5,432 ▲+0.34%   NDX 17,234 ▲+0.45%   DOW 40,123 ▼-0.21%        14:23 EEST  ●
 SYMBOL    │ Price    │ Δday      │ Value    │ Alloc  │ Profit    │ PET   │ PEF   │ Upside  │ Buy %  │ PIs   │ Signal
 GOOG      │  397.01  │ ▴-0.01%   │  20,000  │  8.8%  │  +2,000  │ 30.3  │ 27.4  │  +3.6%  │ 100%   │ 35%   │ HOLD
 AMZN      │  272.63  │ ▼-0.02%   │  15,000  │  7.6%  │  +1,500  │ 32.7  │ 27.6  │ +14.0%  │ 100%   │ 36%   │ BUY
 MSFT      │  415.06  │ ▼-0.01%   │  10,000  │  7.2%  │   -500  │ 24.7  │ 21.4  │ +35.4%  │  96%   │ 44%   │ BUY
 NVDA      │  215.13  │ ▼-0.03%   │  5,000  │  6.7%  │  +1,000  │ 43.8  │ 19.1  │ +25.1%  │ 100%   │ 35%   │ BUY
 TSLA      │  198.80  │ ▼-3.12%   │   2,500  │  0.9%  │     −848  │ 72.4  │ 64.1  │ -12.3%  │  30%   │ 18%   │ SELL
 …
[↑↓] select  [s] sort  [/] filter  [r] refresh  [?] help  [q] quit                                  by Value ↓  prices ● live  updated 4s ago
```

## Features

- **Live prices** — eToro `/market-data/instruments/rates` polled every 5s, FX-corrected to USD across all exchanges (London pence, Hong Kong dollars, Danish kroner, etc.)
- **Bloomberg-style colour grading** — 3-tier intensity (bold bright / normal / dim) on Δday and Profit so magnitude pops at a glance. Magnitude-coded triangles (▲▴▾▼) for direction-and-size in one glyph.
- **Honest day-change** — Δday computed from yesterday's close (census `priceData`) FX-adjusted to USD, not lifetime return relabeled
- **Parametric flex columns** — table fills any terminal width via per-column min + flex weights. Verified at 140 / 180 / 220 / 240 cols.
- **Inline header indices** — S&P 500, NASDAQ, Dow 30 (FX-converted to USD for consistency with portfolio rows). Up to 3 fit in the bar.
- **Aggregated by ticker** — many lots per symbol collapsed into one row with weighted-avg open and total P&L
- **Fundamentals** — trailing/forward P/E, analyst target upside, % buy ratings, popular-investor holding rate
- **Honest labels** — "Δday" not "Δ%"; "Profit" is lifetime, "Δday" is today; "—" when census coverage is missing rather than fake zeros
- **Local-first, GitHub-fallback** for the daily-refreshed data sources (no scraping, no API keys for census/signals)
- **Single-line footer** — key legend + sort + last-fetch + status. No detail panel; the table IS the dashboard.

## Install

```bash
pipx install etoro-tui                       # env vars or .env file only
pipx install "etoro-tui[keyring]"            # adds OS keyring support
```

Or with `uv`:

```bash
uv tool install etoro-tui
uv tool install "etoro-tui[keyring]"         # with keyring
```

Or from source:

```bash
git clone https://github.com/weirdapps/etoro-tui.git
cd etoro-tui
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev,keyring]"
```

Requires Python 3.13+.

## Credentials

Keys are read in priority order: **environment variables → `~/.etoro-tui/.env` file → system keyring**. The setup wizard picks the best storage option for your platform.

### Per-platform credential storage

| Platform | Backend (with `[keyring]` extra) | Just works? | Notes |
|---|---|---|---|
| **macOS** | Keychain | ✅ | Keys appear in Keychain Access under service `etoro-public-key` / `etoro-user-key`. |
| **Windows** | Credential Manager | ✅ | Keys appear in Control Panel → Credential Manager → Generic Credentials. Persists across logins. |
| **Linux desktop** (GNOME/KDE) | Secret Service / GNOME Keyring / KWallet | ⚠️ | Needs an unlocked keyring. First call may prompt for the keyring password. |
| **Linux headless / SSH / Docker** | n/a | ❌ | No D-Bus → keyring fails. Wizard automatically falls back to `~/.etoro-tui/.env` (chmod 600). |
| **CI / GitHub Actions** | n/a | n/a | Inject `ETORO_PUBLIC_KEY` / `ETORO_USER_KEY` as repository secrets — env vars take priority. |

If `keyring` isn't installed (or fails on Linux without D-Bus), the app still works — just use env vars or the `.env` file. The wizard detects what's available and offers the right options.

### Setup wizard

```bash
etoro-tui setup
```

It walks you through:

1. **Generating an eToro API key** — Settings → Trading → API Key Management. Copy both keys *immediately*; eToro shows the user-key only once.
2. **Pasting both keys** — Public Key and User Key.
3. **Choosing where to store them** — `~/.etoro-tui/.env` file (chmod 600), system keyring (if `[keyring]` extra installed and available), or just print `export` commands for your shell profile.
4. **(Optional) seeding `~/.etoro-tui/config.toml`** from the documented template at [`docs/config.example.toml`](docs/config.example.toml).

If you already have credentials configured, the wizard offers to either keep them (and just change where they're stored) or rotate them.

### Without the wizard

```bash
export ETORO_PUBLIC_KEY="..."
export ETORO_USER_KEY="..."
```

…or write the same lines to `~/.etoro-tui/.env`:

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
etoro-tui            # launch the dashboard
etoro-tui --demo     # preview the UI with synthetic data — no credentials needed
etoro-tui --version
```

Logs go to `~/.etoro-tui/etoro-tui.log` (httpx requests pinned to WARNING). Tail it if you need to debug an auth or rate-limit issue.

### Key bindings

| Key | Action |
|---|---|
| `↑` `↓` | Move row selection |
| `s` | Cycle sort: Value → Profit → Δday → Upside → Buy % → PEF → Signal → Symbol |
| `/` | Filter rows by symbol substring; `Esc` clears |
| `r` | Refresh now (bypass the 5s timer) |
| `?` | Help modal (column docs + data freshness) |
| `q` / `Ctrl-C` | Quit |

## Configuration

Optional file at `~/.etoro-tui/config.toml`. Every section is optional; missing keys fall back to baked-in defaults. See [`docs/config.example.toml`](docs/config.example.toml) for the full template.

```toml
[indices]
# Up to 3 indices fit in the header. Set order = priority.
list = [
  ["S&P 500",   "SPX500"],
  ["NASDAQ",    "NSDQ100"],
  ["Dow 30",    "DJ30"],
  ["DAX",       "GER40"],
  ["FTSE",      "UK100"],
]

[paths]
# Override only if you have local copies of the public datasets:
# signals_csv = "~/SourceCode/etorotrade/yahoofinance/output/etoro.csv"
# census_dir  = "~/SourceCode/etoro_census/archive/data"
```

## How it works

| Source | What it provides | Refresh |
|---|---|---|
| `public-api.etoro.com /api/v1/trading/info/portfolio` | open positions + cash | live (5s poll) |
| `public-api.etoro.com /api/v1/market-data/instruments/rates` | last/bid/ask + FX rates | live (5s poll) |
| [`weirdapps/etorotrade`](https://github.com/weirdapps/etorotrade) `etoro.csv` | analyst signals + P/E + upside + buy% | daily (~22:00 UTC) |
| [`weirdapps/etoro_census`](https://github.com/weirdapps/etoro_census) `etoro-data-*.json` | popular-investor holdings + close prices | daily (~03:00 UTC) |

Local files (if you have the source repos cloned) take priority; otherwise the daily-refreshed sources are pulled from GitHub raw / Contents API and cached in `~/.etoro-tui/cache/` for 6 hours.

A 1-minute equity snapshot is written to `~/.etoro-tui/snapshots.db` for the header sparkline and "today's Δ" baseline.

### Architecture

```
src/etoro_tui/
├── app.py              ← Textual App: timers, AppState, key bindings
├── models.py           ← Frozen dataclasses
├── config.py           ← TOML + env + keyring credential resolution
├── storage.py          ← SQLite snapshots
├── demo.py             ← --demo synthetic data
├── setup_wizard.py     ← `etoro-tui setup`
├── clients/
│   ├── etoro.py        ← async REST with retry + backoff
│   ├── signals.py      ← etorotrade CSV (local → GitHub fallback)
│   ├── census.py       ← etoro_census JSON (local → GitHub Contents API)
│   └── remote_fetch.py ← stdlib urllib + ~/.etoro-tui/cache/
└── widgets/
    ├── header.py       ← single-row equity + indices + clock + status
    ├── positions_table.py  ← parametric flex-column DataTable
    ├── footer.py       ← key legend + sort + status
    └── help_modal.py
```

Strict layering: `clients/` does I/O only, `widgets/` does rendering only, `app.py` is the only place that imports both.

### Column widths are parametric

Each column has a **minimum inner width** (hard floor) and a **flex weight** (proportion of leftover terminal width). On mount and on terminal resize, `compute_widths(available)` distributes the spare space proportionally so the table fills your screen — verified working at 140, 180, 220, and 240 cols. Profit / Value / Price get higher weights because their numbers benefit from breathing room; PET / PIs / Buy % get lower weights because their values are 4–5 chars and look weird with lots of trailing space.

## Security & Scope

**Personal portfolio dashboard. Single-user, runs locally on your machine.**

The eToro Public API endpoints used here are **read-only** — `GET /portfolio` and `GET /market-data/instruments/rates`. The app **never** sends trade orders, never deposits, never withdraws. A leaked API key grants visibility into your portfolio, equity, and P&L history — but not the ability to trade on your behalf. When you generate the key, set permission to **Read** (Write is unnecessary).

What's hardened:

- Sensitive files in `~/.etoro-tui/` (`snapshots.db`, `.env`, `etoro-tui.log`) are written with mode `0o600`; the directory is `0o700`. POSIX-only — Windows users should rely on user-account isolation or the system keyring instead of the `.env` file
- `.env` writes use `os.open(O_CREAT|O_EXCL, mode=0o600)` to avoid TOCTOU
- HTTPS hardcoded; no plaintext fallback
- All SQL queries parameterized
- httpx logs pinned to WARNING (no request URLs / no headers in the log file)
- File logging only — never to terminal — with rotation (4 MB cap)
- CI runs `ruff` + `pip-audit` on every push and PR
- Dependabot enabled for `pip` + GitHub Actions

What's **not** done:

- No third-party security audit
- No penetration testing
- No certificate pinning
- Single maintainer (bus factor 1)
- No SLSA provenance or signed releases on PyPI

If your threat model requires any of these, **do not run etoro-tui in that environment.** Vulnerability reports: see [`SECURITY.md`](SECURITY.md).

## Disclaimer

**Unofficial open-source tool. Not affiliated with eToro.**
**Not financial advice. Use at your own risk.**

Numbers shown may differ from your eToro app — verify in the official platform before any trading decision. Common reasons for small discrepancies:

- FX conversion uses the rate at position-open time for the cost basis (a few percent drift over months); current value uses live FX
- Census prices update once daily (used as fallback when live rates fail)
- Open P&L excludes realized profit (eToro's "Total P&L" includes both)

## Contributing

Issues and PRs welcome. Before opening a PR:

```bash
uv pip install -e ".[dev]"
pytest                           # 54 tests, ~1s
python -m etoro_tui --demo       # smoke-test the UI
```

CI runs on Python 3.13 against Ubuntu + macOS for every push and PR.

Areas where contributions would land cleanly:

- More built-in indices (FTSE 250, ASX 200, KOSPI…)
- Localized number formatting (EUR-style 1.234,56)
- Additional fundamentals columns (dividend yield, ROE, debt/equity — already in the source CSV)
- Per-row hover/popup with full position dossier (the old DetailPanel was removed because it relied on local-only data; a hover-only variant could work for everyone)

## License

MIT — see [LICENSE](LICENSE).
