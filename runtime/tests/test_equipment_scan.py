"""Verify live equipment alarms using reproducible synthetic pump measurements.

Hysteresis must count uninterrupted eligible cycles rather than transient excursions.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from crosscut_anomaly.equipment_learning import learn_equipment
from crosscut_connectors.base import LiveValue
from crosscut_runtime.jobs import equipment_scan


def _pump_training() -> tuple:
    """Build aligned floating-point channels from synthetic pump speed and current."""
    generator = np.random.default_rng(216)
    times = np.arange(600, dtype=float)
    output = 50 + 10 * np.sin(times / 25)
    data = {"PV": output + generator.normal(0, 0.1, 600), "SP": output,
            "OUT": output, "MODE": np.ones(600), "RUN": np.ones(600),
            "CURRENT": 2 * output + generator.normal(0, 0.2, 600)}
    equipment = {"id": "pump", "loops": ["flow"], "running": {"tag": "RUN", "above": 0.5},
                 "signals": [{"tag": "CURRENT", "kind": "current"}]}
    loops = [{"id": "flow", "pv": "PV", "sp": "SP", "out": "OUT", "mode": "MODE"}]
    return times, data, equipment, loops


@pytest.fixture
def pump_job(tmp_path: Path) -> tuple:
    """Fit a synthetic pump and return a controllable live scanner."""
    times, data, equipment, loops = _pump_training()
    model = learn_equipment(times, data, equipment, loops)
    folder = tmp_path / "_anomaly" / "equipment"
    folder.mkdir(parents=True)
    (folder / "pump.model.json").write_text(json.dumps(model.to_dict()))
    values = {tag: float(column[400]) for tag, column in data.items()}
    connector = SimpleNamespace(read_live=lambda tags: {
        tag: LiveValue(values[tag], 0, "2026-01-01T00:00:00Z") for tag in tags})
    job = equipment_scan.EquipmentScanJob({"equipment": ["pump"], "period_s": 1},
                                         {"equipment": [equipment], "loops": loops},
                                         connector, tmp_path)
    job.clock = lambda: 1767225600.0
    return job, values


def _result(is_abnormal: bool) -> dict:
    """Return deterministic statistics to isolate the alarm counter behaviour."""
    return {"t2": None, "spe": None, "contributions": {"spe": {"PV": 1.0}},
            "residuals": {"CURRENT": 8.0 if is_abnormal else 0.0},
            "ewma": {"CURRENT": 8.0 if is_abnormal else 0.0}}


def test_persistence_opens_only_after_three_abnormal_cycles(
    pump_job: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient excursion cannot open an operator event."""
    job, _ = pump_job
    monkeypatch.setattr(equipment_scan, "score", lambda model, row: _result(True))
    assert job.run()["equipment"]["pump"]["status"] == "ok"
    assert job.run()["equipment"]["pump"]["status"] == "ok"
    assert job.run()["equipment"]["pump"]["status"] == "anomaly"


def test_clear_requires_five_consecutive_normal_cycles(
    pump_job: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ISA-18.2 clear hysteresis prevents alarm chatter near the threshold."""
    job, _ = pump_job
    job.job_doc["persistence"] = 1
    monkeypatch.setattr(equipment_scan, "score", lambda model, row: _result(True))
    job.run()
    monkeypatch.setattr(equipment_scan, "score", lambda model, row: _result(False))
    job.run()
    job.run()
    job.run()
    assert job.run()["equipment"]["pump"]["status"] == "anomaly"
    assert job.run()["equipment"]["pump"]["status"] == "ok"
    assert json.loads(job.events_path.read_text().splitlines()[-1])["closed_utc"] is not None


def test_stopped_equipment_suppresses_faults(pump_job: tuple) -> None:
    """Running evidence is required before scoring a fault."""
    job, values = pump_job
    values.update(RUN=0.0, CURRENT=1000.0)
    assert job.run()["equipment"]["pump"]["status"] == "stopped"
    assert not job.events_path.exists()


def test_shelved_equipment_does_not_open_events(pump_job: tuple) -> None:
    """An operator shelf suppresses event creation until its UTC expiry."""
    job, values = pump_job
    job.job_doc["persistence"] = 1
    values["CURRENT"] = 1000.0
    folder = job.root / "_runtime"
    folder.mkdir()
    (folder / "shelved.json").write_text(json.dumps({"pump": "2099-01-01T00:00:00Z"}))
    assert job.run()["equipment"]["pump"]["open_event"] is None
    assert not job.events_path.exists()


def test_event_explains_the_fitted_pump_fault(pump_job: tuple) -> None:
    """A learned current residual identifies the signal and its positive trend."""
    job, values = pump_job
    job.job_doc["persistence"] = 1
    job.run()
    values["CURRENT"] += 100.0
    event = job.run()["equipment"]["pump"]["open_event"]
    assert event["equipment"] == "pump"
    assert event["closed_utc"] is None
    assert event["peak"] > 1
    assert event["contributions"]
    assert event["loops_affected"] == ["flow"]
    assert event["residuals"][0]["tag"] == "CURRENT"
    assert event["residuals"][0]["z"] > 3
    assert event["residuals"][0]["trend"] == 1


def test_missing_model_is_reported_without_sampling(pump_job: tuple) -> None:
    """An absent trained model remains distinguishable from healthy equipment."""
    job, _ = pump_job
    (job.root / "_anomaly" / "equipment" / "pump.model.json").unlink()
    assert job.run()["equipment"]["pump"]["status"] == "no_model"


def test_missing_good_value_breaks_persistence(pump_job: tuple,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Bad-quality cycles cannot join two otherwise separate excursions."""
    job, _ = pump_job
    monkeypatch.setattr(equipment_scan, "score", lambda model, row: _result(True))
    job.run()
    job.run()
    read_live = job.connector.read_live
    job.connector.read_live = lambda tags: {}
    job.run()
    job.connector.read_live = read_live
    assert job.run()["equipment"]["pump"]["status"] == "ok"


def test_restart_keeps_the_existing_open_identity(pump_job: tuple,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Restarting the runtime must not duplicate the operator's active alarm."""
    job, _ = pump_job
    job.job_doc["persistence"] = 1
    monkeypatch.setattr(equipment_scan, "score", lambda model, row: _result(True))
    original = job.run()["equipment"]["pump"]["open_event"]
    restarted = equipment_scan.EquipmentScanJob(job.job_doc, job.site, job.connector, job.root)
    restarted.clock = lambda: job.clock() + 10
    event = restarted.run()["equipment"]["pump"]["open_event"]
    assert event["opened_utc"] == original["opened_utc"]


def test_startup_history_primes_persistence(pump_job: tuple,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """History backfill provides chronological eligible cycles before the first live read."""
    job, values = pump_job
    job.connector.capabilities = lambda: {"history"}
    job.connector.history = lambda tags, start, end, period: {
        tag: [{"timestamp_utc": "2025-12-31T23:59:58Z", "value": values[tag], "quality": 0},
              {"timestamp_utc": "2025-12-31T23:59:59Z", "value": values[tag], "quality": 0}]
        for tag in tags}
    monkeypatch.setattr(equipment_scan, "score", lambda model, row: _result(True))
    result = job.run()["equipment"]["pump"]
    assert result["status"] == "anomaly"
    assert result["backfill"]["samples"] == 10


def test_service_records_equipment_state(pump_job: tuple,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Scheduled equipment results are available through the runtime state store."""
    from crosscut_runtime.service import RuntimeService
    from crosscut_runtime.store import RuntimeStore

    job, _ = pump_job
    job.job_doc.update(id="pump-scan", kind="equipment_scan", source="source", enabled=True)
    job.site["sources"] = [{"id": "source"}]
    store = RuntimeStore(job.root)
    store.save_jobs({"schema_version": 1, "jobs": [job.job_doc]})
    monkeypatch.setattr("crosscut_runtime.service.load_site", lambda root: job.site)
    service = RuntimeService(job.root, lambda source: job.connector, job.clock)
    service.run_once()
    assert store.load_state()["jobs"]["pump-scan"]["equipment"]["pump"]["status"] == "ok"
