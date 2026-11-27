"""MPC controller on the runtime host: model checks, bumpless start, shed, reason codes (#184)."""

from __future__ import annotations

import copy
import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_mpc.artifact import save_ident_model
from crosscut_mpc.identification import IdentifiedModel, PairQuality
from crosscut_runtime.controllers.host import ControllerHost, HostConfig, HostPorts
from crosscut_runtime.controllers.mpc import MpcController
from crosscut_runtime.controllers.mpc_limits import clamp_move
from crosscut_runtime.controllers.mpc_model import ModelRefused, load_bound_model
from crosscut_runtime.controllers.wiring import build_controller_job
from crosscut_runtime.variable_status import VariableStatus

CYCLE_S = 30.0
GOOD = PairQuality(0.99, 3, True, ())
BAD_PAIR = PairQuality(0.2, 1, False, ("free-run R2 too low",))
GAINS = np.array([[1.0, 0.3], [0.2, 0.8]])


def make_model(accepted: bool = True, cycle_s: float = CYCLE_S) -> IdentifiedModel:
    """A 2x2 model: inputs u1, u2 and outputs y1, y2."""
    row = (GOOD, GOOD if accepted else BAD_PAIR)
    return IdentifiedModel(
        ("u1", "u2"), ("y1", "y2"), GAINS, np.full((2, 2), 90.0), np.full((2, 2), 30.0),
        cycle_s, (row, (GOOD, GOOD)), {}, "test",
    )


def variables() -> list[dict[str, Any]]:
    """Catalogue variables: two MVs (move_max 5) and two CVs, y1 with a target."""
    mv = {"operator": {"lo": 0, "hi": 100}, "move_max": 5.0}
    cv = {"operator": {"lo": 0, "hi": 100}}
    return [
        {"id": "u1", "role": "MV", "required": True, "binding": {"loop": "L1"}, "limits": mv},
        {"id": "u2", "role": "MV", "required": True, "binding": {"loop": "L2"}, "limits": mv},
        {"id": "y1", "role": "CV", "binding": {"tag": "t.y1"}, "limits": cv, "target": 50.0},
        {"id": "y2", "role": "CV", "binding": {"tag": "t.y2"}, "limits": cv, "priority": 2},
    ]


def controller_doc(sha: str, artifact: str = "m1") -> dict[str, Any]:
    """The mpc controller entry of the site catalogue."""
    return {"id": "c1", "type": "mpc", "cycle_s": CYCLE_S, "variables": variables(),
            "mpc": {"model": {"artifact": artifact, "sha256": sha},
                    "prediction_horizon": 20, "move_horizon": 4}}


def store(root: Path, model: IdentifiedModel, artifact: str = "m1") -> str:
    """Save the model in the model store of ``root``; the payload hash."""
    return save_ident_model(root / "_mpc" / "models" / artifact, model)


def statuses(sp: tuple[float, float], cv: tuple[float, float]) -> list[VariableStatus]:
    """Good statuses: MV setpoints (PV equal) and CV values."""
    rows = [VariableStatus(n, "t", "good", (), v, None, v)
            for n, v in zip(("u1", "u2"), sp, strict=True)]
    rows += [VariableStatus(n, "t", "good", (), v, None)
             for n, v in zip(("y1", "y2"), cv, strict=True)]
    return rows


TARGETS = {"u1": "t.sp1", "u2": "t.sp2"}


@pytest.fixture
def ctrl(tmp_path: Path) -> MpcController:
    """A controller on a stored, accepted model."""
    doc = controller_doc(store(tmp_path, make_model()))
    return MpcController(doc, load_bound_model(tmp_path, doc, CYCLE_S), TARGETS)


def test_loads_a_verified_model(tmp_path: Path) -> None:
    doc = controller_doc(store(tmp_path, make_model()))
    bound = load_bound_model(tmp_path, doc, CYCLE_S)
    assert (bound.mv_ids, bound.cv_ids, bound.dv_ids) == (("u1", "u2"), ("y1", "y2"), ())


def test_refuses_a_hash_mismatch(tmp_path: Path) -> None:
    store(tmp_path, make_model())
    with pytest.raises(ModelRefused, match="model_hash"):
        load_bound_model(tmp_path, controller_doc("0" * 64), CYCLE_S)


def test_refuses_a_model_that_failed_its_gate(tmp_path: Path) -> None:
    doc = controller_doc(store(tmp_path, make_model(accepted=False)))
    with pytest.raises(ModelRefused, match="model_gate"):
        load_bound_model(tmp_path, doc, CYCLE_S)


def test_refuses_a_missing_or_escaping_artifact(tmp_path: Path) -> None:
    sha = store(tmp_path, make_model())
    for name in ("nope", "../m1"):
        with pytest.raises(ModelRefused, match="model_missing"):
            load_bound_model(tmp_path, controller_doc(sha, name), CYCLE_S)


def test_refuses_another_cycle_time_and_foreign_channels(tmp_path: Path) -> None:
    doc = controller_doc(store(tmp_path, make_model(cycle_s=60.0)))
    with pytest.raises(ModelRefused, match="model_cycle"):
        load_bound_model(tmp_path, doc, CYCLE_S)
    other = dataclasses.replace(make_model(), input_names=("u1", "zz"))
    doc = controller_doc(store(tmp_path, other, "m2"), "m2")
    with pytest.raises(ModelRefused, match="model_names"):
        load_bound_model(tmp_path, doc, CYCLE_S)


def test_first_cycle_is_bumpless_with_zero_move(ctrl: MpcController) -> None:
    result = ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    assert [(m.variable_id, m.value, m.reason) for m in result.moves] == [
        ("u1", 40.0, "bumpless_initialisation"), ("u2", 60.0, "bumpless_initialisation")]
    assert result.diagnostics is not None and result.diagnostics["status"] == "bumpless_start"


def test_later_cycle_moves_toward_the_target_with_reason_codes(ctrl: MpcController) -> None:
    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    result = ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    data = result.diagnostics
    assert data is not None and data["status"] == "solved"
    assert {m["id"] for m in data["mvs"]} == {"u1", "u2"}
    assert all(m["code"] for m in data["mvs"])
    assert result.moves and all(m.reason.startswith("move") for m in result.moves)
    start = (40.0, 60.0)
    assert all(abs(m.value - s) <= 5.0 + 1e-6 for m, s in zip(result.moves, start, strict=True))
    cv = data["cvs"][0]
    assert cv["id"] == "y1" and cv["target"] == 50.0 and len(cv["predicted"]) == 20


def test_no_move_has_a_why_code(ctrl: MpcController) -> None:
    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    held = [m for m in ctrl.step(statuses((40.0, 60.0), (20.0, 30.0))).moves]
    assert held
    at_target = ctrl.step(statuses((0.0, 0.0), (50.0, 50.0)))
    assert at_target.diagnostics is not None
    assert at_target.diagnostics["why_no_move"] in {None, "limit", "at_target"}


def test_bad_input_holds_and_the_next_good_cycle_starts_bumpless(ctrl: MpcController) -> None:
    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    rows = statuses((40.0, 60.0), (20.0, 30.0))
    rows[2] = VariableStatus("y1", "t", "bad", ("quality",), None, None)
    held = ctrl.step(rows)
    assert held.moves == () and held.diagnostics is not None
    assert held.diagnostics["why_no_move"] == "input_bad"
    back = ctrl.step(statuses((41.0, 60.0), (20.0, 30.0)))
    assert [m.reason for m in back.moves] == ["bumpless_initialisation"] * 2
    assert back.moves[0].value == 41.0


def test_sheds_after_three_infeasible_cycles(ctrl: MpcController) -> None:
    bad = statuses((150.0, 60.0), (20.0, 30.0))  # u1 far above its hard limit: no feasible plan
    results = [ctrl.step(bad) for _ in range(5)]
    assert results[0].diagnostics is not None
    assert results[0].diagnostics["status"] == "bumpless_start"
    assert [r.shed for r in results] == [False, False, False, True, True]
    assert results[1].diagnostics is not None and results[1].diagnostics["status"] == "hold"
    assert all(r.moves == () for r in results[1:])


def test_initialise_after_shed_restarts_the_engine(ctrl: MpcController) -> None:
    bad = statuses((150.0, 60.0), (20.0, 30.0))
    for _ in range(4):
        ctrl.step(bad)
    ctrl.initialise([])
    good = ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    assert not good.shed and good.moves[0].reason == "bumpless_initialisation"


class Clock:
    """Advances 30 s per reading."""

    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, tzinfo=UTC).timestamp()

    def __call__(self) -> datetime:
        self.t += CYCLE_S
        return datetime.fromtimestamp(self.t, UTC)


class Plant:
    """Fake connector: fixed values by tag, fresh time stamps."""

    def __init__(self, clock: Clock, values: dict[str, float]) -> None:
        self.clock, self.values = clock, values

    def read_snapshot(self, tag_ids: Any) -> Any:
        from crosscut_connectors.base import LiveValue, Snapshot

        stamp = self.clock().isoformat()
        got = {t: LiveValue(self.values.get(t, 1.0), 0, stamp) for t in tag_ids}
        return Snapshot(stamp, got, True)


def host_for(tmp_path: Path, reasons: list[str], sink: list[Any]) -> ControllerHost:
    """A host around the MPC controller; ``reasons`` is what the gateway says about the MVs."""
    doc = controller_doc(store(tmp_path, make_model()))
    controller = MpcController(doc, load_bound_model(tmp_path, doc, CYCLE_S), TARGETS)
    tags = {"u1": ["t.pv1", "t.sp1"], "u2": ["t.pv2", "t.sp2"], "y1": ["t.y1"], "y2": ["t.y2"]}
    plant = Plant(Clock(), {"t.pv1": 40, "t.sp1": 40, "t.pv2": 60, "t.sp2": 60, "t.y1": 20,
                            "t.y2": 30})
    availability = lambda targets: {  # noqa: E731
        t: {"available": not reasons, "reasons": list(reasons)} for t in targets}
    ports = HostPorts(plant, availability, sink.append, plant.clock)
    return ControllerHost(controller, HostConfig(doc, tags, TARGETS, tmp_path), ports)


def test_advisory_never_proposes_and_keeps_diagnostics(tmp_path: Path) -> None:
    sent: list[Any] = []
    host = host_for(tmp_path, ["mode_no_write"], sent)
    host.request("switch_on")
    states = [host.run_cycle().state]
    states += [host.run_cycle().state for _ in range(3)]
    assert states == ["advisory"] * 4 and sent == []
    record = host.record
    assert record.last_advice and record.diagnostics is not None
    assert record.diagnostics["kind"] == "mpc"


def test_on_proposes_through_the_host_only(tmp_path: Path) -> None:
    sent: list[Any] = []
    host = host_for(tmp_path, [], sent)
    host.request("switch_on")
    for _ in range(4):
        host.run_cycle()
    assert host.record.state == "on" and sent
    assert {m.target_tag for m in sent} <= set(TARGETS.values())
    assert all(m.reason for m in sent)


def test_host_sheds_when_the_engine_does(tmp_path: Path) -> None:
    sent: list[Any] = []
    host = host_for(tmp_path, [], sent)
    host.request("switch_on")
    host.run_cycle()
    # u1 setpoint far above its hard limit on every later cycle
    plant = host._ports.connector  # noqa: SLF001
    plant.values.update({"t.pv1": 150, "t.sp1": 150})
    seen = []
    for _ in range(5):
        record = host.run_cycle()
        seen.append((record.state, record.reason))
    assert ("shed", "controller_shed") in seen
    assert host.record.diagnostics is None or host.record.diagnostics["kind"] == "mpc"
    assert all(m.reason == "bumpless_initialisation" for m in sent)


def site(tmp_path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    """A site document around the mpc controller."""
    return {
        "schema_version": 1, "site": {"name": "t"},
        "sources": [{"id": "s1", "type": "opcua", "endpoint": "x"}],
        "tags": [{"id": t, "source": "s1"} for t in
                 ("t.y1", "t.y2", "t.pv1", "t.pv2", "t.sp1", "t.sp2")],
        "loops": [{"id": "L1", "pv": "t.pv1", "sp": "t.sp1", "out": "t.pv1"},
                  {"id": "L2", "pv": "t.pv2", "sp": "t.sp2", "out": "t.pv2"}],
        "controllers": [doc],
    }


def test_job_refuses_to_start_on_a_wrong_hash(tmp_path: Path) -> None:
    store(tmp_path, make_model())
    doc = controller_doc("1" * 64)
    job = {"controller": "c1", "source": "s1"}
    with pytest.raises(ValueError, match="model_hash"):
        build_controller_job(job, site(tmp_path, copy.deepcopy(doc)), tmp_path, (None, None))


def test_job_builds_with_a_verified_model(tmp_path: Path) -> None:
    doc = controller_doc(store(tmp_path, make_model()))
    job = {"controller": "c1", "source": "s1"}
    deps = (lambda source: Plant(Clock(), {}),
            lambda *args: (lambda targets: {}, lambda move: None))
    built = build_controller_job(job, site(tmp_path, doc), tmp_path, deps)
    assert built.run()["controller"]["state"] == "off"


def test_a_proposal_never_leaves_step_and_range_limits() -> None:
    var = {"id": "u", "role": "MV", "limits": {"operator": {"lo": 0, "hi": 100}, "move_max": 5.0}}
    assert clamp_move(var, 40.0, 45.0000028, CYCLE_S) == pytest.approx(45.0)
    assert clamp_move(var, 40.0, 90.0, CYCLE_S) == pytest.approx(45.0)
    assert clamp_move(var, 98.0, 103.0, CYCLE_S) == pytest.approx(100.0)
    assert clamp_move(var, 120.0, 100.0, CYCLE_S) == pytest.approx(115.0)  # outside: approach


# ---- independent review findings (safety) ----


def test_only_good_inputs_may_drive_a_move(ctrl: MpcController) -> None:
    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    for level in ("uncertain", "bad"):
        rows = statuses((40.0, 60.0), (20.0, 30.0))
        rows[2] = VariableStatus("y1", "t", level, ("stale",), 20.0, None)
        held = ctrl.step(rows)
        assert held.moves == () and held.diagnostics is not None
        assert held.diagnostics["why_no_move"] == "input_bad"


def test_recovery_after_an_infeasible_hold_is_bumpless(ctrl: MpcController) -> None:
    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    held = ctrl.step(statuses((150.0, 60.0), (20.0, 30.0)))  # outside the hard limit: hold
    assert held.diagnostics is not None and held.diagnostics["status"] == "hold"
    back = ctrl.step(statuses((41.0, 60.0), (20.0, 30.0)))
    assert [(m.value, m.reason) for m in back.moves] == [
        (41.0, "bumpless_initialisation"), (60.0, "bumpless_initialisation")]


def test_reenable_after_shed_is_bumpless_with_zero_move(ctrl: MpcController) -> None:
    for _ in range(4):
        ctrl.step(statuses((150.0, 60.0), (20.0, 30.0)))
    ctrl.initialise([])
    again = ctrl.step(statuses((42.0, 61.0), (20.0, 30.0)))
    assert [(m.value, m.reason) for m in again.moves] == [
        (42.0, "bumpless_initialisation"), (61.0, "bumpless_initialisation")]


@pytest.mark.parametrize("sha", ["", "xyz", "a" * 63, "g" * 64, None])
def test_refuses_a_missing_or_malformed_hash(tmp_path: Path, sha: Any) -> None:
    store(tmp_path, make_model())
    doc = controller_doc("0" * 64)
    if sha is None:
        del doc["mpc"]["model"]["sha256"]
    else:
        doc["mpc"]["model"]["sha256"] = sha
    with pytest.raises(ModelRefused, match="model_hash"):
        load_bound_model(tmp_path, doc, CYCLE_S)


def test_hash_compare_ignores_case_and_an_empty_artifact_id_is_refused(tmp_path: Path) -> None:
    sha = store(tmp_path, make_model())
    assert load_bound_model(tmp_path, controller_doc(sha.upper()), CYCLE_S).mv_ids
    for name in ("", "  ", "."):
        with pytest.raises(ModelRefused, match="model_missing"):
            load_bound_model(tmp_path, controller_doc(sha, name), CYCLE_S)


def test_a_step_exception_sheds_without_any_proposal(tmp_path: Path) -> None:
    sent: list[Any] = []
    host = host_for(tmp_path, [], sent)

    def boom(_: Any) -> Any:
        raise RuntimeError("solver crashed")

    host.request("switch_on")
    host.run_cycle()
    host._controller.step = boom  # type: ignore[method-assign]  # noqa: SLF001
    record = host.run_cycle()
    assert (record.state, record.reason) == ("shed", "controller_error")
    assert sent == [] and record.diagnostics is None
    assert record.consecutive_overruns == 0 and record.liveness_utc is not None


def test_a_nonfinite_engine_move_holds_that_mv(
    ctrl: MpcController, monkeypatch: pytest.MonkeyPatch
) -> None:
    import crosscut_runtime.controllers.mpc as module  # noqa: PLC0415

    real = module.cycle

    def poisoned(*args: Any) -> Any:
        result, state = real(*args)
        moves = (float("nan"), *result.moves[1:])
        return dataclasses.replace(result, moves=moves), state

    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    monkeypatch.setattr(module, "cycle", poisoned)
    out = ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    assert "u1" not in {m.variable_id for m in out.moves}
    assert out.diagnostics is not None
    codes = {m["id"]: m["code"] for m in out.diagnostics["mvs"]}
    assert codes["u1"] == "bad_move"
    assert all(np.isfinite(m["proposed"]) for m in out.diagnostics["mvs"])


def test_clamp_uses_the_last_proposal_and_always_the_range() -> None:
    var = {"id": "u", "role": "MV", "limits": {"operator": {"lo": 0, "hi": 100}, "move_max": 5.0}}
    assert clamp_move(var, 40.0, 49.0, CYCLE_S, last=44.0) == pytest.approx(45.0)
    assert clamp_move(var, 40.0, 30.0, CYCLE_S, last=36.0) == pytest.approx(35.0)
    assert clamp_move(var, 40.0, 49.0, CYCLE_S, last=60.0) == pytest.approx(45.0)  # no overlap
    assert clamp_move(var, 40.0, 38.0, CYCLE_S, last=36.0) == pytest.approx(38.0)
    assert clamp_move(var, 99.0, 500.0, CYCLE_S, last=100.0) == pytest.approx(100.0)
    assert clamp_move(var, 102.0, 500.0, CYCLE_S) == pytest.approx(100.0)


def test_unapplied_proposals_do_not_accumulate(ctrl: MpcController) -> None:
    rows = statuses((40.0, 60.0), (20.0, 30.0))
    ctrl.step(rows)
    for _ in range(6):  # advisory: the plant never applies the proposal
        out = ctrl.step(rows)
        start = {"u1": 40.0, "u2": 60.0}
        assert all(abs(m.value - start[m.variable_id]) <= 5.0 + 1e-9 for m in out.moves)


ECONOMICS = {"cv_value": {"y2": 2.0}, "mv_cost": {"u1": 0.1}, "soft_limits": {"y2": {"hi": 80.0}}}


def test_economics_are_reported_with_where_and_why(ctrl: MpcController) -> None:
    ctrl.apply_economics(ECONOMICS)
    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    data = ctrl.step(statuses((40.0, 60.0), (20.0, 30.0))).diagnostics
    assert data is not None and data["status"] in {"solved", "relaxed"}
    economics = data["economics"]
    assert economics["status"] == "optimal" and economics["benefit_rate"] >= 0
    assert all({"kind", "variable", "side", "limit", "shadow_price"} <= b.keys()
               for b in economics["binding"])
    assert {b["variable"] for b in economics["binding"]} <= {"u1", "u2", "y1", "y2"}


def test_no_objective_means_no_economics_report(ctrl: MpcController) -> None:
    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    data = ctrl.step(statuses((40.0, 60.0), (20.0, 30.0))).diagnostics
    assert data is not None and "economics" not in data


def test_economics_cannot_move_an_mv_beyond_its_step_window(ctrl: MpcController) -> None:
    ctrl.apply_economics(ECONOMICS)
    ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    result = ctrl.step(statuses((40.0, 60.0), (20.0, 30.0)))
    assert all(abs(m.value - s) <= 5.0 + 1e-6 for m, s in zip(result.moves, (40.0, 60.0), strict=True))
