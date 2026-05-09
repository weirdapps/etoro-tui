"""Entry point for `python -m etoro_tui` / `etoro-tui` / `etoro-tui setup`."""

from __future__ import annotations

import argparse
import logging
import sys

from . import config, storage
from .app import EtoroTuiApp

_DISCLAIMER = (
    "etoro-tui — unofficial. Not affiliated with eToro. Not financial advice. Use at your own risk."
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="etoro-tui",
        description="Live eToro portfolio TUI with intelligence overlays.",
        epilog=_DISCLAIMER,
    )
    p.add_argument(
        "--demo", action="store_true", help="Run with synthetic data (no API calls, no credentials)"
    )
    p.add_argument("--version", action="store_true", help="Print version and exit")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("setup", help="Interactive wizard to set up eToro API credentials")
    return p


def _run_demo() -> int:
    """Launch with synthetic state — bypasses credential check and live API."""
    from .demo import build_demo_indices, build_demo_state

    state = build_demo_state()
    app = EtoroTuiApp(initial_state=state, disable_polling=True)
    app._demo_indices = build_demo_indices()  # consumed in on_mount when present
    try:
        app.run()
    except KeyboardInterrupt:
        return 0
    return 0


def _setup_logging() -> None:
    """Route ALL logs to ~/.etoro-tui/etoro-tui.log, never to the terminal.

    A TUI repaints over the screen — anything written to stdout/stderr (httpx
    request lines, our own INFO logs) flashes briefly between Textual frames
    and looks like a glitch. Sending logs to a file keeps them available for
    debugging without painting the user's display.

    Uses RotatingFileHandler so the log can't grow unbounded — keeps the
    most recent 4 MB of history (1 MB × 4 files) and rotates older logs out.
    """
    from logging.handlers import RotatingFileHandler

    config.ensure_home_secure()  # 0o700 dir + 0o600 sensitive files
    log_path = config.ETORO_TUI_HOME / "etoro-tui.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,  # 1 MB per file
        backupCount=3,  # keep 3 rotated files (.1 / .2 / .3) → ~4 MB total
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Replace any prior handlers (e.g. from a previous basicConfig call) so
    # nothing else is still bound to stderr.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    # httpx is the chattiest at INFO (one line per request, ~5s tick) — pin
    # it to WARNING so the log file stays readable too.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Tighten the new log file to 0o600 (RotatingFileHandler creates with
    # default umask). No-op on Windows.
    try:
        log_path.chmod(0o600)
    except OSError:
        pass


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    _setup_logging()

    if args.version:
        from . import __version__

        print(f"etoro-tui {__version__}")
        return 0

    if args.command == "setup":
        from .setup_wizard import run_setup

        return run_setup()

    if args.demo:
        print(_DISCLAIMER, file=sys.stderr)
        return _run_demo()

    try:
        config.get_credentials()
    except config.AuthMissingError as e:
        print(f"etoro-tui: {e}", file=sys.stderr)
        print(
            "Tip: run `etoro-tui setup` for an interactive wizard, "
            "or `etoro-tui --demo` to try the UI without keys.",
            file=sys.stderr,
        )
        return 2

    try:
        storage.init_db(config.SNAPSHOT_DB_PATH).close()
    except OSError as e:
        print(f"etoro-tui: snapshot DB init failed: {e}", file=sys.stderr)
        return 3

    print(_DISCLAIMER, file=sys.stderr)
    try:
        EtoroTuiApp().run()
    except KeyboardInterrupt:
        return 0
    except Exception as e:  # noqa: BLE001 — top-level safety net
        print(f"etoro-tui: unexpected error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
