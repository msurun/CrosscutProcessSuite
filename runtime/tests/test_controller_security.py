"""Security regressions for controller ports, bindings and host caching.

Use synthetic site documents and mocked gateways to keep the checks offline.
"""

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from crosscut_connectors.base import LiveValue, Snapshot
from crosscut_runtime.controllers.fuzzy import ControllerBindingError
from crosscut_runtime.controllers.gateway_adapter import make_gateway_ports
from crosscut_runtime.controllers.protocol import Move
from crosscut_runtime.controllers.wiring import AddressedSnapshot, build_controller_job
from crosscut_runtime.service import RuntimeService

from .test_controller_job import JOB, SITE, _service, _state


@pytest.fixture
def gateway_client(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Replace optional API modules so runtime tests do not require the HTTP framework."""
    client = Mock()
    monkeypatch.setitem(
        sys.modules, "crosscut_api.gateway_client",
        SimpleNamespace(FileGatewayClient=Mock(return_value=client)),
    )
    monkeypatch.setitem(
        sys.modules, "crosscut_api.auth.actor", SimpleNamespace(ActorContext=SimpleNamespace),
    )
    return client


def test_gateway_refuses_another_controllers_target(
    tmp_path: Path, gateway_client: Mock
) -> None:
    """The controller service identity cannot send moves to an unrelated loop."""
    _, propose = make_gateway_ports(tmp_path, "c1", lambda: 7, frozenset({"t.sp"}))
    with pytest.raises(ControllerBindingError, match="target"):
        propose(Move("mv1", "other.sp", 52.0, "test"))
    gateway_client.propose.assert_not_called()


def test_gateway_sends_an_allowed_target(tmp_path: Path, gateway_client: Mock) -> None:
    """An authorised move keeps its controller service principal."""
    _, propose = make_gateway_ports(tmp_path, "c1", lambda: 7, frozenset({"t.sp"}))
    propose(Move("mv1", "t.sp", 52.0, "test"))
    assert gateway_client.propose.call_args.args[0]["target_tag"] == "t.sp"
    assert gateway_client.propose.call_args.kwargs["actor"].actor == "svc:controller:c1"


@pytest.mark.parametrize("limits", [{}, {"move_max": None}])
def test_mv_requires_a_move_limit(tmp_path: Path, limits: dict) -> None:
    """Missing step limits fail binding before any gateway is built."""
    site = deepcopy(SITE)
    site["controllers"][0]["variables"][1]["limits"] = limits
    gateway = Mock()
    with pytest.raises(ControllerBindingError, match="^binding:.*move_max"):
        build_controller_job(JOB, site, tmp_path, (Mock(), gateway))
    gateway.assert_not_called()


@pytest.mark.parametrize("range_name", ["operator", "eng"])
@pytest.mark.parametrize("bounds", [{"lo": 2, "hi": 2}, {"lo": 3, "hi": 2}])
def test_unordered_ranges_fail_binding(tmp_path: Path, range_name: str, bounds: dict) -> None:
    """Both equal and inverted bounds are invalid, including unused engineering bounds."""
    site = deepcopy(SITE)
    site["controllers"][0]["variables"][1]["limits"][range_name] = bounds
    with pytest.raises(ControllerBindingError, match="^binding:.*requires lo < hi"):
        build_controller_job(JOB, site, tmp_path, (Mock(), Mock()))


def test_missing_address_has_bad_quality_and_reason() -> None:
    """Partial snapshots retain both present values and explicit missing values."""
    good = LiveValue(42.0, 0, "now")
    connector = Mock()
    connector.read_snapshot.return_value = Snapshot("now", {"present": good}, True)
    addressed = AddressedSnapshot(connector, {"pv": "present", "sp": "absent"})
    snapshot = addressed.read_snapshot(["pv", "sp"])
    assert snapshot.values == {"pv": good, "sp": LiveValue(None, 2, "now")}
    assert snapshot.reason == "missing" and snapshot.comm_ok
    connector.read_snapshot.assert_called_once_with(["present", "absent"])


@pytest.mark.parametrize("section", ["controllers", "loops"])
def test_site_binding_edits_rebuild_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, section: str
) -> None:
    """The cached host survives unchanged input and is replaced after an in-place edit."""
    service = RuntimeService(tmp_path)
    builder = Mock()
    monkeypatch.setattr("crosscut_runtime.service.build_controller_job", builder)
    site = deepcopy(SITE)
    service._controller_run(JOB, site)
    service._controller_run(JOB, site)
    assert builder.call_count == 1
    site[section][0]["description"] = "edited"
    service._controller_run(JOB, site)
    assert builder.call_count == 2


@pytest.mark.parametrize("variables", [None, [{}]])
def test_malformed_controller_is_logged_as_a_job_error(tmp_path: Path, variables: object) -> None:
    """Malformed site bindings cannot escape into the scheduling loop."""
    service = _service(tmp_path, [])
    site = deepcopy(SITE)
    site["controllers"][0]["variables"] = variables
    service._sync_controller(JOB, site)
    results = service._scheduler.tick(service._clock())
    service._update_state([JOB], results)
    assert _state(tmp_path)["status"] == "error"
    assert service._store.read_log()


def test_wiring_passes_only_its_mv_setpoints(tmp_path: Path) -> None:
    """Gateway authorisation receives setpoints rather than PVs or unrelated tags."""
    _service(tmp_path, [])
    gateway = Mock(return_value=(Mock(), Mock()))
    build_controller_job(JOB, SITE, tmp_path, (Mock(), gateway))
    assert gateway.call_args.args[3] == frozenset({"t.sp"})

