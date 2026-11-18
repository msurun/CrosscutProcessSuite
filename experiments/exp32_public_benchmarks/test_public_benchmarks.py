"""Tests for the TEP and C-MAPSS loaders, protocol split, metrics and the skip path.

Tiny synthetic files in each dataset's exact layout are written into tmp_path; no real data and
no network are used.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import cmapss_degradation as cm  # noqa: E402
import run_benchmarks  # noqa: E402
import tep_anomaly as tep  # noqa: E402


def _tep_csv(path: Path, fault: int, runs: list[int], n: int, shift: float = 0.0) -> None:
    """Write a TEP-layout CSV; from row 160 on every variable is shifted by ``shift``."""
    rng = np.random.default_rng(fault * 100 + runs[0])
    lines = [",".join(["faultNumber", "simulationRun", "sample", *tep.TAGS])]
    for run in runs:
        for i in range(n):
            vals = rng.normal(size=len(tep.TAGS)) + (shift if i >= 160 else 0.0)
            lines.append(",".join([str(fault), str(run), str(i + 1), *map(str, vals)]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _merge(path: Path, parts: list[Path]) -> None:
    """Concatenate CSV parts (header once) into ``path``."""
    lines = parts[0].read_text(encoding="utf-8").splitlines()
    for part in parts[1:]:
        lines += part.read_text(encoding="utf-8").splitlines()[1:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _tep_folder(tmp_path: Path) -> Path:
    """A folder with the three files: fault-free runs 1-3 (train), runs 1-2 (test), 20 faults."""
    _tep_csv(tmp_path / tep.FILES["train"], 0, [1, 2, 3], 300)
    _tep_csv(tmp_path / tep.FILES["test_free"], 0, [1, 2], 300)
    parts = []
    for f in tep.FAULTS:
        parts.append(tmp_path / f"p{f}.csv")
        _tep_csv(parts[-1], f, [1, 2], 300, shift=6.0)
    _merge(tmp_path / tep.FILES["test_fault"], parts)
    return tmp_path


def test_tep_loader_shapes_and_record(tmp_path: Path) -> None:
    """Rows are grouped by fault and run; the matrix has 52 columns."""
    _tep_csv(tmp_path / "a.csv", 3, [1, 2], 10)
    table = tep.load_table(tmp_path / "a.csv")
    assert table.x.shape == (20, 52) and table.record(3, 2).shape == (10, 52)


def test_tep_loader_names_missing_column(tmp_path: Path) -> None:
    """A file without the xmv columns is rejected."""
    (tmp_path / "bad.csv").write_text("faultNumber,simulationRun,xmeas_1\n1,1,0.5\n")
    with pytest.raises(ValueError, match="missing columns"):
        tep.load_table(tmp_path / "bad.csv")


def test_pick_runs_is_deterministic_and_distinct() -> None:
    """The frozen run choice is repeatable, sorted and has no duplicates."""
    runs = np.repeat(np.arange(1, 501), 3)
    a = tep.pick_runs(runs, tep.TEST_SEED)
    assert a == tep.pick_runs(runs, tep.TEST_SEED) and len(set(a)) == 10 and a == sorted(a)


def test_score_run_known_answer() -> None:
    """Event 150-170 gives 10 false alarm samples; event 175-200 is detected with delay 15."""
    s = tep.score_run([(150, 170), (175, 200)], 160, 960)
    assert (s.delay, s.false_alarm_samples, s.pre_samples) == (15, 10, 160)
    assert tep.score_run([], 160, 960).delay is None


def test_summarise_known_answer() -> None:
    """Two runs: delay 10 samples and a miss; one alarm sample in 320 pre-onset samples."""
    out = tep.summarise([tep.RunScore(10, 1, 160), tep.RunScore(None, 0, 160)])
    assert out["detection_rate"] == 0.5 and out["mean_delay_min"] == 30.0
    assert out["false_alarm_rate"] == pytest.approx(1 / 320)


def test_tep_protocol_end_to_end(tmp_path: Path) -> None:
    """A large shift after onset is detected quickly; structure of the result holds."""
    result = tep.run_protocol(_tep_folder(tmp_path))
    assert set(result["faults"]) == set(tep.FAULTS) and result["test_runs"] == [1, 2]
    assert result["faults"][1]["detection_rate"] == 1.0
    assert result["faults"][1]["mean_delay_samples"] < 10


def _cmapss_file(path: Path, units: int, cycles: int, seed: int) -> None:
    """Write a whitespace-separated 26-column file whose sensor 1 drifts with the cycle."""
    rng = np.random.default_rng(seed)
    rows = []
    for u in range(1, units + 1):
        for c in range(1, cycles + 1):
            sensors = rng.normal(size=21) * 0.01
            sensors[0] += c * 0.1
            rows.append([u, c, 0.0, 0.0, 100.0, *sensors])
    np.savetxt(path, np.array(rows), fmt="%.6f")


def _cmapss_folder(folder: Path) -> Path:
    """FD001 in the exact file layout: train, test and RUL files."""
    folder.mkdir(exist_ok=True)
    _cmapss_file(folder / "train_FD001.txt", 4, 60, 1)
    _cmapss_file(folder / "test_FD001.txt", 3, 30, 2)
    np.savetxt(folder / "RUL_FD001.txt", [30.0, 30.0, 30.0], fmt="%.0f")
    return folder


def test_cmapss_loader_units_and_columns(tmp_path: Path) -> None:
    """24 value columns per cycle, units split correctly; a wrong width is rejected."""
    folder = _cmapss_folder(tmp_path)
    units = cm.load_units(folder / "train_FD001.txt")
    assert sorted(units) == [1, 2, 3, 4] and units[1].shape == (60, 24)
    np.savetxt(folder / "bad.txt", np.ones((3, 5)))
    with pytest.raises(ValueError, match="26 columns"):
        cm.load_units(folder / "bad.txt")


def test_train_targets_are_capped_countdown() -> None:
    """RUL of the last cycle is 0, the first of a 200-cycle engine is capped at 125."""
    _, y = cm.train_targets({1: np.zeros((200, 24))})
    assert y[-1] == 0 and y[0] == cm.RUL_CAP and y[199 - 10] == 10


def test_metrics_known_answer() -> None:
    """RMSE of errors (+3, -4) is sqrt(12.5); PHM08 score of d = -13 and d = +10 is 2(e - 1)."""
    assert cm.rmse(np.array([13.0, 6.0]), np.array([10.0, 10.0])) == pytest.approx(math.sqrt(12.5))
    score = cm.phm08_score(np.array([7.0, 20.0]), np.array([20.0, 10.0]))
    assert score == pytest.approx(2 * (math.e - 1))


def test_cmapss_protocol_learns_the_drift(tmp_path: Path) -> None:
    """On a clean linear drift the baseline predicts the last-cycle RUL within a few cycles."""
    result = cm.run_protocol(_cmapss_folder(tmp_path))
    assert list(result["subsets"]) == ["FD001"]
    assert result["subsets"]["FD001"]["engines"] == 3
    assert result["subsets"]["FD001"]["rmse"] < 15.0


def test_skip_path_without_data(tmp_path: Path, capsys) -> None:
    """An empty folder is a clean skip: exit 0, message, no output file."""
    out = tmp_path / "r.json"
    for kind in ("tep", "cmapss"):
        assert run_benchmarks.main([kind, "--data", str(tmp_path), "--out", str(out)]) == 0
    assert capsys.readouterr().out.count("SKIP") == 2 and not out.exists()


def test_cli_writes_results_json(tmp_path: Path) -> None:
    """With data present the CLI writes valid JSON with the protocol name."""
    out = tmp_path / "r.json"
    folder = _cmapss_folder(tmp_path / "d")
    assert run_benchmarks.main(["cmapss", "--data", str(folder), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["protocol"] == "cmapss_degradation_v1"
