# etoro-tui

> Live eToro portfolio in your terminal — positions, fundamentals, signals, and indices on one screen.

[![ci](https://github.com/weirdapps/etoro-tui/actions/workflows/ci.yml/badge.svg)](https://github.com/weirdapps/etoro-tui/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![pypi](https://img.shields.io/pypi/v/etoro-tui.svg)](https://pypi.org/project/etoro-tui/)

```text
$100,000.00   ▲ +$500 (+0.26%) today  ▁▂▃▅▆▇   Cash $20K   P&L +$5K   14:23  ●live
─────────────────────────────────────────────────────────────────────────────────────────
Symbol   Last      Δ%    Value $   % Eq    P&L $    PE-T  PE-F   Up%   Buy%  PI%  Sig │ Portfolio overview
GOOG    381.01  +29.26    20,000   9.4%  +2,000    29.0  26.6   +3.4   100%  35%  HOLD│   ...
AMZN    273.07  +33.70    77,291   8.5%  +19,481    32.5  27.5  +13.5   100%  37%  BUY │ Top 5 holdings
MSFT    409.42   −8.03    72,194   7.9%   −5,419    24.6  21.4  +35.6    96%  44%  BUY │   ...
NVDA    197.34  +51.91    62,283   6.8%  +21,225    40.5  17.7  +35.6   100%  35%  BUY │
…                                                                                       │ ─────────────────
                                                                                        │ Indices
                                                                                        │   S&P 500   5,432.10  +0.34%
                                                                                        │   NASDAQ   17,234.52  +0.45%
                                                                                        │   Dow 30   40,123.45  −0.21%
                                                                                        │ ─────────────────
                                                                                        │ Actions
                                                                                        │   ✚ Buy   5  AGI, EMAAR.AE +3
                                                                                        │   + Add  10  AMZN, NVDA +8
                                                                                        │   = Hold 16  GOOG, AAPL +14
                                                                                        │   - Trim  2  AMD, NKE
─────────────────────────────────────────────────────────────────────────────────────────
[↑↓] select  [⏎] detail  [s] sort  [/] filter  [r] refresh  [?] help  [q] quit  by Value ↓  prices ● live  updated 4s ago
```

## Features

- **Live prices** — eToro `/market-data/instruments/rates` polled every 5s, FX-corrected to USD across all exchanges (London pence, Hong Kong dollars, Danish kroner, etc.)
- **Aggregated by ticker** — many lots per symbol collapsed into one row with weighted-avg open and total P&L
- **Fundamentals** — trailing/forward P/E, analyst target upside, % buy ratings, popular-investor holding rate
- **Indices snapshot** — S&P 500, NASDAQ, Dow, Euro Stoxx 50, ATHEX (configurable) with daily change
- **Actions snapshot** — Buy / Add / Hold / Trim / Sell buckets derived from etorotrade signals
- **Honest labels** — "Last" not "Now"; "Δ% since open" not "today's change"; help modal documents every refresh cadence
- **Portfolio overview** — top holdings, currency mix, biggest movers, all visible at a glance
- **Local-first, GitHub-fallback** for the daily-refreshed data sources (no scraping, no API keys for census/signals)

## Install

```bash
pipx install etoro-tui
# Optional: cross-platform credential storage (macOS Keychain / Windows Credential Manager / Linux Secret Service)
pipx inject etoro-tui keyring
```

Or with `uv`:

```bash
uv tool install etoro-tui
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

## Setup

Run the interactive wizard:

```bash
etoro-tui setup
```

It walks you through:

1. **Generating an eToro API key** — Settings → Trading → API Key Management. Copy both keys *immediately*; eToro shows the user-key only once.
2. **Pasting both keys** — Public Key and User Key.
3. **Choosing where to store them** — `~/.etoro-tui/.env`, system keyring, or just printed `export` commands.
4. **(Optional) seeding `~/.etoro-tui/config.toml`** from the documented template at [`docs/config.example.toml`](docs/config.example.toml).

If you already have credentials configured, the wizard offers to either keep the existing keys (and just change where they're stored) or rotate them.

### Without the wizard

Set environment variables in your shell profile:

```bash
export ETORO_PUBLIC_KEY="..."
export ETORO_USER_KEY="..."
```

## Usage

```bash
etoro-tui            # launch the dashboard
etoro-tui --demo     # preview the UI with synthetic data — no credentials needed
etoro-tui --version
```

### Key bindings

| Key | Action |
|---|---|
| `↑` `↓` | Move row selection |
| `Enter` | Toggle detail panel for selected position |
| `s` | Cycle sort: Value → P&L → Δ% → Upside → Buy% → PE-F → Symbol → Signal |
| `/` | Filter rows by symbol substring; `Esc` clears |
| `r` | Refresh now (bypass the 5s timer) |
| `?` | Help modal (also shows column docs + data freshness) |
| `q` / `Ctrl-C` | Quit |

## Configuration

Optional file at `~/.etoro-tui/config.toml`. Every section is optional; missing keys fall back to baked-in defaults. See [`docs/config.example.toml`](docs/config.example.toml) for the full template.

```toml
[indices]
list = [
  ["S&P 500",   "SPX500"],
  ["NASDAQ",    "NSDQ100"],
  ["Dow 30",    "DJ30"],
  ["DAX",       "GER40"],
  ["FTSE",      "UK100"],
  ["Nikkei",    "JPN225"],
]

[paths]
# Override if you have local copies of the public datasets:
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
│   ├── news.py         ← optional news.db (private; silently disabled if absent)
│   └── remote_fetch.py ← stdlib urllib + ~/.etoro-tui/cache/
└── widgets/
    ├── header.py
    ├── positions_table.py
    ├── detail_panel.py
    ├── footer.py
    └── help_modal.py
```

Strict layering: `clients/` does I/O only, `widgets/` does rendering only, `app.py` is the only place that imports both.

## Disclaimer

**Unofficial open-source tool. Not affiliated with eToro.**
**Not financial advice. Use at your own risk.**

Numbers shown may differ from your eToro app — verify in the official platform before any trading decision. Common reasons for small discrepancies:

- FX conversion uses the rate at position-open time (a few percent drift over months)
- Census prices update once daily (used as fallback when live rates fail)
- Open P&L excludes realized profit (eToro's "Total P&L" includes both)

## Contributing

Issues and PRs welcome. Before opening a PR:

```bash
uv pip install -e ".[dev]"
pytest                           # 47 tests, ~1s
python -m etoro_tui --demo       # smoke-test the UI
```

CI runs on Python 3.13 against Ubuntu + macOS for every push and PR.

Areas where contributions would land cleanly:

- More built-in indices (FTSE 250, ASX 200, KOSPI…)
- Linux/Windows-specific install instructions
- Localized number formatting (EUR-style 1.234,56)
- Additional fundamentals columns (dividend yield, ROE, debt/equity — already in the source CSV)

## License

MIT — see [LICENSE](LICENSE).
