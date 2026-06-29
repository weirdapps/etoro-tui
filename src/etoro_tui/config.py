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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

# ---- baked-in defaults ----

ETORO_BASE_URL = "https://www.etoro.com/api/public"
WS_URL = "wss://ws.etoro.com/ws"
WS_ENABLED = True  # [websocket].enabled — false forces the pure-REST price path

# Refresh intervals (seconds). Override via TOML [intervals].
POLL_PORTFOLIO_S = 30
POLL_PORTFOLIO_IDLE_S = 600  # outside market hours
POLL_SIGNALS_S = 30
POLL_CENSUS_S = 60
SNAPSHOT_S = 60
RENDER_S = 1.5  # fast re-render cadence from the live WS price store

# Market-hours window (UTC, 0-23). Active polling uses POLL_PORTFOLIO_S;
# outside this window (and weekends) falls back to POLL_PORTFOLIO_IDLE_S.
MARKET_OPEN_UTC = 7  # covers European opens
MARKET_CLOSE_UTC = 22  # covers US regular close

# Local user data root.
ETORO_TUI_HOME = Path.home() / ".etoro-tui"
CONFIG_TOML = ETORO_TUI_HOME / "config.toml"
ENV_FILE = ETORO_TUI_HOME / ".env"
SNAPSHOT_DB_PATH = ETORO_TUI_HOME / "snapshots.db"
CACHE_DIR = ETORO_TUI_HOME / "cache"

# Sensitive files in ETORO_TUI_HOME (.env, snapshots.db, log) should be
# user-only readable. The cache contains only public data and stays default.
_SENSITIVE_FILES: tuple[str, ...] = (".env", "snapshots.db", "etoro-tui.log")


def ensure_home_secure() -> None:
    """Create ~/.etoro-tui/ with mode 0o700 + tighten any pre-existing
    sensitive files to 0o600. Called from app startup + setup wizard.

    POSIX-only: chmod is a no-op on Windows. Errors are swallowed silently
    because permission tightening is best-effort hardening, not a hard
    requirement for app function.
    """
    try:
        ETORO_TUI_HOME.mkdir(parents=True, exist_ok=True)
        # Tighten dir even if it already existed at default 0o755.
        ETORO_TUI_HOME.chmod(0o700)
    except OSError:
        return  # Windows or unusual filesystem — give up quietly.
    for name in _SENSITIVE_FILES:
        p = ETORO_TUI_HOME / name
        if p.exists():
            try:
                p.chmod(0o600)
            except OSError:
                pass


# Default overlay sources. The user can override paths via TOML; if a path
# doesn't exist locally, the corresponding client falls back to the GitHub
# raw URL (built into the clients themselves).
SIGNALS_CSV = Path.home() / "SourceCode" / "etorotrade" / "yahoofinance" / "output" / "etoro.csv"
SIGNALS_GITHUB_URL = (
    "https://raw.githubusercontent.com/weirdapps/etorotrade/main/yahoofinance/output/etoro.csv"
)

PORTFOLIO_CSV = (
    Path.home() / "SourceCode" / "etorotrade" / "yahoofinance" / "input" / "portfolio.csv"
)

CENSUS_GLOB_DIR = Path.home() / "SourceCode" / "etoro_census" / "archive" / "data"
CENSUS_GLOB_PATTERN = "etoro-data-*.json"
CENSUS_GITHUB_REPO = "weirdapps/etoro_census"  # <owner>/<repo>
CENSUS_GITHUB_BRANCH = "data-archive"
CENSUS_GITHUB_PATH = "data"  # path within the branch

# Default indices for the header bar, in priority order — the bar auto-fits as
# many as the terminal width allows, always keeping the first three. Each code
# must have a Yahoo index mapping in clients.yahoo._INDEX_TO_YAHOO (indices are
# priced from Yahoo, not the census). Override via TOML [indices].list.
DEFAULT_INDICES: tuple[tuple[str, str], ...] = (
    ("S&P 500", "SPX500"),
    ("Dow 30", "DJ30"),
    ("NASDAQ", "NSDQ100"),
    ("DAX", "GER40"),
    ("FTSE 100", "UK100"),
    ("EuroStx50", "EUSTX50"),
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


def get_instrument_overrides() -> dict[int, str]:
    """User-configurable instrument→symbol map from TOML [instruments].map.

    For instruments not in census (newly listed or unpopular), the user can
    add entries like `14710 = "9201.T"` so the position renders with the
    correct ticker, Yahoo prev-close, and signals coverage.
    """
    raw = _toml("instruments", "map", default=None)
    if not isinstance(raw, dict):
        return {}
    return {int(k): str(v) for k, v in raw.items()}


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
SIGNALS_CSV = _path_override("paths", "signals_csv", default=SIGNALS_CSV)
CENSUS_GLOB_DIR = _path_override("paths", "census_dir", default=CENSUS_GLOB_DIR)
SNAPSHOT_DB_PATH = _path_override("paths", "snapshot_db", default=SNAPSHOT_DB_PATH)

# Apply TOML interval overrides (after defaults are defined)
POLL_PORTFOLIO_S = _toml("intervals", "poll_portfolio", default=POLL_PORTFOLIO_S)
POLL_PORTFOLIO_IDLE_S = _toml("intervals", "poll_portfolio_idle", default=POLL_PORTFOLIO_IDLE_S)
POLL_SIGNALS_S = _toml("intervals", "poll_signals", default=POLL_SIGNALS_S)
SNAPSHOT_S = _toml("intervals", "snapshot", default=SNAPSHOT_S)
MARKET_OPEN_UTC = _toml("intervals", "market_open_utc", default=MARKET_OPEN_UTC)
MARKET_CLOSE_UTC = _toml("intervals", "market_close_utc", default=MARKET_CLOSE_UTC)
RENDER_S = _toml("intervals", "render", default=RENDER_S)
WS_ENABLED = _toml("websocket", "enabled", default=WS_ENABLED)


def is_market_active() -> bool:
    """True on weekdays when the current UTC hour is within the active window."""
    now = datetime.now(UTC)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return MARKET_OPEN_UTC <= now.hour < MARKET_CLOSE_UTC


# ---- credentials ----

CredSource = Literal["env", "envfile", "keyring"]


class AuthMissingError(RuntimeError):
    """Raised when no credential source supplies both keys."""


# Service / account names used in the system keyring. Match the legacy
# `security add-generic-password -a etoro-api -s etoro-{public,user}-key`
# names so users with existing macOS Keychain entries don't have to re-add.
KEYRING_ACCOUNT = "etoro-api"
KEYRING_SVC_PUBLIC = "etoro-public-key"
KEYRING_SVC_USER = "etoro-user-key"


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
            val = val.strip().strip('"').strip("'")
            out[key.strip()] = val
    except OSError:
        pass
    return out


_ENVFILE: dict[str, str] = _load_env_file()


def keyring_available() -> bool:
    """True if the optional `keyring` package is importable."""
    try:
        import keyring  # noqa: F401

        return True
    except ImportError:
        return False


def _keyring_lookup() -> tuple[str | None, str | None]:
    """Read both keys from the system keyring. Returns (None, None) on any failure."""
    try:
        import keyring
    except ImportError:
        return None, None
    try:
        pk = keyring.get_password(KEYRING_SVC_PUBLIC, KEYRING_ACCOUNT)
        uk = keyring.get_password(KEYRING_SVC_USER, KEYRING_ACCOUNT)
        return pk, uk
    except Exception:  # noqa: BLE001 — keyring backends raise diverse exceptions
        return None, None


def keyring_save(public_key: str, user_key: str) -> None:
    """Persist both keys to the system keyring. Caller checks keyring_available() first."""
    import keyring  # let ImportError propagate so the wizard can catch it

    keyring.set_password(KEYRING_SVC_PUBLIC, KEYRING_ACCOUNT, public_key)
    keyring.set_password(KEYRING_SVC_USER, KEYRING_ACCOUNT, user_key)


def get_credentials() -> tuple[str, str]:
    """Return (public_key, user_key). Resolution: env → .env file → keyring."""
    pk = os.environ.get("ETORO_PUBLIC_KEY") or _ENVFILE.get("ETORO_PUBLIC_KEY")
    uk = os.environ.get("ETORO_USER_KEY") or _ENVFILE.get("ETORO_USER_KEY")
    if not (pk and uk):
        kr_pk, kr_uk = _keyring_lookup()
        pk = pk or kr_pk
        uk = uk or kr_uk
    if not pk or not uk:
        suffix = " / system keyring" if keyring_available() else ""
        raise AuthMissingError(
            "ETORO_PUBLIC_KEY and ETORO_USER_KEY not found in env"
            f" / ~/.etoro-tui/.env{suffix}. Run `etoro-tui setup` to configure."
        )
    return pk, uk


def get_credentials_source() -> CredSource:
    """Report which source supplied the credentials currently in use."""
    if os.environ.get("ETORO_PUBLIC_KEY") and os.environ.get("ETORO_USER_KEY"):
        return "env"
    if _ENVFILE.get("ETORO_PUBLIC_KEY") and _ENVFILE.get("ETORO_USER_KEY"):
        return "envfile"
    return "keyring"
