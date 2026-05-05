"""Entry point: `python -m etoro_tui` or `etoro-tui`."""
from __future__ import annotations

import logging
import sys

from . import config, storage
from .app import EtoroTuiApp


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        # Validate credentials before launching the UI so the error message
        # is visible in the terminal, not buried in the TUI.
        config.get_credentials()
    except config.AuthMissingError as e:
        print(f"etoro-tui: {e}", file=sys.stderr)
        return 2
    try:
        # Pre-flight the snapshot DB so disk/permissions issues surface here.
        storage.init_db(config.SNAPSHOT_DB_PATH).close()
    except OSError as e:
        print(f"etoro-tui: snapshot DB init failed: {e}", file=sys.stderr)
        return 3
    try:
        EtoroTuiApp().run()
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"etoro-tui: unexpected error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
