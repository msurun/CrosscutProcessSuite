"""Shared helpers for the auth route tests: a fake clock, seeded users and request helpers.

Test-only configuration uses a cheap scrypt cost so that hashing stays fast.
Imported by sibling test modules as ``from auth_support import ...``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crosscut_api.auth.deps import CSRF_HEADER
from crosscut_api.auth.passwords import ScryptParams, hash_password
from crosscut_api.auth.sessions import AuthConfig
from crosscut_api.auth.store import JsonUserStore, new_user_record
from crosscut_api.auth_routes import build_auth_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

START_TIME = 1_800_000_000.0
TEST_CONFIG = AuthConfig(scrypt=ScryptParams(n=1024))
PASSWORD = "correct horse 1"
DEFAULT_USERS: dict[str, list[str]] = {
    "admin1": ["admin"],
    "admin2": ["admin"],
    "op1": ["operator"],
    "eng1": ["engineer"],
    "view1": ["viewer"],
}


class FakeClock:
    """Callable clock that only moves when ``advance`` is called."""

    def __init__(self, start: float = START_TIME) -> None:
        """Start the clock at ``start`` POSIX seconds."""
        self.now = start

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the fake time forward by ``seconds``."""
        self.now += seconds


def seed_users(root: Path, specs: dict[str, list[str]], password: str = PASSWORD) -> None:
    """Write a users file under ``root`` with one account per username and its roles."""
    users = [
        new_user_record(
            username,
            username,
            roles,
            hash_password(password, TEST_CONFIG.scrypt),
            START_TIME,
        )
        for username, roles in specs.items()
    ]
    JsonUserStore(root).write_all(users)


def make_app(root: Path, clock: FakeClock) -> FastAPI:
    """Create a FastAPI app that serves only the auth router over ``root``."""
    app = FastAPI()
    app.include_router(build_auth_router(root, TEST_CONFIG, clock))
    return app


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, Any]:
    """Log ``username`` in through ``POST /auth/login`` and return the session payload."""
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def csrf(payload: dict[str, Any]) -> dict[str, str]:
    """Return the request header that carries the CSRF token of a session payload."""
    return {CSRF_HEADER: payload["csrf"]}


def stepup(
    client: TestClient,
    payload: dict[str, Any],
    password: str = PASSWORD,
) -> None:
    """Re-verify the password through ``POST /auth/stepup`` and assert success."""
    response = client.post(
        "/auth/stepup",
        json={"password": password},
        headers=csrf(payload),
    )
    assert response.status_code == 200, response.text
