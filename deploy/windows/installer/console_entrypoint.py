"""Serve the installed console and API in one Windows service.

Use the same /api mount as Docker while retaining rotating component logging.
"""

import argparse
from pathlib import Path

import uvicorn
from crosscut_api.app import create_app
from crosscut_runtime.logsetup import setup_file_logging
from fastapi import FastAPI
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

INSTALL_DIRECTORY = Path(__file__).resolve().parent
CONSOLE_DIRECTORY = INSTALL_DIRECTORY / "console"


def build_app(data_root: Path) -> FastAPI:
    """Mount the API and safely serve built files or a client-side route."""
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    application.mount("/api", create_app(data_root))
    application.mount("/assets", StaticFiles(directory=CONSOLE_DIRECTORY / "assets"))

    @application.get("/{request_path:path}")
    def console(request_path: str) -> FileResponse:
        """Resolve paths before checking containment to reject directory traversal."""
        candidate = (CONSOLE_DIRECTORY / request_path).resolve()
        if not candidate.is_file() or CONSOLE_DIRECTORY.resolve() not in candidate.parents:
            candidate = CONSOLE_DIRECTORY / "index.html"
        return FileResponse(candidate)

    return application


def main() -> None:
    """Start one loopback listener; use a site TLS proxy for remote access."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    arguments = parser.parse_args()
    setup_file_logging("api", arguments.root)
    uvicorn.run(build_app(arguments.root), host="127.0.0.1", port=8000, log_config=None)


if __name__ == "__main__":
    main()
