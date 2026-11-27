"""Command-line entry point: ``python -m crosscut_api --root <data root>`` (uvicorn, 127.0.0.1).

Starts the data API with the central rotating log file ``<root>/_logs/api.log`` (issue #170),
which the Administration > Health page exports.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from crosscut_runtime.logsetup import setup_file_logging

from crosscut_api.app import create_app


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, set up file logging and serve the API until stopped."""
    parser = argparse.ArgumentParser(prog="crosscut_api", description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="data root of the deployment")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    setup_file_logging("api", args.root)
    uvicorn.run(create_app(args.root), host=args.host, port=args.port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
