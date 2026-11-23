"""Tests for the on-demand source history route (GET /sources/{id}/history, #201).

Covers the happy path and caching, cache-key stability, the dataset folder written for a
history read, the error codes, eviction of old caches, and access control under the enforcer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from auth_support import DEFAULT_USERS, TEST_CONFIG, FakeClock, csrf, login, seed_users
from crosscut_api.app import create_app
from crosscut_api.auth.deps import AuthGuards, build_auth_context
from crosscut_api.auth.enforce import make_enforcer
from crosscut_api.auth_routes import build_auth_router_for
from crosscut_api.source_history import build_source_history_router, evict
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

SOURCE_ID = "hist1"
TAG_PV = "plant.csv/FIC101"
TAG_SP = "plant.csv/LIC201"
START = "2026-01-01T00:00:00Z"
END = "2026-01-01T00:30:00Z"
CSV_HEADER = "timestamp,FIC101,LIC201"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "dataset.schema.json"


def _write_csv(folder: Path, rows: int = 30) -> None:
    """Write a minute-resolution CSV with deterministic values FIC101=m, LIC201=2m."""
    folder.mkdir(parents=True, exist_ok=True)
    lines = [CSV_HEADER]
    for minute in range(rows):
        lines.append(f"2026-01-01T00:{minute:02d}:00Z,{minute},{2 * minute}")
    (folder / "plant.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_site(root: Path) -> None:
    """Write a site catalogue with one csv source named hist1 pointing at root/csvsrc."""
    site_folder = root / "_site"
    site_folder.mkdir(parents=True, exist_ok=True)
    site_doc = {
        "schema_version": 1,
        "site": {"id": "demo", "name": "Demo"},
        "tags": [],
        "sources": [{"id": SOURCE_ID, "driver": "csv", "endpoint": str(root / "csvsrc")}],
    }
    (site_folder / "site.json").write_text(json.dumps(site_doc), encoding="utf-8")


@pytest.fixture
def history_root(tmp_path: Path) -> Path:
    """A data root with a working csv source and its site catalogue."""
    _write_csv(tmp_path / "csvsrc")
    _write_site(tmp_path)
    return tmp_path


@pytest.fixture
def history_client(history_root: Path) -> TestClient:
    """A test client for the app with auth disabled over the working root."""
    return TestClient(create_app(history_root, auth_enabled=False))


def _history(
    client: TestClient,
    tags: list[str] | str = (TAG_PV, TAG_SP),
    start: str = START,
    end: str = END,
) -> Any:
    """Call the history route with the given tags and window."""
    tag_list = [tags] if isinstance(tags, str) else list(tags)
    params: list[tuple[str, str]] = [("tag", tag) for tag in tag_list]
    params += [("start", start), ("end", end)]
    return client.get(f"/sources/{SOURCE_ID}/history", params=params)


def _cached_id(client: TestClient) -> str:
    """Fetch the history once and return the resulting dataset id."""
    response = _history(client)
    assert response.status_code == 200, response.text
    return str(response.json()["dataset_id"])


def _read_metadata(root: Path, dataset_id: str) -> dict[str, Any]:
    """Read the dataset.json of a cached history folder."""
    return json.loads((root / dataset_id / "dataset.json").read_text("utf-8"))


def test_first_call_reads_fresh_and_returns_a_history_id(history_client: TestClient) -> None:
    """The first call is not cached and yields a hist- dataset covering the window and tags."""
    response = _history(history_client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cached"] is False
    assert body["dataset_id"].startswith("hist-")
    assert body["time_range"]["start_utc"] >= START
    assert body["time_range"]["end_utc"] <= END
    assert set(body["tags"]) == {TAG_PV, TAG_SP}


def test_second_identical_call_is_served_from_the_cache(history_client: TestClient) -> None:
    """The same request twice hits the cache and returns the same dataset id."""
    first = _history(history_client).json()
    second = _history(history_client).json()
    assert second["cached"] is True
    assert second["dataset_id"] == first["dataset_id"]


def test_tag_order_and_duplicates_share_the_cache_key(history_client: TestClient) -> None:
    """Reordered tags and a repeated tag give the same cache folder and id."""
    first = _history(history_client, tags=[TAG_PV, TAG_SP]).json()
    second = _history(history_client, tags=[TAG_SP, TAG_PV, TAG_PV]).json()
    assert second["dataset_id"] == first["dataset_id"]
    assert second["cached"] is True


def test_the_cached_dataset_serves_its_values(history_client: TestClient) -> None:
    """The stored samples are readable back through the dataset series endpoint."""
    dataset_id = _cached_id(history_client)
    response = history_client.get(
        f"/datasets/{dataset_id}/series",
        params=[("tag", TAG_PV), ("tag", TAG_SP)],
    )
    assert response.status_code == 200, response.text
    series = {one["tag"]: one["mean"] for one in response.json()["series"]}
    # The CSV holds FIC101 = m and LIC201 = 2m at minute m, for m = 0..29.
    assert series[TAG_PV] == [float(m) for m in range(30)]
    assert series[TAG_SP] == [float(2 * m) for m in range(30)]


def test_the_stored_source_block_marks_a_history_read(
    history_client: TestClient, history_root: Path
) -> None:
    """dataset.json source records kind, source_id and the requested window."""
    dataset_id = _cached_id(history_client)
    source = _read_metadata(history_root, dataset_id)["source"]
    assert source["kind"] == "history"
    assert source["source_id"] == SOURCE_ID
    assert (source["window"]["start_utc"], source["window"]["end_utc"]) == (START, END)


def test_the_stored_dataset_json_validates_against_the_schema(
    history_client: TestClient, history_root: Path
) -> None:
    """The written metadata file validates against schemas/dataset.schema.json."""
    jsonschema = pytest.importorskip("jsonschema")
    dataset_id = _cached_id(history_client)
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    jsonschema.validate(_read_metadata(history_root, dataset_id), schema)


def test_an_unknown_source_is_404(history_client: TestClient) -> None:
    """A source id absent from the catalogue is 404."""
    response = history_client.get(
        "/sources/missing/history", params=[("tag", TAG_PV), ("start", START), ("end", END)]
    )
    assert response.status_code == 404


def test_a_window_without_samples_is_404(history_client: TestClient) -> None:
    """A window past the last sample has no rows and is 404."""
    response = _history(history_client, start="2026-02-01T00:00:00Z", end="2026-02-01T01:00:00Z")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-01-01T00:30:00Z", "2026-01-01T00:00:00Z"),
        ("2026-01-01T00:30:00Z", "2026-01-01T00:30:00Z"),
    ],
)
def test_end_not_after_start_is_422(history_client: TestClient, start: str, end: str) -> None:
    """A window whose end is not strictly after its start is 422."""
    assert _history(history_client, start=start, end=end).status_code == 422


def test_an_unparseable_start_is_422(history_client: TestClient) -> None:
    """A start that is not ISO-8601 is 422."""
    assert _history(history_client, start="not-a-time").status_code == 422


def test_a_window_longer_than_the_limit_is_422(history_client: TestClient) -> None:
    """A window beyond 400 days is refused before any read."""
    response = _history(history_client, start="2024-01-01T00:00:00Z", end="2026-01-01T00:00:00Z")
    assert response.status_code == 422


def test_a_missing_tag_parameter_is_422(history_client: TestClient) -> None:
    """No tag query parameter fails validation."""
    response = history_client.get(
        f"/sources/{SOURCE_ID}/history", params=[("start", START), ("end", END)]
    )
    assert response.status_code == 422


def test_a_source_without_the_history_capability_is_400(
    history_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connector that does not advertise history is 400."""

    class BareConnector:
        def capabilities(self) -> set[str]:
            return set()

    monkeypatch.setattr(
        "crosscut_api.source_history.connector_from_source", lambda source: BareConnector()
    )
    assert _history(history_client).status_code == 400


def test_a_connector_failure_during_history_is_502(
    history_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SourceConnectionError from the connector surfaces as 502."""
    from crosscut_connectors.base import CAP_HISTORY, SourceConnectionError

    class FailingConnector:
        def capabilities(self) -> set[str]:
            return {CAP_HISTORY}

        def history(self, *args: Any, **kwargs: Any) -> Any:
            raise SourceConnectionError("plant offline")

    monkeypatch.setattr(
        "crosscut_api.source_history.connector_from_source", lambda source: FailingConnector()
    )
    assert _history(history_client).status_code == 502


def test_evict_removes_the_oldest_caches_beyond_keep(history_root: Path) -> None:
    """With several hist- caches, evict(root, keep=1) leaves only the most recent one."""
    created: list[Path] = []
    for index in range(3):
        folder = history_root / f"hist-{index:04d}"
        folder.mkdir()
        (folder / "dataset.json").write_text("{}", encoding="utf-8")
        created.append(folder)
    removed = evict(history_root, keep=1)
    survivors = sorted(p.name for p in history_root.glob("hist-*"))
    assert survivors == [created[-1].name]
    assert sorted(removed) == sorted([created[0].name, created[1].name])


@pytest.fixture
def world(tmp_path: Path) -> tuple[FastAPI, Path]:
    """A mini app: enforcer, auth router and source history router over a data root."""
    seed_users(tmp_path, DEFAULT_USERS)
    clock = FakeClock()
    ctx = build_auth_context(tmp_path, TEST_CONFIG, clock)
    app = FastAPI(dependencies=[Depends(make_enforcer(AuthGuards(ctx), ctx))])
    app.include_router(build_auth_router_for(ctx))
    app.include_router(build_source_history_router(tmp_path))
    return app, tmp_path


def as_user(app: FastAPI, name: str) -> tuple[TestClient, dict[str, str]]:
    """A logged-in client and its CSRF header."""
    client = TestClient(app)
    return client, csrf(login(client, name))


def test_a_viewer_with_data_view_may_read_history(world: tuple[FastAPI, Path]) -> None:
    """A viewer holding data.view may call the history route under the enforcer."""
    app, root = world
    _write_csv(root / "csvsrc")
    _write_site(root)
    client, _headers = as_user(app, "view1")
    response = client.get(
        f"/sources/{SOURCE_ID}/history",
        params=[("tag", TAG_PV), ("tag", TAG_SP), ("start", START), ("end", END)],
    )
    assert response.status_code == 200, response.text
    assert response.json()["dataset_id"].startswith("hist-")
