"""Tuning window of a level loop: the suggested window keeps the quiet lead (via the API)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from crosscut_api.app import create_app
from crosscut_loops.step_test_cli import main
from fastapi.testclient import TestClient

GRID_S = 2.0
LOOP_URL = "/datasets/{name}/loops/LIC1/tuning"


def _write_record(path: Path, manual_from_s: float) -> None:
    """Integrating record: OUT 50 -> 56 at 1200 s -> 50 at 2400 s; MAN from ``manual_from_s``."""
    t = np.arange(0.0, 4800.0, GRID_S)
    out = 50.0 + 6.0 * ((t >= 1200.0) & (t < 2400.0))
    delayed = np.concatenate([np.full(3, 50.0), out[:-3]])
    pv = 40.0 + 0.002 * GRID_S * np.cumsum(delayed - 50.0)
    pv += np.random.default_rng(1).normal(0.0, 0.02, len(t))
    lines = ["time_s,LIC1.PV,LIC1.OUT,LIC1.MODE"]
    for ti, p, o in zip(t, pv, out, strict=True):
        mode = "MAN" if ti >= manual_from_s else "AUTO"
        lines.append(f"{ti:.0f},{p:.4f},{o:.3f},{mode}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _client(tmp_path: Path, name: str, manual_from_s: float) -> TestClient:
    """App over a dataset made by ``step_test_cli make-dataset`` from the synthetic record."""
    csv_path = tmp_path / f"{name}.csv"
    _write_record(csv_path, manual_from_s)
    root = tmp_path / "root"
    cols = ["--time-col", "time_s", "--pv-col", "LIC1.PV", "--out-col", "LIC1.OUT"]
    args = ["make-dataset", str(csv_path), *cols, "--mode-col", "LIC1.MODE", "--manual-value", "0"]
    assert main([*args, "--out", str(root / name)]) == 0
    return TestClient(create_app(root))


def test_suggested_window_includes_the_quiet_lead(tmp_path: Path) -> None:
    client = _client(tmp_path, "lead", 0.0)
    body = client.get(LOOP_URL.format(name="lead")).json()
    window = body["window"]
    assert window["start_s"] <= 1200.0 - 0.3 * (window["end_s"] - window["start_s"]) + 1.0
    assert window["end_s"] >= 2400.0 + 300.0
    assert window["padded"]["before_s"] > 0
    assert body["blocked_code"] is None
    assert body["model"]["kind"] == "ipdt" and body["settings"] is not None


def test_lead_is_limited_by_the_manual_segment_and_refused_honestly(tmp_path: Path) -> None:
    client = _client(tmp_path, "short", 1190.0)
    body = client.get(LOOP_URL.format(name="short")).json()
    assert body["window"]["start_s"] >= 1190.0
    assert body["blocked_code"] == "ipdt_refused"


def test_explicit_window_is_not_padded(tmp_path: Path) -> None:
    client = _client(tmp_path, "explicit", 0.0)
    params = {"start_s": 898, "end_s": 3300}
    window = client.get(LOOP_URL.format(name="explicit"), params=params).json()["window"]
    assert (window["start_s"], window["end_s"]) == (898, 3300)
    assert window["padded"] == {"before_s": 0.0, "after_s": 0.0}


@pytest.mark.parametrize("kind", ["self_regulating"])
def test_self_regulating_window_is_not_padded(tmp_path: Path, kind: str) -> None:
    csv_path = tmp_path / "s.csv"
    _write_record(csv_path, 0.0)
    cols = ["--time-col", "time_s", "--pv-col", "LIC1.PV", "--out-col", "LIC1.OUT"]
    root = tmp_path / "root"
    assert main(["make-dataset", str(csv_path), *cols, "--process-kind", kind,
                 "--out", str(root / "s")]) == 0  # fmt: skip
    window = TestClient(create_app(root)).get(LOOP_URL.format(name="s")).json()["window"]
    assert window["padded"] == {"before_s": 0.0, "after_s": 0.0}
