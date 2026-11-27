"""Entry point of the api container: serve the console and the Crosscut API.

The browser calls the API under /api and loads the single-page console from every
other path; settings arrive from the site env file, so one image fits every site.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from crosscut_api.app import create_app
from fastapi import FastAPI
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

ROOT_ENV = "CROSSCUT_ROOT"
CONSOLE_DIR_ENV = "CROSSCUT_CONSOLE_DIR"
LOG_LEVEL_ENV = "CROSSCUT_LOG_LEVEL"
DEFAULT_ROOT = Path("/var/lib/crosscut")
DEFAULT_CONSOLE_DIR = Path("/opt/crosscut/frontend/dist")
DEFAULT_LOG_LEVEL = "info"
CONTAINER_PORT = 8000
ALL_INTERFACES = "0.0.0.0"


def _env_path(name: str, default: Path) -> Path:
    """Return a path from the environment, or the default when it is unset."""
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


def _console_file(console_dir: Path, request_path: str) -> Path:
    """Return the built file for a URL path, or index.html for a client-side route."""
    # Resolve before the containment check so "../" cannot escape the build folder.
    candidate = (console_dir / request_path).resolve()
    if candidate.is_file() and console_dir.resolve() in candidate.parents:
        return candidate
    return console_dir / "index.html"


def build_app(data_root: Path, console_dir: Path) -> FastAPI:
    """Create the console app: API under /api, static build at every other path."""
    app = FastAPI(title="Crosscut console", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/api", create_app(data_root))
    app.mount("/assets", StaticFiles(directory=console_dir / "assets"), name="assets")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness probe; it checks only that the HTTP stack answers."""
        return {"status": "ok"}

    @app.get("/{request_path:path}")
    def console(request_path: str) -> FileResponse:
        """Serve a built file or the single-page-app entry point."""
        return FileResponse(_console_file(console_dir, request_path))

    return app


def main() -> None:
    """Start uvicorn on the container port."""
    data_root = _env_path(ROOT_ENV, DEFAULT_ROOT)
    console_dir = _env_path(CONSOLE_DIR_ENV, DEFAULT_CONSOLE_DIR)
    log_level = os.environ.get(LOG_LEVEL_ENV, DEFAULT_LOG_LEVEL)
    uvicorn.run(
        build_app(data_root, console_dir),
        host=ALL_INTERFACES,
        port=CONTAINER_PORT,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
