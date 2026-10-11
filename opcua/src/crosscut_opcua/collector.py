"""Collect samples from a running OPC UA plant server into a Parquet dataset.

Command line: ``python -m crosscut_opcua.collector --help``.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from asyncua import Client, ua
from asyncua.common.node import Node
from asyncua.ua.attribute_ids import AttributeIds
from crosscut_sim.dataset import DEFAULT_START_UTC, write_dataset
from crosscut_sim.run import PLANTS, parse_duration
from crosscut_sim.scenarios import build_scenario

from crosscut_opcua.server import EXTRA_TAGS, NAMESPACE_URI, PLANT_OBJECT_NAME, TIME_TAG

GOOD_QUALITY = 0
BAD_QUALITY = 2


def _utc_to_ns(text: str) -> int:
    dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return int(dt.timestamp()) * 10**9


async def _discover_plant_nodes(client: Client, idx: int) -> tuple[Node, list[Node], list[str]]:
    """Return the time node, the plant tag nodes (server order) and their tag ids."""
    plant_obj = await _find_plant_object(client)
    time_node, tag_nodes, tag_ids = await _collect_plant_tags(plant_obj, idx)
    return time_node, tag_nodes, tag_ids


async def _find_plant_object(client: Client) -> Node:
    """Return the server's plant object node. Raise RuntimeError when it is absent."""
    for child in await client.nodes.objects.get_children():
        if (await child.read_browse_name()).Name == PLANT_OBJECT_NAME:
            return child
    raise RuntimeError(f"no '{PLANT_OBJECT_NAME}' object in the server address space")


async def _collect_plant_tags(plant_obj: Node, idx: int) -> tuple[Node, list[Node], list[str]]:
    """Split the plant variables into the time tag and the remaining tag nodes with their ids."""
    time_node: Node | None = None
    tag_nodes: list[Node] = []
    tag_ids: list[str] = []
    for node in await plant_obj.get_children(nodeclassmask=ua.NodeClass.Variable):
        tag_id = str(node.nodeid.Identifier)
        if tag_id == TIME_TAG:
            time_node = node
        elif tag_id not in EXTRA_TAGS:
            tag_nodes.append(node)
            tag_ids.append(tag_id)
    if time_node is None:
        raise RuntimeError(f"time tag {TIME_TAG!r} not found in namespace {idx}")
    return time_node, tag_nodes, tag_ids


async def collect(
    endpoint: str,
    out_dir: str | Path,
    *,
    sim_duration_s: float,
    sample_period_s: float,
    dataset_id: str,
    plant_name: str,
    scenario_name: str | None = None,
    seed: int | None = None,
    start_utc: str = DEFAULT_START_UTC,
    timeout_s: float = 3600.0,
    poll_s: float = 0.01,
    git_commit: str | None = None,
) -> dict[str, Any]:
    """Record plant samples from an OPC UA server into ``out_dir`` and return the dataset document.

    Samples are taken whenever the plant time has advanced by ``sample_period_s`` since the last
    sample; the first poll is always recorded. Sample timestamps are ``start_utc`` plus the plant
    time elapsed since the first sample.

    Raises
    ------
    TimeoutError
        If ``sim_duration_s`` of plant time has not elapsed within ``timeout_s`` wall seconds.
    """
    if sim_duration_s <= 0 or sample_period_s <= 0 or poll_s < 0:
        raise ValueError("sim_duration_s and sample_period_s must be positive")

    start_ns = _utc_to_ns(start_utc)
    ts_ns: list[int] = []
    rows: list[list[float]] = []
    quality_rows: list[list[int]] = []
    first_plant_time: float | None = None
    last_recorded: float | None = None
    deadline = time.monotonic() + timeout_s

    async with Client(endpoint) as client:
        idx = await client.get_namespace_index(NAMESPACE_URI)
        time_node, tag_nodes, tag_ids = await _discover_plant_nodes(client, idx)
        all_nodes = [time_node, *tag_nodes]

        while True:
            data_values = await client.read_attributes(all_nodes, AttributeIds.Value)
            plant_time = float(data_values[0].Value.Value)  # type: ignore[union-attr]
            if first_plant_time is None:
                first_plant_time = plant_time
            if last_recorded is None or plant_time - last_recorded >= sample_period_s - 1e-9:
                elapsed = plant_time - first_plant_time
                ts_ns.append(start_ns + round(elapsed * 1e9))
                rows.append([float(dv.Value.Value) for dv in data_values[1:]])  # type: ignore[union-attr]
                quality_rows.append(
                    [
                        GOOD_QUALITY
                        if dv.StatusCode is None or dv.StatusCode.is_good()
                        else BAD_QUALITY
                        for dv in data_values[1:]
                    ]
                )
                last_recorded = plant_time
            if plant_time - first_plant_time >= sim_duration_s:
                break
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"plant time {plant_time - first_plant_time:.1f}s of {sim_duration_s:.1f}s "
                    f"after {timeout_s:.0f} wall seconds"
                )
            await asyncio.sleep(poll_s)

    source: dict[str, Any] = {"kind": "opcua", "plant": plant_name}
    if scenario_name is not None:
        source["scenario"] = scenario_name
    if seed is not None:
        source["seed"] = seed

    tags_document: dict[str, Any] = {
        "schema_version": "0.1.0",
        "tags": [
            {
                "id": tag_id,
                "name": tag_id,
                "unit": "",
                "type": "float",
                "role": "other",
                "source": {"driver": "opcua", "address": f"ns={idx};s={tag_id}"},
            }
            for tag_id in tag_ids
        ],
    }

    return write_dataset(
        out_dir,
        np.asarray(ts_ns, dtype=np.int64),
        tag_ids,
        np.asarray(rows, dtype=np.float64),
        np.asarray(quality_rows, dtype=np.uint8),
        dataset_id=dataset_id,
        source=source,
        start_utc=start_utc,
        tags_document=tags_document,
        git_commit=git_commit,
    )


def _git_commit() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            or None
        )
    except (subprocess.SubprocessError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m crosscut_opcua.collector",
        description="Record a running OPC UA plant server into a Parquet dataset.",
    )
    parser.add_argument("--endpoint", required=True, help="e.g. opc.tcp://127.0.0.1:4840")
    parser.add_argument("--duration", required=True, help="plant time to record, e.g. 1h")
    parser.add_argument("--sample-period", default="1s", help="plant time between samples (1s)")
    parser.add_argument("--out", required=True, type=Path, help="output root directory")
    parser.add_argument("--dataset-id", default=None, help="dataset id (default: derived)")
    parser.add_argument("--plant", required=True, choices=sorted(PLANTS), help="plant identifier")
    parser.add_argument("--scenario", default=None, help="scenario name used for the metadata")
    parser.add_argument("--seed", type=int, default=None, help="seed used by the server")
    parser.add_argument(
        "--start-utc", default=DEFAULT_START_UTC, help="timestamp of the first sample"
    )
    parser.add_argument(
        "--timeout", type=float, default=3600.0, help="wall-clock limit in seconds (3600)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Collect a dataset from a running server; returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        duration_s = parse_duration(args.duration)
        sample_period_s = parse_duration(args.sample_period)
    except ValueError as e:
        parser.error(str(e))

    if args.scenario is not None:
        try:
            build_scenario(args.plant, args.scenario, duration_s=duration_s)
        except ValueError as e:
            parser.error(str(e))

    dataset_id = args.dataset_id or f"{args.plant}_{args.scenario or 'opcua'}_collected"
    dataset_dir = args.out / dataset_id
    try:
        doc = asyncio.run(
            collect(
                args.endpoint,
                dataset_dir,
                sim_duration_s=duration_s,
                sample_period_s=sample_period_s,
                dataset_id=dataset_id,
                plant_name=args.plant,
                scenario_name=args.scenario,
                seed=args.seed,
                start_utc=args.start_utc,
                timeout_s=args.timeout,
                git_commit=_git_commit(),
            )
        )
    except FileExistsError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"{dataset_dir} ({doc['row_count']} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
