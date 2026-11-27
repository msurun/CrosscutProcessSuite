"""Verify the online soft sensor job: validity status, lab bias with delay, backup failover.

A synthetic linear process Y = 2A + B + 5 is fitted once; a controllable connector and clock
drive the job one period at a time.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from crosscut_connectors.base import LiveValue
from crosscut_runtime.jobs.softsensor import SoftSensorJob, state_path
from crosscut_softsensor.config import load_config
from crosscut_softsensor.pls import fit_pls
from crosscut_softsensor.validation_store import code_version, content_hash, file_sha256

T0 = 1_800_000_000.0
PERIOD = 60.0
VALIDATION = {"preset": "belt_scale_backup", "results": {
    "rmse_model": 1.0, "rmse_baseline": 2.0, "scored_coverage": 0.9, "n_samples": 600,
    "baseline": "last_good_instrument_value", "same_information_cutoff": True}}
CONFIG = {
    "schema_version": "1.0.0", "id": "s1", "target_tag": "Y", "input_tags": ["A", "B"],
    "mode": "advisory", "lags_s": [0], "sample_period_s": PERIOD, "lab_delay_s": 3600,
    "backup": {"enabled": True, "measured_tag": "Y", "frozen_s": 100000, "range_lo": 0,
               "range_hi": 200, "return_hold_s": 300},
}


def _stamp(epoch: float) -> str:
    """ISO UTC text of epoch seconds."""
    return datetime.fromtimestamp(epoch, UTC).isoformat()


class Plant:
    """Controllable live values, per-tag quality and source timestamp age."""

    def __init__(self) -> None:
        """Start with a healthy plant at T0."""
        self.now = T0
        self.values = {"A": 10.0, "B": 3.0, "Y": 28.0}
        self.quality = {"A": 0, "B": 0, "Y": 0}
        self.age = {"A": 0.0, "B": 0.0, "Y": 0.0}

    def read_live(self, tags: list[str]) -> dict[str, LiveValue]:
        """The current samples of ``tags``."""
        return {t: LiveValue(self.values[t], self.quality[t], _stamp(self.now - self.age[t]))
                for t in tags}


@pytest.fixture
def world(tmp_path: Path) -> tuple[SoftSensorJob, Plant, Path]:
    """A fitted sensor on disk and a job bound to the controllable plant."""
    rng = np.random.default_rng(157)
    x = rng.uniform([5, 1], [15, 5], size=(400, 2))
    y = 2 * x[:, 0] + x[:, 1] + 5 + rng.normal(0, 0.05, 400)
    config = load_config(CONFIG)
    folder = tmp_path / "_softsensor"
    folder.mkdir()
    (folder / "s1.json").write_text(json.dumps(CONFIG))
    (folder / "s1.model.json").write_text(json.dumps(fit_pls(x, y, config).to_dict()))
    plant = Plant()
    job = SoftSensorJob({"id": "s1", "period_s": PERIOD}, plant, tmp_path)
    job.clock = lambda: plant.now
    return job, plant, tmp_path


def _mode(root: Path, mode: str, validation: bool = True) -> None:
    """Write the deployment and a record shaped like the server-side validation (test double)."""
    (root / "_softsensor" / "s1.deployment.json").write_text(json.dumps({"mode": mode}))
    if validation:
        folder = root / "_softsensor"
        record = {**VALIDATION, "code_version": code_version(),
                  "model_file_sha256": file_sha256(folder / "s1.model.json")}
        record["hash"] = content_hash(record)
        (folder / "s1.validation.json").write_text(json.dumps(record))


def _cycle(job: SoftSensorJob, plant: Plant, steps: int = 1) -> dict:
    """Advance the clock by whole periods and run; return the last output."""
    out: dict = {}
    for _ in range(steps):
        plant.now += PERIOD
        out = job.run()["softsensor"]
    return out


def test_valid_inputs_give_a_good_value(world: tuple) -> None:
    """Healthy inputs: status good, value = 2A + B + 5, shadow output never used downstream."""
    job, plant, root = world
    _mode(root, "shadow")
    output = _cycle(job, plant)["output"]
    assert output["status"] == "good" and output["reason"] == ""
    assert output["value"] == pytest.approx(28.0, abs=0.3)
    assert output["used_downstream"] is False
    assert state_path(root, "s1").is_file()


def test_stale_and_bad_inputs_degrade_the_status_with_a_reason(world: tuple) -> None:
    """A stale input gives bad with the tag and reason; extrapolation gives uncertain."""
    job, plant, root = world
    _mode(root, "shadow")
    _cycle(job, plant)
    plant.age["A"] = 1000.0
    stale = _cycle(job, plant)["output"]
    assert stale["status"] == "bad" and stale["reason"] == "A:stale" and stale["value"] is None
    plant.age["A"], plant.quality["B"] = 0.0, 2
    assert _cycle(job, plant)["output"]["reason"] == "B:bad_quality"
    plant.quality["B"], plant.values["A"] = 0, 500.0
    far = _cycle(job, plant)["output"]
    assert far["status"] == "uncertain" and far["reason"] in ("out_of_range", "extrapolation")


def test_lab_bias_waits_for_the_report_delay(world: tuple) -> None:
    """A lab value is used only after stamp + delay and is paired with the estimate at its stamp."""
    job, plant, root = world
    _mode(root, "shadow")
    _cycle(job, plant)
    stamp = plant.now
    (root / "_softsensor" / "s1.lab.csv").write_text(f"sample_time,value\n{stamp!r},31.0\n")
    plant.now += 1800
    assert _cycle(job, plant)["last_lab"] is None
    plant.now += 1800
    out = _cycle(job, plant)
    assert out["last_lab"]["residual"] == pytest.approx(3.0, abs=0.3)
    assert out["output"]["bias"] == pytest.approx(out["last_lab"]["residual"])
    assert out["output"]["value"] == pytest.approx(31.0, abs=0.3)


def test_backup_fails_over_and_returns_with_hysteresis(world: tuple) -> None:
    """Backup uses the soft sensor while the instrument is bad; it returns after the hold time."""
    job, plant, root = world
    _mode(root, "backup")
    plant.values["Y"] = 28.0
    first = _cycle(job, plant)["output"]
    assert first["source"] == "instrument" and first["used_downstream"] is False
    plant.quality["Y"] = 2
    failed = _cycle(job, plant)
    assert failed["output"]["source"] == "softsensor" and failed["output"]["used_downstream"]
    assert failed["output"]["value"] == pytest.approx(28.0, abs=0.3)
    plant.quality["Y"] = 0
    assert _cycle(job, plant, 2)["output"]["source"] == "softsensor"  # valid < return_hold_s
    plant.quality["Y"] = 2
    _cycle(job, plant)  # a flicker restarts the hold
    plant.quality["Y"] = 0
    assert _cycle(job, plant, 3)["output"]["source"] == "softsensor"
    back = _cycle(job, plant, 3)
    assert back["output"]["source"] == "instrument"
    assert [(e["from"], e["to"]) for e in back["events"]] == [
        ("instrument", "softsensor"), ("softsensor", "instrument")]
    assert back["events"][0]["reason"] == "bad_quality"


def test_backup_without_a_passing_gate_runs_as_shadow(world: tuple) -> None:
    """Without a stored validation the job never leaves shadow, whatever the file says."""
    job, plant, root = world
    _mode(root, "primary", validation=False)
    out = _cycle(job, plant)
    assert out["mode"] == "primary" and out["effective_mode"] == "shadow"
    assert out["output"]["used_downstream"] is False


def test_primary_uses_the_soft_sensor_and_state_survives_a_restart(world: tuple) -> None:
    """Primary publishes the corrected estimate; a new job object restores bias and events."""
    job, plant, root = world
    _mode(root, "primary")
    stamp = plant.now
    (root / "_softsensor" / "s1.lab.csv").write_text(f"sample_time,value\n{stamp!r},31.0\n")
    plant.now += 3601
    first = job.run()["softsensor"]
    assert first["output"]["used_downstream"] is True
    fresh = SoftSensorJob({"id": "s1", "period_s": PERIOD}, plant, root)
    fresh.clock = lambda: plant.now + PERIOD
    assert fresh.run()["softsensor"]["last_lab"] == first["last_lab"]
    unfit = SimpleNamespace(read_live=lambda tags: {})
    with pytest.raises(ValueError, match="fit a model first"):
        SoftSensorJob({"id": "nope"}, unfit, root).run()
