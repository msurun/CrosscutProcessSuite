"""Tests of the controller host with fake connector, availability, clock (Phase 2.5, step 5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from crosscut_connectors.base import LiveValue, Snapshot
from crosscut_runtime.controllers.dummy import DummyController
from crosscut_runtime.controllers.host import (
    ControllerHost,
    HostConfig,
    HostPorts,
    record_path,
)
from crosscut_runtime.controllers.protocol import Move
from crosscut_runtime.store import read_variable_status

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
DOC = {
    "id": "c1",
    "cycle_s": 30,
    "variables": [
        {"id": "cv1", "role": "CV", "binding": {"tag": "t.cv1"}},
        {"id": "cv2", "role": "CV", "binding": {"tag": "t.cv2"}},
        {"id": "mv1", "role": "MV", "required": True, "binding": {"loop": "L1"}},
    ],
}
TAGS = {"cv1": ["t.cv1"], "cv2": ["t.cv2"], "mv1": ["t.pv", "t.sp"]}
MOVE = Move("mv1", "t.sp", 42.0, "test")


class FakeClock:
    """Time that advances 1 s per reading; tests jump it with ``t +=``."""

    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


class FakeConnector:
    """Returns healthy values with a fresh time stamp unless told otherwise."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.comm_ok = True
        self.bad_tags: set[str] = set()

    def read_snapshot(self, tag_ids: Any) -> Snapshot:
        stamp = self.clock.t.isoformat()
        values = {
            tag: LiveValue(1.0, 2 if tag in self.bad_tags else 0, stamp) for tag in tag_ids
        }
        return Snapshot(stamp, values, self.comm_ok)


class Rig:
    """Host plus fakes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = FakeClock()
        self.connector = FakeConnector(self.clock)
        self.reasons: list[str] = []
        self.proposed: list[Move] = []
        self.controller = DummyController("c1", [MOVE])
        self.host = self.build()

    def availability(self, targets: list[str]) -> dict[str, dict[str, Any]]:
        return {t: {"available": not self.reasons, "reasons": list(self.reasons)} for t in targets}

    def build(self) -> ControllerHost:
        config = HostConfig(DOC, TAGS, {"mv1": "t.sp"}, self.root)
        ports = HostPorts(self.connector, self.availability, self.proposed.append, self.clock)
        return ControllerHost(self.controller, config, ports)

    def cycle(self, command: str | None = None) -> str:
        if command:
            self.host.request(command)
        return self.host.run_cycle().state

    def start_on(self) -> None:
        assert self.cycle("switch_on") == "on"


def test_starts_off_and_stays_off(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert rig.cycle() == "off"
    assert rig.proposed == [] and rig.controller.steps == 0


def test_guard_refusal_mv_unavailable(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.reasons = ["killed"]
    assert rig.cycle("switch_on") == "standby"
    assert rig.host.record.reason == "mv_unavailable"
    assert rig.controller.initialised == 0


def test_guard_refusal_advisory_only(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.reasons = ["mode_no_write"]
    assert rig.cycle("switch_on") == "standby"
    assert rig.host.record.reason == "advisory_only"


def test_guard_refusal_no_good_cv(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.connector.bad_tags = {"t.cv1", "t.cv2"}
    assert rig.cycle("switch_on") == "standby"
    assert rig.host.record.reason == "no_good_cv"


def test_proposes_only_while_on(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.cycle()
    rig.cycle("switch_on")
    assert rig.controller.initialised == 1 and rig.proposed == []
    rig.cycle()
    assert rig.proposed == [MOVE]
    rig.cycle("standby")
    rig.cycle()
    assert rig.proposed == [MOVE]
    assert rig.host.record.last_explanation == "dummy step 1"


def test_bad_cv_dropped_controller_keeps_running(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    rig.connector.bad_tags = {"t.cv1"}
    assert rig.cycle() == "on"
    seen = {s.variable_id: s.status for s in rig.controller.last_statuses}
    assert seen["cv1"] == "bad" and seen["cv2"] == "good"


def test_required_mv_unavailable_sheds(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    rig.reasons = ["hold_off"]
    assert rig.cycle() == "shed"
    assert rig.host.record.reason == "mv_unavailable"
    count = len(rig.proposed)
    rig.cycle()
    assert len(rig.proposed) == count


def test_bad_mv_status_sheds(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    rig.connector.bad_tags = {"t.pv"}
    assert rig.cycle() == "shed"


def test_comm_loss_sheds(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    rig.connector.comm_ok = False
    assert rig.cycle() == "shed"
    assert rig.host.record.reason == "comm_loss"


def test_three_overruns_shed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    states = []
    for _ in range(3):
        rig.clock.t += timedelta(seconds=120)
        states.append(rig.cycle())
    assert states == ["on", "on", "shed"]
    assert rig.host.record.overruns == 3
    assert rig.host.record.reason == "overruns"


def test_on_time_cycle_resets_consecutive_overruns(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    for _ in range(2):
        rig.clock.t += timedelta(seconds=120)
        rig.cycle()
    rig.clock.t += timedelta(seconds=25)
    rig.cycle()
    assert rig.host.record.consecutive_overruns == 0
    rig.clock.t += timedelta(seconds=120)
    assert rig.cycle() == "on"


def test_shed_to_standby_when_healthy_then_needs_switch_on(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    rig.connector.comm_ok = False
    assert rig.cycle() == "shed"
    rig.connector.comm_ok = True
    assert rig.cycle() == "standby"
    assert rig.cycle() == "standby"
    assert rig.cycle("switch_on") == "on"
    assert rig.controller.initialised == 2


def test_restart_restores_on_as_standby(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    rig.cycle()
    restarted = rig.build()
    assert restarted.record.state == "standby"
    assert restarted.record.reason == "restart"
    assert restarted.record.consecutive_overruns == 0


def test_restart_restores_shed_as_standby_and_off_stays_off(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    rig.reasons = ["killed"]
    rig.cycle()
    assert rig.build().record.state == "standby"
    rig.cycle("switch_off")
    assert rig.build().record.state == "off"


def test_state_file_round_trips_and_statuses_written(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start_on()
    rig.cycle()
    path = record_path(tmp_path, "c1")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "state", "reason", "last_cycle_utc", "last_duration_s", "overruns",
        "consecutive_overruns", "liveness_utc", "last_explanation", "disabled",
    ):
        assert key in data
    assert data["state"] == "on" and data["last_duration_s"] == 1.0
    assert list(path.parent.glob("*.tmp")) == []
    written = read_variable_status(tmp_path)["c1"]
    assert {s["variable_id"] for s in written} == {"cv1", "cv2", "mv1"}


def test_corrupt_record_gives_fresh_off(tmp_path: Path) -> None:
    path = record_path(tmp_path, "c1")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert Rig(tmp_path).host.record.state == "off"


def test_disabled_variable_is_bad_and_persisted(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.host.set_disabled(["cv1"])
    rig.start_on()
    rig.cycle()
    seen = {s.variable_id: s.status for s in rig.controller.last_statuses}
    assert seen["cv1"] == "bad"
    data = json.loads(record_path(tmp_path, "c1").read_text(encoding="utf-8"))
    assert data["disabled"] == ["cv1"]
