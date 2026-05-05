"""Tiny GitHub-fallback fetcher used by the signals + census readers.

Strategy: if the configured local path exists, the reader uses it (the
project author runs the dev box this way). Otherwise, fetch the file from
a GitHub raw URL and cache it under ~/.etoro-tui/cache/. Subsequent runs
re-use the cache for up to `max_age_seconds`.

No third-party deps — uses urllib.request from the stdlib so users don't
have to install anything extra to get the public datasets.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import config

log = logging.getLogger(__name__)

_USER_AGENT = "etoro-tui/0.1 (+https://github.com/weirdapps/etoro-tui)"


def _ensure_cache_dir() -> Path:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.CACHE_DIR


def _http_get(url: str, timeout: float = 10.0) -> bytes | None:
    """GET bytes or None on any error. Sets a UA header (GitHub returns 403 without one)."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT,
                                               "Accept": "application/vnd.github.v3+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.warning("remote fetch failed %s: %s", url, e)
        return None


def fetch_to_cache(
    url: str,
    cache_name: str,
    max_age_seconds: int = 6 * 3600,
) -> Path | None:
    """Return a cached local path for `url`. Re-fetches if the cache file is
    older than `max_age_seconds`. Returns None if the fetch fails AND we
    have no usable cached copy.
    """
    cache_path = _ensure_cache_dir() / cache_name
    fresh = (
        cache_path.exists()
        and (time.time() - cache_path.stat().st_mtime) < max_age_seconds
    )
    if fresh:
        return cache_path
    body = _http_get(url)
    if body is not None:
        cache_path.write_bytes(body)
        return cache_path
    # Fetch failed — fall back to whatever's already cached, even if stale.
    return cache_path if cache_path.exists() else None


def fetch_newest_census_file() -> Path | None:
    """Find the newest etoro-data-*.json on the data-archive branch and cache it.

    Two HTTP calls: list the branch directory via the GitHub Contents API,
    pick the newest filename, then fetch its raw content.
    """
    api_url = (
        f"https://api.github.com/repos/{config.CENSUS_GITHUB_REPO}"
        f"/contents/{config.CENSUS_GITHUB_PATH}"
        f"?ref={config.CENSUS_GITHUB_BRANCH}"
    )
    listing = _http_get(api_url)
    if listing is None:
        return None
    try:
        items: list[dict[str, Any]] = json.loads(listing)
    except (ValueError, TypeError):
        return None
    json_files = [it for it in items
                  if isinstance(it, dict)
                  and it.get("type") == "file"
                  and isinstance(it.get("name"), str)
                  and it["name"].startswith("etoro-data-")
                  and it["name"].endswith(".json")]
    if not json_files:
        return None
    # Filenames embed YYYY-MM-DD-HH-MM, sorted lex == sorted chronologically.
    json_files.sort(key=lambda it: it["name"])
    newest = json_files[-1]
    download_url = newest.get("download_url")
    if not download_url:
        return None
    # Cache by filename so we don't re-download yesterday's file as today's.
    return fetch_to_cache(download_url, newest["name"], max_age_seconds=6 * 3600)
