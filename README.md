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
