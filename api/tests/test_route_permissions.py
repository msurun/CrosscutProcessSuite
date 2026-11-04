"""Route permission enforcement with authentication enabled.

Checks that the app-level enforcer agrees with ROUTE_PERMISSIONS and PUBLIC_ROUTES and
refuses anonymous, under-privileged, CSRF-less and step-up-less requests.
Uses the shared helpers from ``auth_support``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, csrf, login, seed_users, stepup
from crosscut_api.app import create_app
from crosscut_api.auth.roles import load_roles
from crosscut_api.auth.route_permissions import (
    AUTHENTICATED,
    PUBLIC_ROUTES,
    ROUTE_PERMISSIONS,
    AnyOf,
    Requirement,
)
from fastapi import FastAPI
from fastapi.routing import APIRoute, _IncludedRouter
from fastapi.testclient import TestClient

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PROTECTED_KEYS = sorted(ROUTE_PERMISSIONS)
VIEWER_PERMISSIONS = load_roles(None).permissions_for(["viewer"])


def _route_id(key: tuple[str, str]) -> str:
    """Return a readable pytest id such as ``"GET /datasets"``."""
    return f"{key[0]} {key[1]}"


def _concrete_path(path: str) -> str:
    """Replace each ``{placeholder}`` in a route template with a dummy value."""
    return re.sub(r"\{[^}]+\}", "sample", path)


def _satisfied(requirement: Requirement, permissions: frozenset[str]) -> bool:
    """Return True when ``permissions`` meets ``requirement``."""
    if requirement == AUTHENTICATED:
        return True
    if isinstance(requirement, AnyOf):
        return any(permission in permissions for permission in requirement.permissions)
    return requirement in permissions


def _viewer_denied_keys() -> list[tuple[str, str]]:
    """Return the mutating routes whose requirement a viewer does not satisfy."""
    return sorted(
        key
        for key, requirement in ROUTE_PERMISSIONS.items()
        if key[0] in MUTATING_METHODS and not _satisfied(requirement, VIEWER_PERMISSIONS)
    )


VIEWER_DENIED_KEYS = _viewer_denied_keys()


def _route_pairs(routes: list[Any]) -> Iterator[tuple[str, str]]:
    """Yield every (method, path) served, descending into included routers."""
    for route in routes:
        if isinstance(route, _IncludedRouter):
            for context in route.effective_route_contexts():
                yield from ((method.upper(), context.path) for method in context.methods or ())
        elif isinstance(route, APIRoute):
            yield from ((method, route.path) for method in route.methods)


def _served_routes(app: FastAPI) -> set[tuple[str, str]]:
    """Return every (method, path) pair the app serves."""
    return set(_route_pairs(app.routes))


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a data root whose users file holds one account per role."""
    path = tmp_path_factory.mktemp("route_permissions")
    seed_users(path, {**DEFAULT_USERS, "lead1": ["lead"]})
    return path


@pytest.fixture(scope="module")
def app(root: Path) -> FastAPI:
    """Return the app with authentication enabled over the seeded root."""
    return create_app(root, auth_config=TEST_CONFIG)


@pytest.fixture(scope="module")
def viewer(app: FastAPI) -> tuple[TestClient, dict[str, Any]]:
    """Return a client logged in as the viewer, with the login payload."""
    client = TestClient(app)
    return client, login(client, "view1")


def test_route_table_matches_served_routes(app: FastAPI) -> None:
    """Every served route is mapped and every mapped entry is served."""
    served = _served_routes(app)
    mapped = set(ROUTE_PERMISSIONS) | set(PUBLIC_ROUTES)
    assert sorted(served - mapped) == []
    assert sorted(mapped - served) == []


@pytest.mark.parametrize(
    ("method", "path"), PROTECTED_KEYS, ids=[_route_id(key) for key in PROTECTED_KEYS]
)
def test_protected_route_without_session_is_401(app: FastAPI, method: str, path: str) -> None:
    """A request with no session is refused with 401 before any permission check."""
    response = TestClient(app).request(method, _concrete_path(path))
    assert response.status_code == 401


def test_uninitialised_root_returns_503(tmp_path: Path) -> None:
    """Without a users file a protected read answers 503 instead of data."""
    app = create_app(tmp_path, auth_config=TEST_CONFIG)
    response = TestClient(app).get("/datasets")
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("method", "path"),
    VIEWER_DENIED_KEYS,
    ids=[_route_id(key) for key in VIEWER_DENIED_KEYS],
)
def test_viewer_is_forbidden_on_mutating_routes(
    viewer: tuple[TestClient, dict[str, Any]], method: str, path: str
) -> None:
    """A viewer with a valid CSRF token gets 403 on mutating routes it lacks permission for."""
    client, payload = viewer
    response = client.request(method, _concrete_path(path), headers=csrf(payload))
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"


def test_intake_check_without_csrf_is_forbidden(app: FastAPI) -> None:
    """A state-changing request from a logged-in operator without CSRF gets 403."""
    client = TestClient(app)
    login(client, "op1")
    response = client.post("/intake/check")
    assert response.status_code == 403
    assert response.json()["detail"] == "csrf token missing or invalid"


def test_kill_reset_needs_stepup_then_reaches_gateway(app: FastAPI) -> None:
    """lead1 gets 428 without a recent step-up, and 503 (no gateway) after one."""
    client = TestClient(app)
    payload = login(client, "lead1")
    first = client.post("/gateway/kill/reset", headers=csrf(payload))
    assert first.status_code == 428
    assert first.json()["detail"] == "step_up_required"
    stepup(client, payload)
    second = client.post("/gateway/kill/reset", headers=csrf(payload))
    assert second.status_code == 503


def test_health_is_public(app: FastAPI) -> None:
    """GET /health answers 200 without any session."""
    response = TestClient(app).get("/health")
    assert response.status_code == 200


def test_login_with_wrong_password_is_401(app: FastAPI) -> None:
    """POST /auth/login with a wrong password is refused with 401."""
    body = {"username": "admin1", "password": "wrong pass 1"}
    response = TestClient(app).post("/auth/login", json=body)
    assert response.status_code == 401


def test_viewer_can_list_datasets(viewer: tuple[TestClient, dict[str, Any]]) -> None:
    """A logged-in viewer reads GET /datasets with 200."""
    client, _ = viewer
    response = client.get("/datasets")
    assert response.status_code == 200
