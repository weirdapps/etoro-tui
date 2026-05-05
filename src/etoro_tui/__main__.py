"""Entry point for `python -m etoro_tui` / `etoro-tui` / `etoro-tui setup`."""
from __future__ import annotations

import argparse
import logging
import sys

from . import config, storage
from .app import EtoroTuiApp


_DISCLAIMER = (
    "etoro-tui — unofficial. Not affiliated with eToro. Not financial "
    "advice. Use at your own risk."
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="etoro-tui",
        description="Live eToro portfolio TUI with intelligence overlays.",
        epilog=_DISCLAIMER,
    )
    p.add_argument("--demo", action="store_true",
                   help="Run with synthetic data (no API calls, no credentials)")
    p.add_argument("--version", action="store_true", help="Print version and exit")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("setup", help="Interactive wizard to set up eToro API credentials")
    return p


def _run_demo() -> int:
    """Launch with synthetic state — bypasses credential check and live API."""
    from .demo import build_demo_state, build_demo_indices, build_demo_actions
    state = build_demo_state()
    indices = build_demo_indices()
    actions = build_demo_actions(state)
    app = EtoroTuiApp(initial_state=state, disable_polling=True)
    app._demo_indices = indices    # injected; consumed in on_mount when present
    app._demo_actions = actions
    try:
        app.run()
    except KeyboardInterrupt:
        return 0
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
        print("Tip: run `etoro-tui setup` for an interactive wizard, "
              "or `etoro-tui --demo` to try the UI without keys.",
              file=sys.stderr)
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
