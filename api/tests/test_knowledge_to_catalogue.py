"""Knowledge saves promote dataset loops into the shared site catalogue.

Legacy project files remain readable and unchanged during saves and migration.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from crosscut_sim.run import main as run_simulation
from fastapi.testclient import TestClient
from open_app import create_app_without_auth

DATASET = "mill_circuit_nominal_seed42"


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Simulate one short mill-circuit dataset for independent test copies."""
    root = tmp_path_factory.mktemp("recorded_catalogue")
    arguments = ["--plant", "mill_circuit", "--scenario", "nominal", "--duration", "1h",
                 "--sample-period", "10", "--out", str(root)]
    assert run_simulation(arguments) == 0
    return root / DATASET


@pytest.fixture()
def data_root(recorded: Path, tmp_path: Path) -> Path:
    """Copy the simulated dataset without its generated project file."""
    root = tmp_path / "datasets"
    root.mkdir()
    shutil.copytree(recorded, root / DATASET)
    (root / DATASET / "project.json").unlink(missing_ok=True)
    return root


def _first_loop(client: TestClient) -> dict[str, Any]:
    """Return a discovered loop before a catalogue exists."""
    return client.get(f"/datasets/{DATASET}/loops").json()["loops"][0]


def _site(root: Path) -> dict[str, Any]:
    """Read the saved catalogue."""
    return json.loads((root / "_site" / "site.json").read_text(encoding="utf-8"))


def _legacy_project(root: Path, loop: dict[str, Any]) -> bytes:
    """Write old knowledge with the discovered loop's tag roles."""
    entry = {key: loop[key] for key in ("name", "pv", "sp", "out", "mode")}
    entry["delay_s"] = 8.0
    path = root / DATASET / "project.json"
    path.write_text(json.dumps({"loops": [entry]}), encoding="utf-8")
    return path.read_bytes()


def test_first_save_creates_a_catalogue_loop_and_tags(data_root: Path) -> None:
    """A discovered loop gets one catalogue home without a project write."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    response = client.put(
        f"/datasets/{DATASET}/loops/{loop['name']}/knowledge", json={"delay_s": 4.0}
    )
    assert response.status_code == 200
    document = _site(data_root)
    assert document["loops"][0]["id"] == loop["name"]
    assert document["loops"][0]["pv"] == loop["pv"]
    assert {row["id"] for row in document["tags"]} == {
        loop["pv"], loop["sp"], loop["out"], loop["mode"]
    }
    assert not (data_root / DATASET / "project.json").exists()


def test_second_save_updates_the_same_catalogue_entry(data_root: Path) -> None:
    """Repeated edits do not duplicate a loop."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    url = f"/datasets/{DATASET}/loops/{loop['name']}/knowledge"
    client.put(url, json={"delay_s": 4.0})
    response = client.put(url, json={"delay_s": 6.0})
    assert response.status_code == 200
    assert len(_site(data_root)["loops"]) == 1
    assert _site(data_root)["loops"][0]["delay_s"] == 6.0


def test_get_reads_legacy_project_knowledge(data_root: Path) -> None:
    """Existing knowledge survives until its first catalogue save."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    _legacy_project(data_root, loop)
    response = client.get(f"/datasets/{DATASET}/loops/{loop['name']}/knowledge")
    assert response.json()["knowledge"]["delay_s"] == 8.0
    assert response.json()["source"] == "project"


def test_migration_copies_knowledge_and_preserves_project(data_root: Path) -> None:
    """Bulk migration keeps the legacy file intact for compatibility."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    original = _legacy_project(data_root, loop)
    response = client.post(f"/datasets/{DATASET}/loops/migrate-knowledge")
    assert response.status_code == 200
    assert response.json() == {"moved": [loop["name"]], "skipped": []}
    assert _site(data_root)["loops"][0]["delay_s"] == 8.0
    assert (data_root / DATASET / "project.json").read_bytes() == original


def test_invalid_knowledge_does_not_create_a_catalogue(data_root: Path) -> None:
    """A rejected edit leaves the catalogue absent."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    response = client.put(
        f"/datasets/{DATASET}/loops/{loop['name']}/knowledge", json={"delay_s": -1}
    )
    assert response.status_code == 422
    assert not (data_root / "_site" / "site.json").exists()


def test_save_copies_tag_unit_and_description(data_root: Path) -> None:
    """The catalogue retains dataset metadata supported by its tag schema."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    path = data_root / DATASET / "tags.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    tag = next(row for row in document["tags"] if row["id"] == loop["pv"])
    tag.update(description="Synthetic pressure")
    path.write_text(json.dumps(document), encoding="utf-8")
    response = client.put(
        f"/datasets/{DATASET}/loops/{loop['name']}/knowledge", json={"delay_s": 4}
    )
    assert response.status_code == 200
    stored = next(row for row in _site(data_root)["tags"] if row["id"] == loop["pv"])
    assert stored == {
        "id": loop["pv"], "unit": tag["unit"], "description": "Synthetic pressure"
    }


def test_first_save_preserves_other_legacy_knowledge(data_root: Path) -> None:
    """A partial edit carries existing knowledge into the catalogue unchanged."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    original = _legacy_project(data_root, loop)
    response = client.put(
        f"/datasets/{DATASET}/loops/{loop['name']}/knowledge", json={"ultimate_period_s": 12}
    )
    assert response.status_code == 200
    assert response.json()["knowledge"]["delay_s"] == 8.0
    assert (data_root / DATASET / "project.json").read_bytes() == original


def test_unpromoted_loop_stays_readable_after_another_save(data_root: Path) -> None:
    """Promoting one loop must not hide the other discovered loops."""
    client = TestClient(create_app_without_auth(data_root))
    loops = client.get(f"/datasets/{DATASET}/loops").json()["loops"]
    client.put(f"/datasets/{DATASET}/loops/{loops[0]['name']}/knowledge", json={"delay_s": 4})
    response = client.get(f"/datasets/{DATASET}/loops/{loops[1]['name']}/knowledge")
    assert response.status_code == 200
    assert response.json()["source"] == "project"


def test_migration_skips_existing_catalogue_knowledge(data_root: Path) -> None:
    """A repeated migration never overwrites newer catalogue edits."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    _legacy_project(data_root, loop)
    client.put(f"/datasets/{DATASET}/loops/{loop['name']}/knowledge", json={"delay_s": 4})
    response = client.post(f"/datasets/{DATASET}/loops/migrate-knowledge")
    assert response.status_code == 200
    assert response.json()["moved"] == []
    assert response.json()["skipped"][0]["loop"] == loop["name"]
    assert response.json()["skipped"][0]["reason"]
    assert _site(data_root)["loops"][0]["delay_s"] == 4


def test_invalid_catalogue_returns_validation_problems(data_root: Path) -> None:
    """Invalid existing site fields are reported without replacing the file."""
    client = TestClient(create_app_without_auth(data_root))
    loop = _first_loop(client)
    directory = data_root / "_site"
    directory.mkdir()
    path = directory / "site.json"
    invalid = {"schema_version": 1, "site": {"name": "Site"}, "tags": [], "extra": True}
    path.write_text(json.dumps(invalid), encoding="utf-8")
    response = client.put(
        f"/datasets/{DATASET}/loops/{loop['name']}/knowledge", json={"delay_s": 4}
    )
    assert response.status_code == 422
    assert "extra" in response.json()["detail"]
    assert json.loads(path.read_text(encoding="utf-8")) == invalid
