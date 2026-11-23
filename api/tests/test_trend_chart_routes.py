"""Saved trend chart routes (#204) behind the real app-level enforcer.

Checks per-user storage, visibility of shared charts, the owner-only rules, the cross-field
rules of the chart schema, the corrupt-file guard and the actor-injection fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api.auth.actor import ActorContext, actor_of
from crosscut_api.auth.deps import AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.trend_chart_routes import build_trend_chart_router
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

CHART: dict[str, Any] = {
    "name": "Furnace loops",
    "series": [{"source": "s1", "tag": "t.pv", "axis": "y1"}],
    "axes": [{"id": "y1", "side": "left"}],
    "window": {"kind": "relative", "last_s": 3600},
}


def _chart(**overrides: Any) -> dict[str, Any]:
    """A valid chart body with the given top-level fields replaced."""
    return {**CHART, **overrides}


@pytest.fixture
def world(tmp_path: Path) -> tuple[FastAPI, Path]:
    """A mini app: enforcer, auth router and trend chart router over a data root."""
    seed_users(tmp_path, DEFAULT_USERS)
    clock = FakeClock()
    ctx = build_auth_context(tmp_path, TEST_CONFIG, clock)
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(ctx), ctx))])
    app.include_router(build_auth_router_for(ctx))
    app.include_router(build_trend_chart_router(tmp_path, clock))
    return app, tmp_path


def as_user(app: FastAPI, name: str) -> tuple[TestClient, dict[str, str]]:
    """A logged-in client and its CSRF header."""
    client = TestClient(app)
    return client, csrf(login(client, name))


def _create(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    """Create a chart through the API and return the stored representation."""
    response = client.post("/trends/charts", json=_chart(**overrides), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _create_shared(engineer_client: TestClient, engineer_headers: dict[str, str]) -> dict[str, Any]:
    """Create a shared chart owned by engineer1."""
    return _create(engineer_client, engineer_headers, name="Shared chart", shared=True)


def test_create_stamps_id_owner_and_created_time(world: tuple[FastAPI, Path]) -> None:
    """Create returns the server ids and ignores whatever id and owner the client sent."""
    app, _ = world
    client, headers = as_user(app, "view1")
    body = {"id": "clientchosen", "owner": "admin1", "name": "Mine"}
    response = client.post("/trends/charts", json=_chart(**body), headers=headers)
    chart = response.json()
    assert len(chart["id"]) == 12 and chart["id"].islower()
    assert (chart["owner"], chart["shared"]) == ("view1", False)
    assert chart["created_utc"] == chart["updated_utc"]


def test_list_shows_own_and_shared_charts_with_mine_flag(world: tuple[FastAPI, Path]) -> None:
    """List carries the caller's chart and the engineer's shared chart, flagged mine."""
    app, _ = world
    client, headers = as_user(app, "view1")
    _create(client, headers, name="Mine")
    engineer_client, engineer_headers = as_user(app, "eng1")
    _create_shared(engineer_client, engineer_headers)
    rows = client.get("/trends/charts").json()["charts"]
    assert [(row["name"], row["mine"], row["shared"]) for row in rows] == [
        ("Mine", True, False),
        ("Shared chart", False, True),
    ]


def test_a_private_chart_of_another_user_is_never_visible(world: tuple[FastAPI, Path]) -> None:
    """GET, PUT, DELETE and copy of a private foreign chart are all 404."""
    app, _ = world
    owner_client, owner_headers = as_user(app, "eng1")
    chart_id = _create(owner_client, owner_headers)["id"]
    client, headers = as_user(app, "view1")
    url = f"/trends/charts/{chart_id}"
    assert client.get(url).status_code == 404
    assert client.put(url, json=_chart(), headers=headers).status_code == 404
    assert client.delete(url, headers=headers).status_code == 404
    assert client.post(f"{url}/copy", headers=headers).status_code == 404


def test_a_shared_chart_is_readable_but_only_the_owner_changes_it(
    world: tuple[FastAPI, Path],
) -> None:
    """GET of a foreign shared chart succeeds; PUT and DELETE are 403 for another user."""
    app, _ = world
    engineer_client, engineer_headers = as_user(app, "eng1")
    chart_id = _create_shared(engineer_client, engineer_headers)["id"]
    client, headers = as_user(app, "view1")
    url = f"/trends/charts/{chart_id}"
    assert client.get(url).status_code == 200
    assert client.put(url, json=_chart(), headers=headers).status_code == 403
    assert client.delete(url, headers=headers).status_code == 403


def test_copy_of_a_shared_chart_is_unshared_and_owned_by_the_caller(
    world: tuple[FastAPI, Path],
) -> None:
    """Copy yields a private chart of the caller with "(copy)" appended to the name."""
    app, _ = world
    engineer_client, engineer_headers = as_user(app, "eng1")
    chart_id = _create_shared(engineer_client, engineer_headers)["id"]
    client, headers = as_user(app, "view1")
    copy = client.post(f"/trends/charts/{chart_id}/copy", headers=headers).json()
    assert copy["id"] != chart_id
    assert (copy["owner"], copy["shared"]) == ("view1", False)
    assert copy["name"] == "Shared chart (copy)"


@pytest.mark.parametrize("username", ["view1", "op1"])
def test_sharing_needs_config_edit(world: tuple[FastAPI, Path], username: str) -> None:
    """A viewer or operator who marks a chart shared is refused with 403 and nothing is stored."""
    app, root = world
    client, headers = as_user(app, username)
    response = client.post("/trends/charts", json=_chart(shared=True), headers=headers)
    assert response.status_code == 403
    assert client.get("/trends/charts").json()["charts"] == []
    assert not (root / "_trends" / "charts").exists()


def test_an_engineer_may_share_a_chart(world: tuple[FastAPI, Path]) -> None:
    """An engineer holds config.edit and stores a shared chart."""
    app, _ = world
    client, headers = as_user(app, "eng1")
    assert _create(client, headers, shared=True)["shared"] is True


def test_duplicate_axis_ids_are_422(world: tuple[FastAPI, Path]) -> None:
    """Two axes with the same id cannot both be drawn."""
    app, _ = world
    client, headers = as_user(app, "view1")
    axes = [{"id": "y1", "side": "left"}, {"id": "y1", "side": "right"}]
    response = client.post("/trends/charts", json=_chart(axes=axes), headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"] == ["axes: duplicate id 'y1'"]


def test_more_than_three_axes_in_one_pane_are_422(world: tuple[FastAPI, Path]) -> None:
    """A pane stacks at most three y-axes."""
    app, _ = world
    client, headers = as_user(app, "view1")
    axes = [{"id": f"y{i}", "side": "left"} for i in range(4)]
    series = [{"source": "s1", "tag": "t.pv", "axis": "y0"}]
    response = client.post("/trends/charts", json=_chart(axes=axes, series=series), headers=headers)
    assert response.status_code == 422
    assert "pane 0 has 4 axes" in response.json()["detail"][0]


def test_a_series_on_an_unknown_axis_is_422(world: tuple[FastAPI, Path]) -> None:
    """Every series must name an axis of the chart."""
    app, _ = world
    client, headers = as_user(app, "view1")
    series = [{"source": "s1", "tag": "t.pv", "axis": "nope"}]
    response = client.post("/trends/charts", json=_chart(series=series), headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"] == ["series[0]: unknown axis 'nope'"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"window": {"kind": "relative", "last_s": 59}},
        {"series": [{"source": "s1", "tag": "t.pv", "axis": "y1", "colour": "red"}]},
    ],
)
def test_schema_violations_are_422(world: tuple[FastAPI, Path], overrides: dict[str, Any]) -> None:
    """A window shorter than a minute and a colour that is not #rrggbb are refused."""
    app, _ = world
    client, headers = as_user(app, "view1")
    response = client.post("/trends/charts", json=_chart(**overrides), headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"]


@pytest.mark.parametrize("chart_id", ["ABC", "../x", "0123456789ab"])
def test_a_malformed_or_unknown_id_is_404(world: tuple[FastAPI, Path], chart_id: str) -> None:
    """Ids that do not match the file name pattern, and absent ids, are 404."""
    app, _ = world
    client, _ = as_user(app, "view1")
    assert client.get(f"/trends/charts/{chart_id}").status_code == 404


def test_a_corrupt_chart_file_is_skipped_by_list(world: tuple[FastAPI, Path]) -> None:
    """A half-written chart file never breaks the list."""
    app, root = world
    folder = root / "_trends" / "charts"
    folder.mkdir(parents=True)
    (folder / "aaaaaaaaaaaa.json").write_text("{not json", encoding="utf-8")
    client, headers = as_user(app, "view1")
    _create(client, headers, name="Good")
    rows = client.get("/trends/charts").json()["charts"]
    assert [row["name"] for row in rows] == ["Good"]


def test_the_local_dev_actor_owns_the_charts_it_creates(tmp_path: Path) -> None:
    """With auth off ``actor_of`` yields local-dev, who owns what it saves."""
    app = FastAPI()
    app.include_router(build_trend_chart_router(tmp_path))
    app.dependency_overrides[actor_of] = lambda: ActorContext(
        "local-dev", (), "session", "127.0.0.1", False, frozenset()
    )
    client = TestClient(app)
    saved = client.post("/trends/charts", json=CHART).json()
    assert saved["owner"] == "local-dev"
    rows = client.get("/trends/charts").json()["charts"]
    assert [(row["id"], row["mine"]) for row in rows] == [(saved["id"], True)]


def test_without_the_route_table_the_handler_still_serves_the_caller(
    tmp_path: Path,
) -> None:
    """A router used without the enforcer runs with the actor injected by ``actor_of``."""
    app = FastAPI()
    app.include_router(build_trend_chart_router(tmp_path))
    actor = ActorContext("view1", (), "session", "127.0.0.1", False, frozenset())
    app.dependency_overrides[actor_of] = lambda: actor
    client = TestClient(app)
    saved = client.post("/trends/charts", json=CHART).json()
    stored = tmp_path / "_trends" / "charts" / f"{saved['id']}.json"
    assert json.loads(stored.read_text(encoding="utf-8"))["owner"] == "view1"
