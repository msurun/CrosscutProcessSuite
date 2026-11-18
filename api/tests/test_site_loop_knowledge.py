"""Site catalogue loops: eng_limits / out_limits (#122) and one home of loop knowledge (#123)."""

from __future__ import annotations

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
    """Simulate a short mill circuit run once."""
    root = tmp_path_factory.mktemp("recorded_site")
    argv = ["--plant", "mill_circuit", "--scenario", "nominal", "--duration", "1h",
            "--sample-period", "10", "--out", str(root)]
    assert run_simulation(argv) == 0
    return root / DATASET


@pytest.fixture()
def data_root(recorded: Path, tmp_path: Path) -> Path:
    """A fresh data root with the dataset and no project.json."""
    root = tmp_path / "datasets"
    root.mkdir()
    shutil.copytree(recorded, root / DATASET)
    (root / DATASET / "project.json").unlink(missing_ok=True)
    return root


def _site_with_first_loop(root: Path, extra: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Write a site.json whose one loop is the first discovered loop plus ``extra``."""
    client = TestClient(create_app_without_auth(root))
    first = client.get(f"/datasets/{DATASET}/loops").json()["loops"][0]
    tags = json.loads((root / DATASET / "tags.json").read_text(encoding="utf-8"))["tags"]
    ids = {first["pv"], first["out"], first["sp"], first["mode"]}
    entry = {"id": "L1", "name": first["name"], "pv": first["pv"], "sp": first["sp"],
             "out": first["out"], "mode": first["mode"], **extra}
    # Site tags carry only eng_limits (the schema has no flat fields); dataset flat limits
    # are removed so the site catalogue is the only source of limits.
    limits = {"min": 1.0, "max": 9.0}
    site_tags = [{"id": t["id"], "eng_limits": limits} for t in tags if t["id"] in ids]
    doc = {"schema_version": 1, "site": {"name": "S"}, "tags": site_tags, "loops": [entry]}
    for tag in tags:
        tag.pop("eng_min", None)
        tag.pop("eng_max", None)
    (root / DATASET / "tags.json").write_text(json.dumps({"tags": tags}), encoding="utf-8")
    (root / "_site").mkdir()
    (root / "_site" / "site.json").write_text(json.dumps(doc), encoding="utf-8")
    return first["name"], doc


def test_site_loop_reads_eng_limits_and_out_limits(data_root: Path) -> None:
    """#122: PV range from the tag eng_limits, OUT range from loop.out_limits."""
    name, _ = _site_with_first_loop(data_root, {"out_limits": {"min": 5.0, "max": 95.0}})
    client = TestClient(create_app_without_auth(data_root))
    ranges = client.get(f"/datasets/{DATASET}/loops/{name}/knowledge").json()["ranges"]
    assert ranges == {"pv": [1.0, 9.0], "out": [5.0, 95.0]}


def test_site_loop_out_falls_back_to_out_tag_eng_limits(data_root: Path) -> None:
    """#122: without out_limits the OUT tag's eng_limits apply."""
    name, _ = _site_with_first_loop(data_root, {})
    client = TestClient(create_app_without_auth(data_root))
    ranges = client.get(f"/datasets/{DATASET}/loops/{name}/knowledge").json()["ranges"]
    assert ranges["out"] == [1.0, 9.0]


def test_put_knowledge_writes_the_site_entry_not_project_json(data_root: Path) -> None:
    """#123: a loop of the catalogue is edited in site.json; project.json stays absent."""
    name, _ = _site_with_first_loop(data_root, {})
    client = TestClient(create_app_without_auth(data_root))
    url = f"/datasets/{DATASET}/loops/{name}/knowledge"
    response = client.put(url, json={"delay_s": 7.0, "process_kind": "integrating"})
    assert response.status_code == 200
    stored = json.loads((data_root / "_site" / "site.json").read_text(encoding="utf-8"))
    assert stored["loops"][0]["delay_s"] == 7.0
    assert not (data_root / DATASET / "project.json").exists()


def test_site_knowledge_reaches_the_analysis(data_root: Path) -> None:
    """#123: what the editor wrote is what the adapter returns on the next read."""
    name, _ = _site_with_first_loop(data_root, {})
    client = TestClient(create_app_without_auth(data_root))
    url = f"/datasets/{DATASET}/loops/{name}/knowledge"
    client.put(url, json={"delay_s": 7.0, "pv_eng_min": 2.0})
    body = client.get(url).json()
    assert body["knowledge"]["delay_s"] == 7.0
    assert body["ranges"]["pv"] == [2.0, 9.0]
    assert body["source"] == "site"
