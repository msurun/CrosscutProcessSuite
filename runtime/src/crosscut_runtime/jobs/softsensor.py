"""Run one soft sensor online: read role-bound inputs, predict, bias-correct, publish, persist.

The mode (shadow, backup, primary) comes from the audited deployment file; backup and primary
are re-checked against the deployment gate every cycle, so a stale or removed validation drops
the sensor back to shadow. State (bias, buffers, failover events) survives a restart.
"""

from __future__ import annotations

import csv
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_softsensor.config import SoftSensorConfig, load_config
from crosscut_softsensor.deployment import FOLDER, gate_for, read_deployment
from crosscut_softsensor.online import OnlineSensor, stamp_offset
from crosscut_softsensor.pls import PlsModel

from crosscut_runtime.store import write_json_atomic

GOOD_QUALITY = 0  # Connector code for a measurement safe to use.
STALE_PERIODS = 3.0  # Default staleness limit in job periods.
RUNTIME_DIR = Path("_runtime") / "softsensor"


def state_path(root: Path, sid: str) -> Path:
    """File holding the published output and persistent state of one soft sensor."""
    return Path(root) / RUNTIME_DIR / f"{sid}.state.json"


def _epoch(stamp: str, default: float) -> float:
    """Epoch seconds of an ISO timestamp (naive means UTC); ``default`` when unparsable."""
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return default
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()


def read_lab_rows(path: Path) -> list[tuple[float, float]]:
    """(stamp seconds, value) rows of the stored ``<sid>.lab.csv`` (already normalised)."""
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        return [(float(r["sample_time"]), float(r["value"])) for r in csv.DictReader(stream)]


class SoftSensorJob:
    """One soft sensor per job; the scheduler calls ``run`` once per period."""

    def __init__(self, job_doc: dict[str, Any], connector: Any, root: Path) -> None:
        """Bind the job document, an addressed connector and the data root."""
        self.job_doc, self.connector, self.root = job_doc, connector, Path(root)
        self.sid = job_doc.get("softsensor_id", job_doc["id"])
        self.clock = time.time
        self.sensor: OnlineSensor | None = None
        self._model_stamp: tuple[float, float] | None = None

    def _folder(self) -> Path:
        """The soft sensor folder of the data root."""
        return self.root / FOLDER

    def _load(self) -> OnlineSensor:
        """Build the sensor from config and model files; rebuild when they change on disk."""
        config_file = self._folder() / f"{self.sid}.json"
        model_file = self._folder() / f"{self.sid}.model.json"
        if not (config_file.is_file() and model_file.is_file()):
            raise ValueError(f"soft sensor {self.sid!r}: configure and fit a model first")
        stamp = (config_file.stat().st_mtime, model_file.stat().st_mtime)
        if self.sensor is None or stamp != self._model_stamp:
            config: SoftSensorConfig = load_config(json.loads(config_file.read_text("utf-8")))
            model = PlsModel.from_dict(json.loads(model_file.read_text("utf-8")))
            self.sensor = OnlineSensor(config, model)
            self._restore()
            self._model_stamp = stamp
        return self.sensor

    def _restore(self) -> None:
        """Reload the persisted dynamic state after a restart or a refit (same sensor id)."""
        path = state_path(self.root, self.sid)
        if self.sensor is not None and path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            if "sensor" in document:
                self.sensor.load_state(document["sensor"])

    def _effective_mode(self) -> tuple[str, dict[str, Any]]:
        """Stored mode, lowered to shadow when backup/primary no longer pass the gate."""
        deployment = read_deployment(self.root, self.sid)
        mode = deployment["mode"]
        if mode in ("backup", "primary"):
            try:
                decision, _ = gate_for(self.root, self.sid)
            except (KeyError, TypeError, ValueError):
                decision = None
            if decision is None or not decision.deploy:
                mode = "shadow"
        return mode, deployment

    def _inputs(
        self, sensor: OnlineSensor, now_s: float
    ) -> tuple[dict[str, float], dict[str, str]]:
        """Good, fresh values by tag and the reason for every unusable tag."""
        config = sensor.config
        tags = [*config.input_tags, *(r.tag for r in config.reference_inputs)]
        if config.backup is not None:
            tags += [config.backup.measured_tag]
            tags += [config.backup.flag_tag] if config.backup.flag_tag else []
        period_s = float(self.job_doc.get("period_s", 60))
        stale_s = float(self.job_doc.get("stale_s", STALE_PERIODS * period_s))
        live = self.connector.read_live(list(dict.fromkeys(tags)))
        values: dict[str, float] = {}
        problems: dict[str, str] = {}
        for tag in dict.fromkeys(tags):
            sample = live.get(tag)
            if sample is None or sample.value is None or not math.isfinite(sample.value):
                problems[tag] = "no_value"
            elif sample.quality != GOOD_QUALITY:
                problems[tag] = "bad_quality"
            elif now_s - _epoch(sample.timestamp_utc, now_s) > stale_s:
                problems[tag] = "stale"
            else:
                values[tag] = float(sample.value)
        return values, problems

    def run(self) -> dict[str, Any]:
        """One cycle: publish the output and persist the state; returns the status summary."""
        sensor, now_s = self._load(), self.clock()
        mode, deployment = self._effective_mode()
        stamp = deployment["lab_stamp"]
        sensor.apply_labs(now_s, read_lab_rows(self._folder() / f"{self.sid}.lab.csv"),
                          stamp_offset(stamp["meaning"], float(stamp["window_s"])))
        values, problems = self._inputs(sensor, now_s)
        output = sensor.tick(now_s, values, problems, mode) if mode != "off" else None
        summary = {"mode": deployment["mode"], "effective_mode": mode, "output": output,
                   "last_lab": sensor.last_lab, "events": sensor.events[-20:]}
        write_json_atomic(state_path(self.root, self.sid), {**summary, "sensor": sensor.to_dict()})
        return {"samples": 1, "softsensor": summary}
