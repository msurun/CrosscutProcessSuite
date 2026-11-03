"""Tests that the Write Gateway routes are mounted but answer 503 until a client exists.

The gateway runs as a separate process; until a client is wired in, the provider is None.
"""

from __future__ import annotations

from pathlib import Path

from crosscut_api.app import create_app
from fastapi.testclient import TestClient


def test_gateway_status_is_unavailable_without_a_client(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.get("/gateway/status")

    assert response.status_code == 503
