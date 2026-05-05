"""Credentials, file paths, refresh intervals — fed by user TOML + env.

Resolution order for any setting:
    1. user TOML at ~/.etoro-tui/config.toml (whatever's defined wins)
    2. environment variable (for credentials + a few path overrides)
    3. baked-in defaults below

Cross-platform: env-only credentials, optional file-based supplement
(`~/.etoro-tui/.env` written by `etoro-tui setup`). No macOS Keychain
dependency — keeps the binary portable across Linux, macOS, Windows.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

# ---- baked-in defaults ----

ETORO_BASE_URL = "https://public-api.etoro.com"

# Refresh intervals (seconds). Override via TOML [intervals].
POLL_PORTFOLIO_S = 5
POLL_SIGNALS_S = 30
POLL_CENSUS_S = 60
POLL_NEWS_S = 300
SNAPSHOT_S = 60

# Local user data root.
ETORO_TUI_HOME = Path.home() / ".etoro-tui"
CONFIG_TOML = ETORO_TUI_HOME / "config.toml"
ENV_FILE = ETORO_TUI_HOME / ".env"
SNAPSHOT_DB_PATH = ETORO_TUI_HOME / "snapshots.db"
CACHE_DIR = ETORO_TUI_HOME / "cache"

# Default overlay sources. The user can override paths via TOML; if a path
# doesn't exist locally, the corresponding client falls back to the GitHub
# raw URL (built into the clients themselves). News is local-only — no
# public mirror — and is silently skipped when the DB isn't present.
SIGNALS_CSV = Path.home() / "SourceCode" / "etorotrade" / "yahoofinance" / "output" / "etoro.csv"
SIGNALS_GITHUB_URL = (
    "https://raw.githubusercontent.com/weirdapps/etorotrade/main/yahoofinance/output/etoro.csv"
)

CENSUS_GLOB_DIR = Path.home() / "SourceCode" / "etoro_census" / "archive" / "data"
CENSUS_GLOB_PATTERN = "etoro-data-*.json"
CENSUS_GITHUB_REPO = "weirdapps/etoro_census"      # <owner>/<repo>
CENSUS_GITHUB_BRANCH = "data-archive"
CENSUS_GITHUB_PATH = "data"                         # path within the branch

NEWS_DB_PATH = Path(os.environ.get(
    "NEWS_READER_DB",
    str(Path.home() / "SourceCode" / "news" / "data" / "news.db"),
))

# Default indices for the side panel. Override via TOML [indices].list.
DEFAULT_INDICES: tuple[tuple[str, str], ...] = (
    ("S&P 500",   "SPX500"),
    ("NASDAQ",    "NSDQ100"),
    ("Dow 30",    "DJ30"),
    ("EuroStx50", "EUSTX50"),
    ("Greek ETF", "LYXGRE.DE"),
)


# ---- TOML loading ----

def _load_toml() -> dict[str, Any]:
    """Best-effort TOML read; returns {} on missing/malformed file."""
    if not CONFIG_TOML.exists():
        return {}
    try:
        import tomllib  # Python 3.11+ stdlib
    except ImportError:
        return {}
    try:
        return tomllib.loads(CONFIG_TOML.read_text())
    except (OSError, ValueError):
        return {}


_TOML: dict[str, Any] = _load_toml()


def _toml(*keys: str, default: Any = None) -> Any:
    """Walk a dotted-key path through the loaded TOML. Returns default if missing."""
    node: Any = _TOML
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node


def get_indices() -> tuple[tuple[str, str], ...]:
    """User-configurable index list from TOML [indices].list = [["Name", "SYMBOL"], ...]."""
    raw = _toml("indices", "list", default=None)
    if not isinstance(raw, list):
        return DEFAULT_INDICES
    out: list[tuple[str, str]] = []
    for entry in raw:
        if isinstance(entry, list) and len(entry) >= 2:
            out.append((str(entry[0]), str(entry[1])))
    return tuple(out) if out else DEFAULT_INDICES


def _path_override(*keys: str, default: Path) -> Path:
    raw = _toml(*keys)
    return Path(raw).expanduser() if isinstance(raw, str) else default


# Apply TOML path overrides (after defaults are defined)
SIGNALS_CSV     = _path_override("paths", "signals_csv",     default=SIGNALS_CSV)
CENSUS_GLOB_DIR = _path_override("paths", "census_dir",      default=CENSUS_GLOB_DIR)
NEWS_DB_PATH    = _path_override("paths", "news_db",         default=NEWS_DB_PATH)
SNAPSHOT_DB_PATH = _path_override("paths", "snapshot_db",    default=SNAPSHOT_DB_PATH)


# ---- credentials ----

CredSource = Literal["env", "envfile"]


class AuthMissingError(RuntimeError):
    """Raised when env vars are absent and ~/.etoro-tui/.env doesn't supply them."""


def _load_env_file() -> dict[str, str]:
    """Read KEY=VAL pairs from ~/.etoro-tui/.env. Quietly tolerates missing/bad."""
    if not ENV_FILE.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            # Strip optional surrounding quotes.
            val = val.strip().strip('"').strip("'")
            out[key.strip()] = val
    except OSError:
        pass
    return out


_ENVFILE: dict[str, str] = _load_env_file()


def get_credentials() -> tuple[str, str]:
    """Return (public_key, user_key). Env first, then ~/.etoro-tui/.env."""
    pk = os.environ.get("ETORO_PUBLIC_KEY") or _ENVFILE.get("ETORO_PUBLIC_KEY")
    uk = os.environ.get("ETORO_USER_KEY")   or _ENVFILE.get("ETORO_USER_KEY")
    if not pk or not uk:
        raise AuthMissingError(
            "Set ETORO_PUBLIC_KEY and ETORO_USER_KEY environment variables, "
            "or run `etoro-tui setup` to write them to ~/.etoro-tui/.env."
        )
    return pk, uk


def get_credentials_source() -> CredSource:
    """Report whether credentials came from process env or the .env file."""
    if os.environ.get("ETORO_PUBLIC_KEY") and os.environ.get("ETORO_USER_KEY"):
        return "env"
    return "envfile"
