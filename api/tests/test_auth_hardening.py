"""Hardening tests for auth routes: lockout, rate limit, enumeration and timing.

Tests 1-8 describe intended behaviour and fail until the source is hardened; test 9 guards
``actor_of`` and should already pass. Shared helpers come from ``auth_support``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from auth_support import (
    DEFAULT_USERS,
    PASSWORD,
    FakeClock,
    csrf,
    login,
    make_app,
    seed_users,
)
from crosscut_api.auth import passwords
from crosscut_api.auth.actor import ActorContext, actor_of
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

NEW_PASSWORD = "battery staple 42"
WRONG_PASSWORD = "wrong pass 1"
LOCK_WAIT_S = 301
LOGIN_TRACE_ATTEMPTS = 7
VARIANT_NAMES = ["Admin1", " admin1", "ADMIN1 ", "admin1", "admin1"]
GHOST_NAMES = ["Ghost", " ghost", "GHOST ", "ghost", "Ghost"]


@pytest.fixture
def clock() -> FakeClock:
    """Return a fake clock that starts at the shared test time."""
    return FakeClock()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Return a data root seeded with the default users."""
    seed_users(tmp_path, DEFAULT_USERS)
    return tmp_path


@pytest.fixture
def client(root: Path, clock: FakeClock) -> TestClient:
    """Return a plain-HTTP test client for the auth router."""
    return TestClient(make_app(root, clock))


def _post_login(
    client: TestClient,
    username: str,
    password: str = PASSWORD,
    forwarded_for: str | None = None,
) -> httpx.Response:
    """POST a login, optionally claiming a client address through X-Forwarded-For."""
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        headers=headers,
    )


def _post_stepup(
    client: TestClient,
    payload: dict[str, Any],
    password: str = PASSWORD,
) -> httpx.Response:
    """POST a step-up re-verification with the session's CSRF token."""
    return client.post("/auth/stepup", json={"password": password}, headers=csrf(payload))


def _post_password(client: TestClient, payload: dict[str, Any], old: str) -> httpx.Response:
    """POST a password change from ``old`` to ``NEW_PASSWORD`` with the session's CSRF token."""
    return client.post(
        "/auth/password",
        json={"old_password": old, "new_password": NEW_PASSWORD},
        headers=csrf(payload),
    )


def _fail_logins(client: TestClient, names: list[str]) -> list[int]:
    """Attempt a wrong-password login for each name and return the status codes in order."""
    return [_post_login(client, name, WRONG_PASSWORD).status_code for name in names]


def _lock_by_login(client: TestClient, username: str) -> None:
    """Drive five wrong-password logins for ``username``; each must be refused with 401."""
    assert _fail_logins(client, [username] * 5) == [401] * 5


def _trace(response: httpx.Response) -> tuple[int, Any, str | None]:
    """Reduce a response to the parts an observer can see: status, body and Retry-After."""
    return (response.status_code, response.json(), response.headers.get("Retry-After"))


def _trace_logins(root: Path, username: str) -> list[tuple[int, Any, str | None]]:
    """Run wrong-password logins for ``username`` on a fresh app and trace each response."""
    client = TestClient(make_app(root, FakeClock()))
    return [
        _trace(_post_login(client, username, WRONG_PASSWORD))
        for _ in range(LOGIN_TRACE_ATTEMPTS)
    ]


def _fresh_root(base: Path, name: str) -> Path:
    """Create and seed a separate data root under ``base``."""
    root = base / name
    root.mkdir()
    seed_users(root, DEFAULT_USERS)
    return root


def _counted(func: Callable[..., Any], counter: list[int]) -> Callable[..., Any]:
    """Return ``func`` wrapped so that every call increments ``counter[0]``."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Count one call, then delegate to the original function."""
        counter[0] += 1
        return func(*args, **kwargs)

    return wrapper


def _count_hash_checks(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wrap ``verify_password`` so each scrypt check is counted; return the one-slot counter.

    ``dummy_verify`` calls ``verify_password`` internally, so every path performs exactly one check.
    """
    counter = [0]
    monkeypatch.setattr(passwords, "verify_password", _counted(passwords.verify_password, counter))
    return counter


def test_stepup_locks_after_five_failures_then_recovers(
    client: TestClient,
    clock: FakeClock,
) -> None:
    """Five wrong step-up passwords lock step-up, even for the right one, until expiry."""
    payload = login(client, "op1")
    for _ in range(5):
        wrong = _post_stepup(client, payload, WRONG_PASSWORD)
        assert wrong.status_code == 403
        assert wrong.json()["detail"] == "wrong_password"
    locked = _post_stepup(client, payload)
    assert locked.status_code == 423
    assert int(locked.headers["retry-after"]) > 0
    clock.advance(LOCK_WAIT_S)
    assert _post_stepup(client, payload).status_code == 200
    again = _post_stepup(client, payload, WRONG_PASSWORD)
    assert again.status_code == 403
    assert again.json()["detail"] == "wrong_password"


def test_password_change_locks_after_five_failures_then_recovers(
    client: TestClient,
    clock: FakeClock,
) -> None:
    """Five wrong old passwords lock password change, even for the right one, until expiry."""
    payload = login(client, "op1")
    for _ in range(5):
        wrong = _post_password(client, payload, WRONG_PASSWORD)
        assert wrong.status_code == 403
        assert wrong.json()["detail"] == "wrong_password"
    locked = _post_password(client, payload, PASSWORD)
    assert locked.status_code == 423
    assert int(locked.headers["retry-after"]) > 0
    clock.advance(LOCK_WAIT_S)
    again = _post_password(client, payload, WRONG_PASSWORD)
    assert again.status_code == 403
    assert again.json()["detail"] == "wrong_password"
    assert _post_password(client, payload, PASSWORD).status_code == 200


def test_failure_counter_is_shared_across_login_stepup_and_password(
    root: Path,
    clock: FakeClock,
) -> None:
    """Failed logins, step-ups and password changes all count toward one lockout."""
    app = make_app(root, clock)
    first = TestClient(app)
    second = TestClient(app)
    payload = login(first, "op1")
    for _ in range(3):
        assert _post_login(second, "op1", WRONG_PASSWORD).status_code == 401
    for _ in range(2):
        wrong = _post_stepup(first, payload, WRONG_PASSWORD)
        assert wrong.status_code == 403
        assert wrong.json()["detail"] == "wrong_password"
    assert _post_login(first, "op1", PASSWORD).status_code == 423


def test_stepup_is_rate_limited_per_ip_then_resets(client: TestClient, clock: FakeClock) -> None:
    """Twenty-five correct step-ups within one window hit 429; a new window allows them again."""
    payload = login(client, "op1")
    statuses = [_post_stepup(client, payload).status_code for _ in range(25)]
    assert 429 in statuses
    clock.advance(61)
    assert _post_stepup(client, payload).status_code == 200


def test_unknown_and_real_user_responses_match_through_lockout(tmp_path: Path) -> None:
    """A real user and an unknown name get identical responses over seven failed logins."""
    real = _trace_logins(_fresh_root(tmp_path, "real"), "view1")
    unknown = _trace_logins(_fresh_root(tmp_path, "unknown"), "nobody1")
    assert real == unknown
    assert [code for code, _, _ in real] == [401] * 5 + [423] * 2


def test_username_variants_share_one_failure_counter(client: TestClient) -> None:
    """Case and whitespace variants of a real username all count toward its one lockout."""
    assert _fail_logins(client, VARIANT_NAMES) == [401] * 5
    assert _post_login(client, "admin1", PASSWORD).status_code == 423


def test_unknown_username_variants_share_one_failure_counter(client: TestClient) -> None:
    """Case and whitespace variants of an unknown username all count toward one lockout."""
    assert _fail_logins(client, GHOST_NAMES) == [401] * 5
    assert _post_login(client, "ghost", PASSWORD).status_code == 423


def test_locked_real_user_still_costs_one_hash_check(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A login refused by lockout still performs exactly one password-hash check."""
    _lock_by_login(client, "op1")
    checks = _count_hash_checks(monkeypatch)
    assert _post_login(client, "op1", PASSWORD).status_code == 423
    assert checks[0] == 1


def test_locked_unknown_user_still_costs_one_hash_check(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A login for a locked unknown name still performs exactly one password-hash check."""
    _lock_by_login(client, "ghost2")
    checks = _count_hash_checks(monkeypatch)
    assert _post_login(client, "ghost2", PASSWORD).status_code == 423
    assert checks[0] == 1


def test_spoofed_forwarded_for_does_not_bypass_rate_limit(client: TestClient) -> None:
    """Rotating X-Forwarded-For does not get past the per-IP limit of twenty attempts a minute."""
    statuses = [
        _post_login(client, f"u{i:02d}", WRONG_PASSWORD, f"10.0.0.{i}").status_code
        for i in range(20)
    ]
    assert 429 not in statuses
    limited = _post_login(client, "u20", WRONG_PASSWORD, "10.0.1.1")
    assert limited.status_code == 429


def _who_app(auth_enabled: bool) -> FastAPI:
    """Return an app with one route that reports the actor ``actor_of`` resolves."""
    app = FastAPI()
    app.state.auth_enabled = auth_enabled

    @app.get("/who")
    def who(request: Request) -> dict[str, str]:
        """Report the actor the request resolves to."""
        return {"actor": actor_of(request).actor}

    return app


def _stamping_app() -> FastAPI:
    """Return an auth-enabled app whose middleware stamps a fixed actor on every request."""
    app = _who_app(auth_enabled=True)

    @app.middleware("http")
    async def stamp(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Attach the actor that the auth middleware would stamp."""
        request.state.actor = ActorContext(
            actor="zed",
            roles=("viewer",),
            session="s",
            source_ip="1.1.1.1",
            stepup=False,
            permissions=frozenset(),
        )
        return await call_next(request)

    return app


def test_actor_of_refuses_unstamped_request_when_auth_enabled() -> None:
    """With auth enabled and no stamped actor, ``actor_of`` fails closed with 401."""
    response = TestClient(_who_app(auth_enabled=True)).get("/who")
    assert response.status_code == 401


def test_actor_of_grants_local_dev_when_auth_disabled() -> None:
    """With auth disabled, ``actor_of`` returns the local development actor."""
    response = TestClient(_who_app(auth_enabled=False)).get("/who")
    assert response.status_code == 200
    assert response.json() == {"actor": "local-dev"}


def test_actor_of_returns_the_stamped_actor() -> None:
    """A stamped actor on the request is returned as is."""
    response = TestClient(_stamping_app()).get("/who")
    assert response.status_code == 200
    assert response.json() == {"actor": "zed"}
