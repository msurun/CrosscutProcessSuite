# connectors/tests/test_opcua_import_multitag.py
"""Layout test: a multi-tag OPC UA import must write a (time x tag) matrix (issue #90)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from crosscut_connectors import opcua_import
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.opcua_import import PollPlan, import_opcua
from crosscut_sim.core import BAD, GOOD
from crosscut_sim.dataset import read_dataset, to_wide

# sample-major: one row per sample, one column per tag (value, quality)
SAMPLES = [
    [(1.0, GOOD), (10.0, GOOD), (100.0, GOOD)],
    [(2.0, GOOD), (20.0, BAD), (200.0, GOOD)],
    [(3.0, GOOD), (30.0, GOOD), (300.0, BAD)],
    [(4.0, GOOD), (40.0, GOOD), (400.0, GOOD)],
]


async def _noop(*_args: object, **_kwargs: object) -> None:
    """Stand-in for connect, disconnect and sleep."""


async def _resolve(_client: object, node_id: str) -> str:
    """Return the node id unchanged."""
    return node_id


def test_values_and_qualities_are_time_by_tag(tmp_path: Path, monkeypatch) -> None:
    """Dataset rows are samples and columns are tags, same as the CSV importer writes."""
    rounds = iter(SAMPLES)

    async def fake_sample(*_args: object, **_kwargs: object) -> list[tuple[float, int]]:
        return next(rounds)

    monkeypatch.setattr(opcua_import, "Client", lambda **_kw: object())
    monkeypatch.setattr(opcua_import, "_connect", _noop)
    monkeypatch.setattr(opcua_import, "_disconnect", _noop)
    monkeypatch.setattr(opcua_import, "_sleep_before_next_sample", _noop)
    monkeypatch.setattr(opcua_import, "resolve_node_id", _resolve)
    monkeypatch.setattr(opcua_import, "_sample_all", fake_sample)
    nodes = {"tag_a": "ns=2;s=A", "tag_b": "ns=2;s=B", "tag_c": "ns=2;s=C"}
    out_dir = tmp_path / "ds"

    import_opcua(
        "opc.tcp://x", nodes, ImportTarget(out_dir, "mt"), PollPlan(period_s=0.1, n_samples=4)
    )

    table = read_dataset(out_dir)
    _, wide = to_wide(table)
    for column, name in enumerate(nodes):
        np.testing.assert_array_equal(wide[name], [row[column][0] for row in SAMPLES])
    expected_q = [row[c][1] for row in SAMPLES for c in range(3)]
    assert table["quality"].to_pylist() == expected_q
