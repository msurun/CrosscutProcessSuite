"""Liveness beats of the controller cycle and of the runtime process (ADR 015, #112)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from crosscut_runtime.controllers.gateway_adapter import make_liveness_sender
from crosscut_runtime.controllers.runtime_beat import BEAT_PERIOD_S, RuntimeBeat

from .test_controller_job import SITE, Clock, _service, _site_with


class Sent:
    """A sender factory that records every beat."""

    def __init__(self) -> None:
        self.beats: list[tuple[Any, ...]] = []

    def __call__(self, root: Path, sender_id: str, kind: str) -> Any:
        return lambda *args: self.beats.append(args)


def test_sender_sends_a_signed_liveness_command(tmp_path: Path, monkeypatch: Any) -> None:
    """The adapter sends ``liveness`` as the service principal with gw.propose only."""
    client = Mock()
    monkeypatch.setitem(sys.modules, "crosscut_api.gateway_client",
                        SimpleNamespace(FileGatewayClient=Mock(return_value=client)))
    monkeypatch.setitem(sys.modules, "crosscut_api.auth.actor",
                        SimpleNamespace(ActorContext=SimpleNamespace))
    send = make_liveness_sender(tmp_path, "c1", "controller")
    send("controller", "c1", "on", 3, 30.0, 3, ["t.sp"])
    args = client.liveness.call_args.args[0]
    assert args == {"kind": "controller", "id": "c1", "state": "on", "count": 3,
                    "cycle_s": 30.0, "liveness_cycles": 3, "targets": ["t.sp"]}
    actor = client.liveness.call_args.kwargs["actor"]
    assert actor.actor == "svc:controller:c1"
    assert actor.permissions == frozenset({"gw.propose"})


def test_unreachable_gateway_never_stops_the_cycle(tmp_path: Path, monkeypatch: Any) -> None:
    """A timeout or refusal of the beat is logged, not raised."""
    client = Mock()
    client.liveness.side_effect = TimeoutError("gateway did not answer")
    monkeypatch.setitem(sys.modules, "crosscut_api.gateway_client",
                        SimpleNamespace(FileGatewayClient=Mock(return_value=client)))
    monkeypatch.setitem(sys.modules, "crosscut_api.auth.actor",
                        SimpleNamespace(ActorContext=SimpleNamespace))
    make_liveness_sender(tmp_path, "c1", "controller")("controller", "c1", "on", 1, 30.0, 3, [])


def test_controller_cycle_sends_its_beat(tmp_path: Path) -> None:
    """Every controller cycle beats with state, count, cycle_s, liveness_cycles and targets."""
    site = _site_with(lambda s: s["controllers"][0].update({"liveness_cycles": 4}))
    sent = Sent()
    service = _service(tmp_path, [], site)
    service._liveness_factory = sent  # noqa: SLF001
    service.run_once()
    service.run_once()
    beats = [b for b in sent.beats if b[0] == "controller"]
    assert [b[3] for b in beats] == [1, 2]
    assert beats[0] == ("controller", "c1", "off", 1, 30.0, 4, ["t.sp"])


def test_default_liveness_cycles_is_three(tmp_path: Path) -> None:
    """Without liveness_cycles in the site the beat says 3."""
    sent = Sent()
    service = _service(tmp_path, [], SITE)
    service._liveness_factory = sent  # noqa: SLF001
    service.run_once()
    assert sent.beats[0][5] == 3


def test_runtime_beat_is_rate_limited_and_needs_controllers() -> None:
    """The process beat goes out every BEAT_PERIOD_S and only while controllers are hosted."""
    now = [0.0]
    sent = Sent()
    beat = RuntimeBeat(Path("."), lambda: now[0], sent)
    assert beat.maybe_send(False) is False
    assert beat.maybe_send(True) is True
    now[0] += BEAT_PERIOD_S - 1
    assert beat.maybe_send(True) is False
    now[0] += 1
    assert beat.maybe_send(True) is True
    assert [b[3] for b in sent.beats] == [1, 2]
    assert sent.beats[0][:3] == ("runtime", "runtime", "running")


def test_service_without_factory_sends_nothing(tmp_path: Path) -> None:
    """A service built with injected gateway ports (tests) sends no beat."""
    service = _service(tmp_path, [])
    service.run_once()
    assert service._liveness_factory is None  # noqa: SLF001


def test_runtime_service_beats_while_hosting_a_controller(tmp_path: Path) -> None:
    """RuntimeService sends the process beat once a controller job exists."""
    sent = Sent()
    service = _service(tmp_path, [])
    service._runtime_beat = RuntimeBeat(tmp_path, Clock(), sent)  # noqa: SLF001
    service.run_once()
    assert any(b[0] == "runtime" for b in sent.beats)


def test_runtime_beat_precedes_the_first_controller_beat(tmp_path: Path) -> None:
    """The gateway needs both beats before a controller may write: the runtime beats first."""
    sent = Sent()
    service = _service(tmp_path, [])
    service._runtime_beat = RuntimeBeat(tmp_path, Clock(), sent)  # noqa: SLF001
    service._liveness_factory = sent  # noqa: SLF001
    service.run_once()
    assert [b[0] for b in sent.beats][:2] == ["runtime", "controller"]
