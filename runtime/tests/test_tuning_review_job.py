"""Tests of TuningReviewJob: verdicts written to <id>.review.json files (ADR 014 section 5).

The job never rewrites the proposal record; `Setup.load` merges record and review file the way
the API does (status and review taken from the review file).

A temp data root holds a site with one loop, a HistoryStore filled with synthetic series and
proposal JSON files; a fake clock decides which window is complete. Model theta=60 s, tau=120 s
gives W=3600 s windows, a 540 s settling gap and a 180 s cycle (early check after 540 s).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_runtime.history import HistoryStore, history_path
from crosscut_runtime.jobs.tuning_review import TuningReviewJob, utc_to_epoch
from crosscut_runtime.store import RuntimeStore
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
SCHEMA = SCHEMAS / "tuning-proposal.schema.json"
REVIEW_SCHEMA = SCHEMAS / "tuning-review.schema.json"
APPLIED_AT = "2026-11-05T10:00:00Z"
T_APPLY = utc_to_epoch(APPLIED_AT)
STEP_S = 10.0
WINDOW_S = 3600.0
SETTLE_S = 540.0
EARLY_S = 540.0
AFTER_START = T_APPLY + SETTLE_S
AFTER_END = AFTER_START + WINDOW_S
TAGS = {"pv": "FIC101.pv", "sp": "FIC101.sp", "out": "FIC101.out", "mode": "FIC101.mode"}
UUID_A = "0b9f5a52-4c1e-4c63-9d5e-6f3a1e2b7c10"
UUID_B = "1c0a6b63-5d2f-4d74-8e6f-7a4b2f3c8d21"
ITEM = {"param": "gain", "target": "FIC101.KP", "unit": "1", "from": 1.0, "to": 1.4}


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: float) -> None:
        """Start at ``now`` epoch seconds."""
        self.now = now

    def __call__(self) -> float:
        """Return the current epoch seconds."""
        return self.now


def record(proposal_id: str = UUID_A, **changes: Any) -> dict[str, Any]:
    """A complete applied proposal record of loop FIC-101."""
    doc: dict[str, Any] = {
        "id": proposal_id, "version": 1, "loop_id": "FIC-101", "created_by": "alice",
        "created_at": "2026-11-05T09:00:00Z", "expires_at": "2026-11-05T17:00:00Z",
        "vendor_form": {"key": "siemens_pid_compact", "evidence": "partly_verified"},
        "source": {
            "method": "simc", "robustness": 0.5,
            "model": {"K": 1.2, "tau_s": 120.0, "theta_s": 60.0, "process_kind": "self_regulating"},
            "window": {"dataset_id": "wb", "start": "2026-11-05T00:00:00Z",
                       "end": "2026-11-05T06:00:00Z"},
            "report_digest": "a" * 64,
        },
        "confidence": {"level": "medium", "reasons": ["x"]}, "caveats": ["c"], "items": [ITEM],
        "preview": {"label": "model prediction", "iae_ratio": 0.8,
                    "overshoot_pct": {"current": 12.0, "proposed": 6.0},
                    "settling_time_s": {"current": 300.0, "proposed": 220.0},
                    "ms": {"current": 1.9, "proposed": 1.5}},
        "rollback_of": None, "status": "applied", "gateway_key": "b" * 64,
        "applied": {"from_read": {"FIC101.KP": 1.0}, "to_read": {"FIC101.KP": 1.4},
                    "t": APPLIED_AT, "approver": "bob"},
        "review": None,
    }
    doc.update(changes)
    return doc


def write_site(root: Path) -> None:
    """Write a site with loop FIC-101 and its four tags."""
    loop = {"id": "FIC-101", "pv": TAGS["pv"], "sp": TAGS["sp"], "out": TAGS["out"],
            "mode": TAGS["mode"]}
    site = {"schema_version": 1, "site": {"name": "t"}, "tags": [], "loops": [loop]}
    (root / "_site").mkdir(parents=True, exist_ok=True)
    (root / "_site" / "site.json").write_text(json.dumps(site), encoding="utf-8")


def write_record(root: Path, doc: dict[str, Any]) -> Path:
    """Store a proposal record as <root>/_tuning/proposals/<id>.json."""
    folder = root / "_tuning" / "proposals"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc['id']}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def fill(history: HistoryStore, start: float, end: float, error: np.ndarray, mode: float = 1.0,
         tags: dict[str, str] = TAGS) -> None:
    """Add one window of samples every STEP_S: SP 50, PV = SP + error, OUT follows the error."""
    stamps = np.arange(start, end, STEP_S)
    err = np.resize(error, len(stamps))
    rows = []
    for ts, e in zip(stamps, err, strict=True):
        rows += [(tags["pv"], float(ts), 50.0 + float(e)), (tags["sp"], float(ts), 50.0),
                 (tags["out"], float(ts), 40.0 + 0.5 * float(e)), (tags["mode"], float(ts), mode)]
    history.append(rows)


def noise(std: float, seed: int = 3) -> np.ndarray:
    """White noise of one window length, in PV units."""
    return np.random.default_rng(seed).normal(0.0, std, int(WINDOW_S / STEP_S))


def wave(amplitude: float) -> np.ndarray:
    """A slow oscillation of 20 samples (200 s) period plus a little noise."""
    k = np.arange(int(WINDOW_S / STEP_S))
    signal: np.ndarray = amplitude * np.sin(2 * np.pi * k / 20.0) + noise(0.05, 5)
    return signal


def validator() -> Draft202012Validator:
    """Validator of the tuning-proposal schema."""
    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


class Setup:
    """A temp root with site, history and a job on a fake clock."""

    def __init__(self, root: Path, now: float = AFTER_END + 60.0) -> None:
        """Build the root, the history store and the job."""
        write_site(root)
        self.root = root
        self.history = HistoryStore(history_path(root))
        self.clock = Clock(now)
        doc = {"id": "rev", "kind": "tuning_review", "source": "dcs", "loops": ["FIC-101"],
               "period_s": 60.0, "enabled": True}
        self.job = TuningReviewJob(doc, root, self.history, self.clock)

    def load(self, path: Path) -> dict[str, Any]:
        """The record merged with its review file: status and review come from the review."""
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        review_file = path.with_name(f"{path.stem}.review.json")
        if review_file.exists():
            stored = json.loads(review_file.read_text(encoding="utf-8"))
            review_validator = Draft202012Validator(json.loads(REVIEW_SCHEMA.read_text("utf-8")))
            assert review_validator.is_valid(stored)
            loaded = {**loaded, "status": stored["status"], "review": stored["review"]}
        return loaded


def windows(setup: Setup, before: np.ndarray, after: np.ndarray, after_mode: float = 1.0) -> None:
    """Fill the before and the after window of the standard proposal."""
    fill(setup.history, T_APPLY - WINDOW_S, T_APPLY, before)
    fill(setup.history, AFTER_START, AFTER_END, after, after_mode)


@pytest.mark.parametrize(
    ("label", "before", "after", "verdict"),
    [
        ("improved", noise(1.0), noise(0.4, 4), "improved"),
        ("neutral", noise(1.0), noise(1.0, 4), "neutral"),
        ("worse", noise(1.0), noise(2.0, 4), "worse"),
        ("oscillating", noise(1.0), wave(2.0), "worse"),
    ],
)
def test_verdict_is_written_back(
    tmp_path: Path, label: str, before: np.ndarray, after: np.ndarray, verdict: str
) -> None:
    setup = Setup(tmp_path)
    windows(setup, before, after)
    path = write_record(tmp_path, record())
    result = setup.job.run()
    stored = setup.load(path)
    assert result == {"reviewed": [UUID_A], "pending": [], "errors": 0}, label
    assert stored["status"] == f"reviewed:{verdict}"
    assert stored["review"]["verdict"] == verdict
    assert validator().is_valid(stored)
    assert stored["review"]["before"]["n"] == 360 and stored["review"]["t"].endswith("Z")
    assert set(stored["review"]["metrics"]) == {"error_std_ratio", "iae_per_h_ratio",
                                                "out_travel_ratio"}


def test_improved_reports_error_ratio_below_one(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    path = write_record(tmp_path, record())
    setup.job.run()
    review = setup.load(path)["review"]
    assert review["metrics"]["error_std_ratio"] < 0.6
    assert review["reasons"] == ["error_std_down_travel_ok"]


def test_too_few_samples_is_insufficient_data(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    fill(setup.history, T_APPLY - WINDOW_S, T_APPLY, noise(1.0))
    fill(setup.history, AFTER_START, AFTER_START + 20 * STEP_S, noise(1.0, 4))
    path = write_record(tmp_path, record())
    setup.job.run()
    review = setup.load(path)["review"]
    assert review["verdict"] == "insufficient_data" and "few_samples" in review["reasons"]
    assert setup.load(path)["status"] == "reviewed:insufficient_data"


def test_loop_left_auto_is_insufficient_data(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    fill(setup.history, T_APPLY - WINDOW_S, T_APPLY, noise(1.0))
    fill(setup.history, AFTER_START, AFTER_START + 2000, noise(1.0, 4), 1.0)
    fill(setup.history, AFTER_START + 2000, AFTER_END, noise(1.0, 6), 0.0)
    path = write_record(tmp_path, record())
    setup.job.run()
    review = setup.load(path)["review"]
    assert review["verdict"] == "insufficient_data" and "low_service_factor" in review["reasons"]


def test_waits_until_after_window_is_complete(tmp_path: Path) -> None:
    setup = Setup(tmp_path, now=AFTER_START + 1000.0)
    windows(setup, noise(1.0), noise(0.4, 4))
    path = write_record(tmp_path, record())
    before_text = path.read_text(encoding="utf-8")
    assert setup.job.run() == {"reviewed": [], "pending": [UUID_A], "errors": 0}
    assert path.read_text(encoding="utf-8") == before_text
    setup.clock.now = AFTER_END
    assert setup.job.run()["reviewed"] == [UUID_A]


def test_early_worse_then_final_verdict(tmp_path: Path) -> None:
    setup = Setup(tmp_path, now=AFTER_START + EARLY_S + STEP_S)
    windows(setup, noise(1.0), wave(2.0))
    path = write_record(tmp_path, record())
    assert setup.job.run() == {"reviewed": [], "pending": [UUID_A], "errors": 0}
    early = setup.load(path)
    assert early["status"] == "reviewing" and early["review"]["early"] == "worse_early"
    assert early["review"]["verdict"] == "worse_early" and validator().is_valid(early)
    stamp = path.stat().st_mtime_ns
    setup.job.run()
    assert path.stat().st_mtime_ns == stamp
    setup.clock.now = AFTER_END + 1.0
    assert setup.job.run()["reviewed"] == [UUID_A]
    final = setup.load(path)
    assert final["status"] == "reviewed:worse" and final["review"]["early"] == "worse_early"
    assert validator().is_valid(final)


def test_calm_loop_has_no_early_warning(tmp_path: Path) -> None:
    setup = Setup(tmp_path, now=AFTER_START + EARLY_S + STEP_S)
    windows(setup, noise(1.0), noise(0.4, 4))
    path = write_record(tmp_path, record())
    assert setup.job.run()["pending"] == [UUID_A]
    assert setup.load(path)["status"] == "applied"


@pytest.mark.parametrize("flag", [True, "param_changed_externally"])
def test_external_change_flag_is_insufficient_data(tmp_path: Path, flag: Any) -> None:
    setup = Setup(tmp_path, now=T_APPLY + 60.0)
    doc = record()
    doc["applied"]["invalid"] = flag
    path = write_record(tmp_path, doc)
    assert setup.job.run()["reviewed"] == [UUID_A]
    stored = setup.load(path)
    assert stored["review"]["reasons"] == ["param_changed_externally"]
    assert stored["status"] == "reviewed:insufficient_data" and validator().is_valid(stored)


def test_corrupt_and_invalid_files_are_skipped_and_logged(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    folder = tmp_path / "_tuning" / "proposals"
    folder.mkdir(parents=True)
    (folder / "bad.json").write_text("{not json", encoding="utf-8")
    bad_schema = record(UUID_B)
    del bad_schema["items"]
    write_record(tmp_path, bad_schema)
    write_record(tmp_path, record())
    result = setup.job.run()
    assert result == {"reviewed": [UUID_A], "pending": [], "errors": 2}
    messages = [e["message"] for e in RuntimeStore(tmp_path).read_log() if e["level"] == "error"]
    assert len(messages) == 2
    setup.job.run()
    assert len(RuntimeStore(tmp_path).read_log()) == 2


def test_final_and_foreign_records_are_never_touched(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    done = record(UUID_B, status="reviewed:neutral",
                  review={"verdict": "neutral", "t": "2026-11-05T12:00:00Z"})
    other = record("2c1b7c74-6e30-4e85-9f70-8b5c3a4d9e32", loop_id="LIC-200")
    paths = [write_record(tmp_path, doc) for doc in (done, other)]
    texts = [p.read_text(encoding="utf-8") for p in paths]
    assert setup.job.run() == {"reviewed": [], "pending": [], "errors": 0}
    assert [p.read_text(encoding="utf-8") for p in paths] == texts


def test_second_run_is_idempotent(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    path = write_record(tmp_path, record())
    setup.job.run()
    first = path.read_text(encoding="utf-8")
    setup.clock.now += 3600.0
    assert setup.job.run() == {"reviewed": [], "pending": [], "errors": 0}
    assert path.read_text(encoding="utf-8") == first


def test_missing_loop_tags_give_insufficient_data(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    site = json.loads((tmp_path / "_site" / "site.json").read_text(encoding="utf-8"))
    del site["loops"][0]["sp"]
    (tmp_path / "_site" / "site.json").write_text(json.dumps(site), encoding="utf-8")
    path = write_record(tmp_path, record())
    setup.job.run()
    assert setup.load(path)["review"]["reasons"] == ["loop_tags_missing"]


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path: Path, monkeypatch: Any) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    path = write_record(tmp_path, record())
    original = path.read_text(encoding="utf-8")

    def broken_replace(_src: Any, _dst: Any) -> None:
        """Simulate a crash at the moment of the swap."""
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", broken_replace)
    assert setup.job.run()["errors"] == 1
    assert path.read_text(encoding="utf-8") == original
    assert list(path.parent.glob("*.tmp")) == []
    monkeypatch.undo()
    assert setup.job.run()["reviewed"] == [UUID_A]
    assert list(path.parent.glob("*.tmp")) == []


def test_only_time_aligned_rows_are_used(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    extra = [(TAGS["pv"], AFTER_START + 5.0 + k * STEP_S, 99.0) for k in range(50)]
    setup.history.append(extra)
    path = write_record(tmp_path, record())
    setup.job.run()
    assert setup.load(path)["review"]["after"]["n"] == 360
    assert setup.load(path)["review"]["verdict"] == "improved"


def test_review_goes_to_a_separate_file_and_the_record_is_never_rewritten(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    path = write_record(tmp_path, record())
    original = path.read_bytes()
    stamp = path.stat().st_mtime_ns
    setup.job.run()
    review_file = path.with_name(f"{UUID_A}.review.json")
    stored = json.loads(review_file.read_text(encoding="utf-8"))
    assert path.read_bytes() == original and path.stat().st_mtime_ns == stamp
    assert stored["proposal_id"] == UUID_A and stored["final"] is True
    assert stored["status"] == "reviewed:improved"
    assert setup.job.run() == {"reviewed": [], "pending": [], "errors": 0}


def test_a_review_file_is_not_taken_for_a_record(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    write_record(tmp_path, record())
    setup.job.run()
    result = setup.job.run()
    assert result["errors"] == 0 and result["reviewed"] == []


def test_early_review_file_is_not_final_and_leaves_the_record_alone(tmp_path: Path) -> None:
    setup = Setup(tmp_path, now=AFTER_START + EARLY_S + STEP_S)
    windows(setup, noise(1.0), wave(2.0))
    path = write_record(tmp_path, record())
    original = path.read_bytes()
    setup.job.run()
    stored = json.loads(path.with_name(f"{UUID_A}.review.json").read_text(encoding="utf-8"))
    assert stored["final"] is False and stored["status"] == "reviewing"
    assert path.read_bytes() == original


def test_invalid_review_file_is_skipped_and_logged(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    windows(setup, noise(1.0), noise(0.4, 4))
    path = write_record(tmp_path, record())
    path.with_name(f"{UUID_A}.review.json").write_text('{"final": true}', encoding="utf-8")
    assert setup.job.run() == {"reviewed": [], "pending": [], "errors": 1}
