"""Tests of the step-test intake routes: preview, check, dataset creation, safety and size cap."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_api.app import create_app
from fastapi.testclient import TestClient

START = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
ROUTES = Path(__file__).resolve().parents[1] / "src" / "crosscut_api" / "intake_routes.py"
MAPPING = {"time_col": "timestamp", "pv_col": "LIC1.PV", "out_col": "LIC1.OUT"}


def signals(n: int = 720, dt: float = 10.0, step: float = 5.0) -> tuple[Any, Any, Any]:
    """t, OUT (doublet) and PV of an integrator with 30 s dead time and a little noise."""
    t = np.arange(n) * dt
    out = 50.0 + step * ((t >= 2400.0) & (t < 4200.0))
    delayed = np.concatenate([np.full(3, out[0]), out[:-3]])
    pv = 40.0 + 0.002 * dt * np.cumsum(delayed - out[0])
    return t, out, pv + np.random.default_rng(1).normal(0.0, 0.02, n)


def wide_csv(delim: str = ",", decimal: str = ".", bom: bool = False, **kw: Any) -> str:
    """A wide historian CSV with timestamp, PV, OUT and MODE columns."""
    t, out, pv = signals(**kw)
    lines = [delim.join(["timestamp", "LIC1.PV", "LIC1.OUT", "LIC1.MODE"])]
    for ti, o, p in zip(t, out, pv, strict=True):
        stamp = (START + timedelta(seconds=float(ti))).isoformat()
        num = lambda x: f"{x:.4f}".replace(".", decimal)  # noqa: E731
        lines.append(delim.join([stamp, num(p), num(o), "MAN"]))
    return ("﻿" if bom else "") + "\n".join(lines)


def long_csv() -> str:
    """A long CSV (timestamp, tag, value, quality) with change-only OUT rows and a foreign tag."""
    t, out, pv = signals()
    rows = ["timestamp,tag,value,quality"]
    for i, ti in enumerate(t):
        stamp = (START + timedelta(seconds=float(ti))).isoformat()
        rows.append(f"{stamp},LIC1.PV,{pv[i]:.4f},Good")
        if i == 0 or out[i] != out[i - 1]:
            rows.append(f"{stamp},LIC1.OUT,{out[i]:.3f},Good")
        rows.append(f"{stamp},OTHER.TAG,1.0,Good")
    return "\n".join(rows)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """An empty data root."""
    return tmp_path / "data"


@pytest.fixture
def client(root: Path) -> TestClient:
    """A client of an app whose data root exists but holds no dataset."""
    root.mkdir()
    return TestClient(create_app(root))


def body(text: str, **extra: Any) -> dict[str, Any]:
    """A check/dataset request body for the wide test CSV."""
    return {"csv_text": text, "mapping": MAPPING, "options": {}, **extra}


def create_body(text: str, dataset_id: str = "run1") -> dict[str, Any]:
    """A dataset request body."""
    return body(text, dataset_id=dataset_id, loop_name="LIC1", process_kind="integrating")


def files_of(root: Path) -> set[Path]:
    """Every file under the root."""
    return {p for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    ("delim", "decimal", "bom"), [(",", ".", False), (";", ",", False), (";", ",", True)]
)
def test_preview_of_wide_csv(client: TestClient, delim: str, decimal: str, bom: bool) -> None:
    text = wide_csv(delim, decimal, bom)
    reply = client.post("/intake/preview", json={"csv_text": text}).json()
    assert reply["layout"] == "wide" and reply["delimiter"] == delim
    assert reply["decimal"] == ("comma" if decimal == "," else "dot")
    assert reply["time_format"] == "iso" and reply["columns"][0] == "timestamp"
    assert len(reply["rows"]) == 8 and reply["n_rows_estimate"] == 720
    assert reply["suggestions"]["time_col"] == "timestamp"
    assert reply["suggestions"]["pv_col"] == "LIC1.PV"
    assert reply["suggestions"]["out_col"] == "LIC1.OUT"
    assert reply["suggestions"]["mode_col"] == "LIC1.MODE" and reply["tags"] == []


def test_preview_of_long_csv_lists_tags(client: TestClient) -> None:
    reply = client.post("/intake/preview", json={"csv_text": long_csv()}).json()
    assert reply["layout"] == "long"
    assert reply["tags"] == ["LIC1.PV", "LIC1.OUT", "OTHER.TAG"]
    assert reply["suggestions"]["tag_col"] == "tag" and reply["suggestions"]["value_col"] == "value"
    assert reply["suggestions"]["tag_pv"] == "LIC1.PV"
    assert reply["suggestions"]["tag_out"] == "LIC1.OUT"


def test_preview_reports_numeric_time_and_garbage(client: TestClient) -> None:
    seconds = "time,lvl,valve\n0,1.5,10\n1,1.6,10\n"
    reply = client.post("/intake/preview", json={"csv_text": seconds}).json()
    assert reply["time_format"] == "seconds"
    assert reply["suggestions"]["pv_col"] == "lvl" and reply["suggestions"]["out_col"] == "valve"
    bad = client.post("/intake/preview", json={"csv_text": "just one column\nabc\n"})
    assert bad.status_code == 422 and "delimiter" in bad.json()["detail"]


def test_check_of_good_record_is_ready_with_a_chart_sample(client: TestClient) -> None:
    mapping = {**MAPPING, "mode_col": "LIC1.MODE"}
    response = client.post("/intake/check", json={**body(wide_csv()), "mapping": mapping})
    assert response.status_code == 200
    reply = json.loads(response.text, parse_constant=lambda c: pytest.fail(f"{c} in JSON"))
    assert reply["verdict"] == "ready" and reply["dry_run"]["verdict"] == "ok"
    assert reply["dry_run"]["delay_upper_s"] is not None and reply["findings"] == []
    sample = reply["sample"]
    assert 2 <= len(sample["t_s"]) <= 800
    assert len(sample["t_s"]) == len(sample["pv"]) == len(sample["out"])
    assert reply["read_as"] and reply["n"] == 720


def test_check_of_long_csv(client: TestClient) -> None:
    mapping = {"time_col": "timestamp", "tag_pv": "LIC1.PV", "tag_out": "LIC1.OUT"}
    reply = client.post("/intake/check", json={**body(long_csv()), "mapping": mapping}).json()
    assert reply["verdict"] in {"ready", "usable_with_warnings"}


def test_check_of_unusable_record_has_findings(client: TestClient) -> None:
    flat = wide_csv(step=0.0)
    reply = client.post("/intake/check", json=body(flat)).json()
    assert reply["verdict"] == "not_usable"
    finding = next(f for f in reply["findings"] if f["code"] == "no_out_move")
    assert finding["text"] and finding["what_to_do"] and finding["blocking"] is True


def test_check_with_nan_cells_has_no_nan_in_json(client: TestClient) -> None:
    lines = wide_csv().split("\n")
    lines[5] = lines[5].replace(lines[5].split(",")[1], "Bad")
    response = client.post("/intake/check", json=body("\n".join(lines)))
    assert response.status_code == 200
    json.loads(response.text, parse_constant=lambda c: pytest.fail(f"{c} in JSON"))


def test_unknown_column_gives_a_friendly_422(client: TestClient) -> None:
    mapping = {**MAPPING, "pv_col": "NOPE"}
    response = client.post("/intake/check", json={**body(wide_csv()), "mapping": mapping})
    assert response.status_code == 422 and "NOPE" in response.json()["detail"]


def test_dataset_is_created_listed_and_tunable(client: TestClient, root: Path) -> None:
    assert client.get("/datasets").json() == []
    response = client.post("/intake/dataset", json=create_body(wide_csv()))
    assert response.status_code == 201
    reply = response.json()
    assert reply["dataset_id"] == "run1" and reply["assumptions"]
    assert [loop["name"] for loop in reply["loops"]] == ["LIC1"]
    assert [d["id"] for d in client.get("/datasets").json()] == ["run1"]
    loops = client.get("/datasets/run1/loops").json()["loops"]
    assert [row["name"] for row in loops] == ["LIC1"]
    tuning = client.get("/datasets/run1/loops/LIC1/tuning")
    assert tuning.status_code == 200 and tuning.json()["model"]["kind"] == "ipdt"


def test_duplicate_dataset_is_409_and_keeps_the_first(client: TestClient, root: Path) -> None:
    assert client.post("/intake/dataset", json=create_body(wide_csv())).status_code == 201
    before = files_of(root)
    assert client.post("/intake/dataset", json=create_body(wide_csv())).status_code == 409
    assert files_of(root) == before


def test_unusable_record_creates_nothing(client: TestClient, root: Path) -> None:
    response = client.post("/intake/dataset", json=create_body(wide_csv(step=0.0)))
    assert response.status_code == 422
    assert "no_out_move" in response.json()["detail"]["finding_codes"]
    assert not list(root.iterdir())


@pytest.mark.parametrize(
    "dataset_id", ["..", "../evil", "a/b", "a\\b", "..\\evil", "/abs", "x" * 65, "", "_softsensor"]
)
def test_unsafe_dataset_ids_are_refused(client: TestClient, root: Path, dataset_id: str) -> None:
    response = client.post("/intake/dataset", json=create_body(wide_csv(), dataset_id))
    assert response.status_code == 422
    assert not list(root.iterdir()) and not list(root.parent.glob("evil*"))


def test_only_the_new_dataset_folder_is_written(client: TestClient, root: Path) -> None:
    (root / "other.txt").write_text("keep", encoding="utf-8")
    before = files_of(root)
    client.post("/intake/preview", json={"csv_text": wide_csv()})
    client.post("/intake/check", json=body(wide_csv()))
    assert files_of(root) == before
    assert client.post("/intake/dataset", json=create_body(wide_csv())).status_code == 201
    new = files_of(root) - before
    assert new and all((root / "run1") in p.parents for p in new)
    assert files_of(root) - new == before


def test_oversized_csv_is_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("crosscut_api.intake_routes.MAX_BODY_BYTES", 1000)
    for url in ("/intake/preview", "/intake/check"):
        response = client.post(url, json=body("x" * 2000))
        assert response.status_code == 413


def test_intake_routes_import_no_plant_capability() -> None:
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    tops = {n.split(".")[0] for n in names}
    forbidden = {"opcua", "asyncua", "crosscut_opcua", "connectors", "crosscut_connectors"}
    assert not tops & forbidden
    assert not {n for n in names if "write_dataset" in n or "subprocess" in n}
