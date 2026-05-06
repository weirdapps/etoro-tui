# Changelog

All notable changes to **etoro-tui** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
