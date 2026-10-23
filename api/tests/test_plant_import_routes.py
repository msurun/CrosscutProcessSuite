"""Tests of the PI wide-file import routes: upload, preview, import, delete.

The app includes only build_plant_import_router(tmp_path) so every dataset and upload lands
in a temporary data root. A synthetic CSV with one mode tag stands in for a real PI export.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from crosscut_api.plant_import_routes import build_plant_import_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

TIME_STEP_S = 10
SAMPLE_ROWS = 6

DATA_CSV = "\n".join(
    ["timestamp,demo.1000-lic-20103.mv,demo.1000-lic-20103.out,"
     "demo.1000-lic-20103.sp,demo.1000-lic-20103.auto#state,test"]
    + [
        f"2026-10-09 11:00:{index * TIME_STEP_S:02d},{100 + index},{100},{120},0,row{index}"
        for index in range(SAMPLE_ROWS)
    ]
) + "\n"

DICTIONARY_CSV = (
    "tag,description,unit,signal,loop,cell\n"
    "demo.1000-lic-20103.mv,Lic level,cm,PV (measured),20103,1\n"
    "demo.1000-lic-20103.out,Lic output,%,OUT (controller output),20103,1\n"
    "demo.1000-lic-20103.sp,Lic setpoint,cm,SP,20103,1\n"
    "demo.1000-lic-20103.auto#state,Lic mode,,mode flag,20103,1\n"
)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """A client on an app with only the plant import router and ``tmp_path`` as data root."""
    app = FastAPI()
    app.include_router(build_plant_import_router(tmp_path))
    return TestClient(app)


def _upload(client: TestClient, content: str) -> str:
    """Send a raw CSV body and return the upload id the server assigned."""
    response = client.post(
        "/intake/plant/upload",
        params={"role": "data"},
        content=content.encode(),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200
    return response.json()["upload_id"]


def _upload_data_and_dictionary(client: TestClient) -> tuple[str, str]:
    """Upload the sample data and its dictionary, returning both ids."""
    data_id = _upload(client, DATA_CSV)
    response = client.post(
        "/intake/plant/upload",
        params={"role": "dictionary"},
        content=DICTIONARY_CSV.encode(),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200
    return data_id, response.json()["upload_id"]


def test_upload_returns_a_hex_id_and_the_byte_count(client: TestClient, tmp_path: Path):
    response = client.post(
        "/intake/plant/upload",
        params={"role": "data"},
        content=DATA_CSV.encode(),
        headers={"content-type": "application/octet-stream"},
    )

    body = response.json()
    assert response.status_code == 200
    assert len(body["upload_id"]) == 32
    int(body["upload_id"], 16)  # raises when the id is not hexadecimal
    assert body["bytes"] == len(DATA_CSV.encode())


def test_upload_stores_the_file_under_the_uploads_folder(client: TestClient, tmp_path: Path):
    upload_id = _upload(client, DATA_CSV)

    stored = tmp_path / "_uploads" / f"{upload_id}.csv"
    assert stored.is_file()
    assert stored.read_text() == DATA_CSV


def test_an_unknown_role_is_rejected(client: TestClient):
    response = client.post(
        "/intake/plant/upload",
        params={"role": "report"},
        content=DATA_CSV.encode(),
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 422


def test_preview_reports_the_complete_loop_and_the_row_count(client: TestClient):
    data_id, dictionary_id = _upload_data_and_dictionary(client)
    response = client.post(
        "/intake/plant/preview",
        json={"data_upload": data_id, "dictionary_upload": dictionary_id},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["n_rows"] == SAMPLE_ROWS
    assert any(loop["id"] == "LIC-20103" and loop["complete"] for loop in body["loops"])


def test_preview_of_an_unknown_upload_is_not_found(client: TestClient):
    response = client.post(
        "/intake/plant/preview",
        json={"data_upload": "0" * 32},
    )

    assert response.status_code == 404


def test_preview_with_santiago_timezone_reports_utc_start(client: TestClient):
    data_id = _upload(client, DATA_CSV)
    response = client.post(
        "/intake/plant/preview",
        json={
            "data_upload": data_id,
            "timezone": {"kind": "iana", "value": "America/Santiago"},
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["start_utc"].startswith("2026-10-09T14:00:00")


def test_import_creates_the_dataset_and_removes_the_uploads(client: TestClient, tmp_path: Path):
    data_id, dictionary_id = _upload_data_and_dictionary(client)
    response = client.post(
        "/intake/plant/import",
        json={"data_upload": data_id, "dictionary_upload": dictionary_id, "dataset_id": "site"},
    )

    dataset = tmp_path / "site"
    assert response.status_code == 201
    assert (dataset / "dataset.json").is_file()
    assert (dataset / "test_windows.json").is_file()
    project = json.loads((dataset / "project.json").read_text())
    assert any("LIC-20103" in json.dumps(loop) for loop in project["loops"])
    assert not (tmp_path / "_uploads" / f"{data_id}.csv").exists()
    assert not (tmp_path / "_uploads" / f"{dictionary_id}.csv").exists()


def test_importing_into_an_existing_dataset_conflicts(client: TestClient):
    data_id, dictionary_id = _upload_data_and_dictionary(client)
    payload = {"data_upload": data_id, "dictionary_upload": dictionary_id, "dataset_id": "site"}
    first = client.post("/intake/plant/import", json=payload)
    second_data, second_dictionary = _upload_data_and_dictionary(client)
    payload["data_upload"] = second_data
    payload["dictionary_upload"] = second_dictionary
    second = client.post("/intake/plant/import", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_a_dataset_id_starting_with_underscore_is_rejected(client: TestClient):
    data_id = _upload(client, DATA_CSV)
    response = client.post(
        "/intake/plant/import",
        json={"data_upload": data_id, "dataset_id": "_hidden"},
    )

    assert response.status_code == 422


def test_a_dataset_id_with_forbidden_characters_is_rejected(client: TestClient):
    data_id = _upload(client, DATA_CSV)
    response = client.post(
        "/intake/plant/import",
        json={"data_upload": data_id, "dataset_id": "bad/id"},
    )

    assert response.status_code == 422


def test_an_upload_above_the_size_cap_is_too_large(client: TestClient, monkeypatch, tmp_path):
    monkeypatch.setattr("crosscut_api.plant_import_routes.MAX_UPLOAD_BYTES", 10)
    response = client.post(
        "/intake/plant/upload",
        params={"role": "data"},
        content=DATA_CSV.encode(),
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 413
    stored = list((tmp_path / "_uploads").glob("*.csv"))
    assert stored == []


def test_deleting_an_upload_returns_no_content_and_removes_the_file(
    client: TestClient, tmp_path: Path
):
    upload_id = _upload(client, DATA_CSV)
    response = client.delete(f"/intake/plant/upload/{upload_id}")

    assert response.status_code == 204
    assert not (tmp_path / "_uploads" / f"{upload_id}.csv").exists()


def test_deleting_with_an_invalid_upload_id_is_rejected(client: TestClient):
    response = client.delete("/intake/plant/upload/not-a-hex-id")

    assert response.status_code == 422
