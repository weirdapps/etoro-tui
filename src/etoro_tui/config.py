"""Credentials lookup, file paths, refresh intervals."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

ETORO_BASE_URL = "https://public-api.etoro.com"

# Refresh intervals (seconds)
POLL_PORTFOLIO_S = 5
POLL_SIGNALS_S = 30
POLL_CENSUS_S = 60
POLL_NEWS_S = 300
SNAPSHOT_S = 60   # every minute — populates sparklines faster (was 300/5min)

# Paths (all absolute)
SNAPSHOT_DB_PATH = Path.home() / ".etoro-tui" / "snapshots.db"
SIGNALS_CSV = Path.home() / "SourceCode" / "etorotrade" / "yahoofinance" / "output" / "etoro.csv"
CENSUS_GLOB_DIR = Path.home() / "SourceCode" / "etoro_census" / "archive" / "data"
CENSUS_GLOB_PATTERN = "etoro-data-*.json"
NEWS_DB_PATH = Path(
    os.environ.get(
        "NEWS_READER_DB",
        str(Path.home() / "SourceCode" / "news" / "data" / "news.db"),
    )
)

CredSource = Literal["env", "keychain"]


class AuthMissingError(RuntimeError):
    """Raised when neither env vars nor keychain provide credentials."""


def _keychain_lookup(service: str) -> str | None:
    """Read a generic password from macOS Keychain. Returns None if not found."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", "etoro-api", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_credentials() -> tuple[str, str]:
    """Return (public_key, user_key). Env first, then macOS Keychain."""
    pk = os.environ.get("ETORO_PUBLIC_KEY") or _keychain_lookup("etoro-public-key")
    uk = os.environ.get("ETORO_USER_KEY") or _keychain_lookup("etoro-user-key")
    if not pk or not uk:
        raise AuthMissingError(
            "Set ETORO_PUBLIC_KEY and ETORO_USER_KEY env vars, or store them "
            "in macOS Keychain under service names "
            "'etoro-public-key' / 'etoro-user-key' (account 'etoro-api')."
        )
    return pk, uk


def get_credentials_source() -> CredSource:
    """Report whether credentials came from env or keychain (for ? help modal)."""
    if os.environ.get("ETORO_PUBLIC_KEY") and os.environ.get("ETORO_USER_KEY"):
        return "env"
    return "keychain"
