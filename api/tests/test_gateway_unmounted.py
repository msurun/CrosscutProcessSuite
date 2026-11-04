"""Tests that the Write Gateway routes are mounted but answer 503 until a client exists.

The gateway runs as a separate process; until a client is wired in, the provider is None.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from open_app import create_app_without_auth


def test_gateway_status_is_unavailable_without_a_client(tmp_path: Path) -> None:
    client = TestClient(create_app_without_auth(tmp_path))

    response = client.get("/gateway/status")

    assert response.status_code == 503
