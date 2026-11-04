"""Test helper that builds the Crosscut API app with authentication disabled.

Used by the API test modules as a fixture factory.
"""

from pathlib import Path

from crosscut_api.app import create_app
from fastapi import FastAPI


def create_app_without_auth(data_root: Path) -> FastAPI:
    """Build the API app with authentication disabled (test fixtures only)."""
    return create_app(data_root, auth_enabled=False)
