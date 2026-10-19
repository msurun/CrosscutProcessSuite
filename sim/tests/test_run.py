"""Tests for the command-line runner `python -m crosscut_sim.run`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from crosscut_sim.run import _current_git_commit, main, parse_duration


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("6h", 21600.0), ("30m", 1800.0), ("90s", 90.0), ("1.5h", 5400.0), ("45", 45.0)],
)
def test_parse_duration(text: str, seconds: float) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "h", "-5m", "abc", "0s", "5x"])
def test_parse_duration_rejects_bad_input(text: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(text)


def test_main_creates_dataset_directory_named_after_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--plant", "wood_berry", "--scenario", "nominal", "--duration", "10m", "--seed", "3"]
    assert main([*args, "--out", str(tmp_path)]) == 0
    dataset_dir = tmp_path / "wood_berry_nominal_seed3"
    assert (dataset_dir / "dataset.json").is_file()
    assert str(dataset_dir) in capsys.readouterr().out
    doc = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    assert doc["source"] == {"kind": "sim", "plant": "wood_berry", "scenario": "nominal", "seed": 3}
    assert doc["row_count"] == 600 * 11


def test_main_is_reproducible_across_output_directories(tmp_path: Path) -> None:
    args = ["--plant", "wood_berry", "--scenario", "noisy_feed", "--duration", "5m", "--seed", "8"]
    assert main([*args, "--out", str(tmp_path / "one")]) == 0
    assert main([*args, "--out", str(tmp_path / "two")]) == 0
    first = json.loads(
        (tmp_path / "one/wood_berry_noisy_feed_seed8/dataset.json").read_text("utf-8")
    )
    second = json.loads(
        (tmp_path / "two/wood_berry_noisy_feed_seed8/dataset.json").read_text("utf-8")
    )
    assert first["data_sha256"] == second["data_sha256"]


def test_main_refuses_to_overwrite_an_existing_dataset(tmp_path: Path) -> None:
    args = ["--plant", "wood_berry", "--scenario", "nominal", "--duration", "1m", "--seed", "1"]
    assert main([*args, "--out", str(tmp_path)]) == 0
    assert main([*args, "--out", str(tmp_path)]) != 0


def test_unknown_plant_or_scenario_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(
            ["--plant", "nope", "--scenario", "nominal", "--duration", "1m", "--out", str(tmp_path)]
        )
    assert excinfo.value.code != 0
    assert main(["--plant", "wood_berry", "--scenario", "nope", "--duration", "1m",
                 "--out", str(tmp_path)]) != 0  # fmt: skip


def test_module_entry_point_prints_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "crosscut_sim.run", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--plant" in result.stdout


def test_main_runs_the_mill_circuit(tmp_path: Path) -> None:
    args = ["--plant", "mill_circuit", "--scenario", "observational", "--duration", "10m"]
    assert main([*args, "--seed", "4", "--out", str(tmp_path)]) == 0
    doc = json.loads(
        (tmp_path / "mill_circuit_observational_seed4" / "dataset.json").read_text("utf-8")
    )
    assert doc["source"]["plant"] == "mill_circuit"
    assert doc["row_count"] == 600 * 21


def test_missing_git_executable_gives_no_code_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a git executable the revision is simply unknown (None), not a crash."""

    def no_git(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert _current_git_commit() is None
