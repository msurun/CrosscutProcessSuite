"""OPC UA importer: nodes named by namespace URI, and a session that dies and comes back.

The index in ``ns=2`` is only valid for one server session; the URI form ``nsu=<uri>;s=Tag`` is
looked up after connecting. The reconnect test stops the server in the middle of the poll and
starts a new one on the same port, as happens when a plant server is restarted.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.opcua_import import PollPlan, import_opcua
from crosscut_opcua.server import NAMESPACE_URI
from test_opcua_import import TAG_Y1, free_port, make_server, read_column, run_against_server

N_SAMPLES = 40
PERIOD_S = 0.1
OUTAGE_AFTER_S = 1.0  # let some samples through before the server goes away
OUTAGE_S = 1.0  # the server stays down this long


async def _import_across_a_restart(
    port: int, nodes: dict[str, str], plan: PollPlan, dataset_dir: Path
) -> None:
    """Run an import while the server stops after OUTAGE_AFTER_S and returns after OUTAGE_S."""
    first = make_server(port)
    await first.start()
    job = asyncio.to_thread(
        import_opcua, first.endpoint, nodes, ImportTarget(dataset_dir, "r"), plan
    )
    task = asyncio.ensure_future(job)
    await asyncio.sleep(OUTAGE_AFTER_S)
    await first.stop()
    await asyncio.sleep(OUTAGE_S)
    second = make_server(port)
    await second.start()
    await asyncio.wait_for(task, timeout=60.0)
    await second.stop()


def test_a_node_named_by_namespace_uri_is_read(tmp_path: Path) -> None:
    """``nsu=<uri>;s=Tag`` gives the same good samples as ``ns=2;s=Tag``."""
    nodes = {"y1": f"nsu={NAMESPACE_URI};s={TAG_Y1}"}
    server = make_server(free_port())

    def call(endpoint: str):
        """Import the node from the running server at `endpoint` (4 samples, 50 ms apart)."""
        return import_opcua(
            endpoint, nodes, ImportTarget(tmp_path / "ds", "nsu"), PollPlan(0.05, 4)
        )

    report = run_against_server(server, call)
    _, values, _ = read_column(tmp_path / "ds", "y1")
    assert report.n_bad_values == 0
    assert np.all(np.isfinite(values))


def test_an_unknown_namespace_uri_is_a_clear_error(tmp_path: Path) -> None:
    """A URI the server does not publish raises ValueError naming the URI."""
    nodes = {"y1": f"nsu=urn:not-there;s={TAG_Y1}"}
    server = make_server(free_port())

    def call(endpoint: str):
        """Try to import the unknown-URI node from the server at `endpoint`."""
        return import_opcua(endpoint, nodes, ImportTarget(tmp_path / "ds", "x"), PollPlan(0.05, 2))

    with pytest.raises(ValueError, match="urn:not-there"):
        run_against_server(server, call)


def test_the_import_survives_a_server_restart(tmp_path: Path) -> None:
    """Samples during the outage are BAD, samples after the restart are good again."""
    nodes = {"y1": f"nsu={NAMESPACE_URI};s={TAG_Y1}"}
    plan = PollPlan(PERIOD_S, N_SAMPLES)

    asyncio.run(_import_across_a_restart(free_port(), nodes, plan, tmp_path / "ds"))
    _, values, quality = read_column(tmp_path / "ds", "y1")
    assert np.isnan(values).any()
    assert np.isfinite(values[:3]).all()
    assert np.isfinite(values[-3:]).all()
    assert quality[-1] == 0 or np.isfinite(values[-1])
