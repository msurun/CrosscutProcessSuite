"""Command-line entry point: ``python -m crosscut_runtime --root <data root>``.

Runs the runtime service until SIGINT or SIGTERM, then marks it stopped in the state file.
"""

from __future__ import annotations

import argparse
import signal
import threading
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

from crosscut_runtime.service import serve


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of the runtime command."""
    parser = argparse.ArgumentParser(prog="crosscut_runtime", description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="data root of the deployment")
    parser.add_argument(
        "--interval", type=float, default=1.0, help="seconds between service passes"
    )
    return parser


def _install_stop_handlers(stop_event: threading.Event) -> None:
    """Make SIGINT and SIGTERM set the stop event instead of killing the process."""

    def request_stop(signum: int, frame: FrameType | None) -> None:
        """Signal handler: ask the service loop to finish its current pass."""
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, install the stop handlers and run the service."""
    args = build_parser().parse_args(argv)
    stop_event = threading.Event()
    _install_stop_handlers(stop_event)
    serve(args.root, args.interval, stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
