"""Health probe for the api, runtime and gateway containers.

The api probe asks its HTTP endpoint; the runtime and gateway check that their
state file was written recently. Exit 0 healthy, 1 unhealthy, 2 bad usage.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ROOT = Path("/var/lib/crosscut")
ROOT_ENV = "CROSSCUT_ROOT"
API_URL = "http://127.0.0.1:8000/healthz"
FRESH_FOR_S = 120.0
HTTP_TIMEOUT_S = 3.0
STATE_FILES = {
    "runtime": Path("_runtime") / "state.json",
    "gateway": Path("_gateway") / "state.json",
}


def _http_is_up(url: str) -> bool:
    """Return True when the URL answers with HTTP 200."""
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _state_is_fresh(root: Path, relative_path: Path, now: float) -> bool:
    """Return True when the state file exists and was written within FRESH_FOR_S."""
    try:
        age_s = now - (root / relative_path).stat().st_mtime
    except OSError:
        return False
    return age_s <= FRESH_FOR_S


def main(argv: list[str]) -> int:
    """Run the probe named in argv[0] and return the process exit code."""
    if len(argv) != 1 or (argv[0] != "api" and argv[0] not in STATE_FILES):
        print(f"usage: {Path(sys.argv[0]).name} api|runtime|gateway", file=sys.stderr)
        return 2
    if argv[0] == "api":
        return 0 if _http_is_up(API_URL) else 1
    root = Path(os.environ.get(ROOT_ENV, "").strip() or DEFAULT_ROOT)
    healthy = _state_is_fresh(root, STATE_FILES[argv[0]], time.time())
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
