# Changelog

All notable changes to **etoro-tui** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Bloomberg-style table** — vertical `│` dividers between cells, magnitude-coded
  triangles (▲▴▾▼) for Δday, 3-tier colour gradient (bold bright / normal / dim)
  on Δday and Profit so magnitude pops at a glance, refined cyan/navy cursor.
- **Parametric flex columns** — each column has a `min_inner` floor and a
  `flex_weight`. `compute_widths(available_chars)` distributes leftover terminal
  width proportionally. Verified at 140 / 180 / 220 / 240 cols. Re-flows on
  terminal resize via `on_resize` handler.
- **Δday column** — honest day-change computed from yesterday's close
  (census `priceData`, FX-adjusted to USD), not lifetime return relabeled.
  Sortable via the new `day_change_pct` sort key.
- **Inline indices in header** — up to 3 indices (S&P / NDX / DOW) render in
  the header bar with squashed names + colour-coded change. Replaces the
  sidebar indices block.
- **Right-anchored clock + status** — header is now two sections: portfolio
  data flush left, clock + status dot anchored to the right edge via 1fr filler.
- **`prev_close` field on Position** — populated from census `currentPrice`
  × current FX. Enables the new Δday column and "Today's movers" detail.
- **`_overlay_fields()` helper** — single source of truth for the overlay-kwargs
  dict (signal, pi_pct, PE, upside, buy %, target). `_to_position` and
  `_tick_overlays` both call it so the two paths can never drift.
- **File-based logging** — all logs route to `~/.etoro-tui/etoro-tui.log`.
  httpx pinned to WARNING. Stops HTTP request URLs from flashing on the
  screen between Textual repaints.
- **Defensive `.gitignore`** — adds `.env`, `.env.*`, `*.envfile`, `.etoro-tui/`,
  `*.key`, `*.pem`, `credentials.*`, `secrets.*` so a stray credential file
  can never be staged accidentally.
- **`tests/test_app_logic.py`** — unit tests for `_overlay_fields`,
  `_to_position` price-fallback paths, and `_day_change_pct` formatter.

### Changed

- **Single-panel layout** — table spans the full terminal width. The right
  detail panel was removed (see below). Column count: 12.
- **Header has no `│` dividers** — replaced with whitespace gaps for a cleaner
  scan path. Status indicator is now a coloured dot only (no "live" / "slow"
  text label).
- **`_build_indices` applies FX** — same `conversionRateAsk` as `_to_position`,
  so EUR-quoted instruments (`LYXGRE.DE`, `EuroStx50`) match the USD prices
  shown in the portfolio table. Previously the same instrument could show two
  different prices in the two panels.
- **`_to_position` price selection** — replaced the lazy `or` chain with
  explicit `None` / `0.0` checks. Walks live keys (`lastExecution` → `Bid` →
  `bid`) accepting the first `> 0` value. All-missing → census fallback,
  never crashes on `float(None)`.
- **Column header alignment** — refactored cell rendering so the `│` divider
  is always at column position 0 and the value is right-padded within the
  remaining width. Previously `justify="right"` on the whole `"│ value"`
  string caused the divider to drift between rows of different value widths.
- **CHANGELOG / README** rewritten for the new layout and per-platform
  credentials story.

### Removed

- **`widgets/detail_panel.py`** (~320 lines) — relied on data sources
  (etorotrade signals + census PIs) that don't work for shared users without
  the original repos cloned. Functionality replaced by:
  - Indices → moved to header bar
  - Per-position dossier → not replaced (the table itself shows the same
    fundamentals as columns)
  - Portfolio overview / Today's movers → removed
  - Buy / Add / Hold / Trim / Sell action buckets → removed
- **`ActionsSummary` dataclass** + `_build_actions()` function (no consumer left).
- **`Enter` / `toggle_detail` key binding** (no panel to toggle).
- **`PositionsTable.PositionSelected` consumer** in `app.py` (the message is
  still emitted; no handler currently acts on it).
- **`clients/news.py`** + `tests/test_clients_news.py` (~123 lines) —
  `news_24h` / `news_anomaly` were never displayed after the detail panel was
  removed. `NEWS_DB_PATH` and `POLL_NEWS_S` removed from `config.py`. News
  fields removed from `Position`, `_OverlayKwargs`, `_overlay_fields`,
  `_to_position`, `_aggregate_by_symbol`, `EtoroTuiApp.__init__`, and
  `demo.py`. Test count: 60 → 54 (only news-specific tests removed).

### Fixed

- **"Today's movers" detail** previously showed biggest **lifetime** gainer/loser
  using `pnl_pct`; now uses real day-change via `prev_close`. Falls back to
  "(awaiting census prev_close)" when no positions have a baseline.
- **Stale `styles.tcss` docstring** that claimed a 2-row header (it's 1 row).

### Security

- **`gitleaks` integration** — pre-commit hook + CI job that scans every
  commit and PR for secrets (default ruleset) plus custom patterns for
  account-fingerprint dollar amounts and any future PII drift. Config in
  [`.gitleaks.toml`](.gitleaks.toml). Local install:
  `pip install pre-commit && pre-commit install`.
- **README + header docstring mockups** redacted to clearly synthetic
  round numbers (`$100,000.00`, `Cash $20K`, `EXAMPLE1..5` tickers) so the
  rendered example never resembles a real account snapshot.

## [0.2.0] — 2026-05-06

First public release. Hardens the project for distribution on PyPI and GitHub.

### Added

- **MIT license** + disclaimer banner at startup and in the help modal.
- **`etoro-tui --demo`** — boots the UI with an 8-position synthetic portfolio so
  prospective users can preview the dashboard without any credentials or API call.
- **`etoro-tui setup`** — interactive wizard for first-time configuration. Walks
  through generating eToro keys, pasting them, and choosing a storage backend
  (`~/.etoro-tui/.env`, system keyring, or printed `export` commands). When
  credentials already exist, offers a 3-way prompt (keep current keys / rotate /
  cancel) instead of always pushing the rotation flow.
- **Optional `keyring` extra** for cross-platform credential storage:
  macOS Keychain, Windows Credential Manager, and Linux Secret Service. Install
  with `pipx inject etoro-tui keyring` (or `pip install etoro-tui[keyring]`).
  Service names match the legacy `security add-generic-password` entries so
  existing macOS Keychain users don't need to re-add anything.
- **GitHub fallbacks** for daily-refreshed data sources. New users no longer
  need to clone `weirdapps/etorotrade` or `weirdapps/etoro_census` locally —
  the clients fall back to GitHub raw URLs / Contents API and cache results in
  `~/.etoro-tui/cache/` for 6 hours.
- **TOML configuration** at `~/.etoro-tui/config.toml`. Customise the indices
  list and override paths to local data sources. Template at
  [`docs/config.example.toml`](docs/config.example.toml).
- **CI workflow** — pytest on Python 3.13 across Ubuntu and macOS for every
  push and PR, plus a TUI boot smoke test in demo mode.
- **PyPI-ready packaging** — hatchling build backend, classifiers, keywords,
  project URLs, sdist include rules, optional extras (`dev`, `keyring`).

### Changed

- **Credential resolution chain** is now `env → ~/.etoro-tui/.env → keyring`
  (previously: macOS Keychain shellout only). Cross-platform from day one.
- **README** rewritten for a public audience — badges, ASCII layout mockup,
  install paths (pipx / uv / source), data-source table with refresh cadences,
  architecture file tree, contributing notes.
- **Help modal** documents every column with its refresh cadence, lists
  fallback behaviour, and shows live data freshness for census + signals.

### Removed

- macOS Keychain shellout (`security add-generic-password`). The same keychain
  is still reachable via the new optional `keyring` extra.

### Fixed

- `etoro-tui setup` no longer pushes the user through "get new keys" when
  they already have working credentials and just want to change storage.
- Test suite reaches 47 tests, all passing in ~1s. Bypasses the dev box's real
  keyring entries when verifying the `AuthMissingError` path.

## [0.1.0] — 2026-05-05

Initial implementation. Not released to PyPI.

### Added

- Async eToro REST client (`public-api.etoro.com/api/v1/...`) with retry +
  exponential backoff. Live polling of `/trading/info/portfolio` and
  `/market-data/instruments/rates` every 5 seconds.
- **Aggregated-by-ticker** position rows — many lots per symbol collapsed
  into one row with weighted-average open price and total P&L.
- **FX correction** for non-USD positions: prices in pence (London),
  Hong Kong dollars, Danish kroner, etc. converted via per-position
  `openConversionRate`.
- **Fundamentals overlay** from `weirdapps/etorotrade` CSV — trailing P/E,
  forward P/E, analyst upside, % buy ratings, BUY/SELL/HOLD signal.
- **Popular-investor holding rate** (PI%) from `weirdapps/etoro_census` JSON.
- **Indices snapshot** — S&P 500, NASDAQ, Dow 30, Euro Stoxx 50, Greek ETF
  with daily change.
- **Actions snapshot** — Buy / Add / Hold / Trim / Sell buckets with full
  ticker lists, derived from etorotrade signals + current portfolio.
- **Detail panel** with two modes: portfolio overview + per-position dossier.
- **1-minute equity snapshots** to `~/.etoro-tui/snapshots.db` for the header
  baseline and "today's Δ" calculation.
- **Key bindings**: ↑/↓ select, Enter detail, `s` cycle sort, `/` filter,
  `r` refresh now, `?` help, `q` quit.
- **Right-aligned numeric columns** with explicit DataTable widths for
  pixel-perfect visual alignment.

[Unreleased]: https://github.com/weirdapps/etoro-tui/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/weirdapps/etoro-tui/releases/tag/v0.2.0
[0.1.0]: https://github.com/weirdapps/etoro-tui/releases/tag/v0.1.0
