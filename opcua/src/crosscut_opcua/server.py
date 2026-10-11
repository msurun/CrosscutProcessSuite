"""OPC UA server that exposes a simulated plant as a set of Double variables.

The server advances the plant in real time scaled by ``speed``, publishes every tag on each
tick and forwards client writes to the plant. A heartbeat counter written by the client acts
as a simulated DCS watchdog: when it stops changing, cascade (CAS) loops fall back to AUTO.

Run from the command line with ``python -m crosscut_opcua.server --help``.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Callable, Sequence

from asyncua import Server, ua
from asyncua.common.node import Node
from asyncua.server.address_space import NodeData
from asyncua.ua.attribute_ids import AttributeIds
from crosscut_sim.core import AUTO, CAS, Plant, Scenario
from crosscut_sim.run import PLANTS
from crosscut_sim.scenarios import build_scenario

NAMESPACE_URI = "urn:crosscut:sim"
PLANT_OBJECT_NAME = "Plant"
HEARTBEAT_TAG = "sim.heartbeat"
HEARTBEAT_OK_TAG = "sim.heartbeat_ok"
TIME_TAG = "sim.time_s"
EXTRA_TAGS = (HEARTBEAT_TAG, HEARTBEAT_OK_TAG, TIME_TAG)


def _node_id(idx: int, identifier: str) -> ua.NodeId:
    """Return the string NodeId ``ns=<idx>;s=<identifier>`` used for every plant node."""
    return ua.NodeId.from_string(f"ns={idx};s={identifier}")


class PlantServer:
    """Serve a plant over OPC UA (anonymous, no security) while it runs in the background.

    Client writes are intercepted with an asyncua value setter, so they never travel through
    the subscription machinery. The server's own publishing is flagged with ``_publishing`` and
    is stored unchanged, which avoids any feedback loop.
    """

    def __init__(
        self,
        plant: Plant,
        scenario: Scenario,
        *,
        seed: int,
        host: str = "127.0.0.1",
        port: int = 4840,
        speed: float = 1.0,
        tick_s: float = 0.1,
        heartbeat_timeout_s: float = 10.0,
    ) -> None:
        if speed <= 0 or tick_s <= 0 or heartbeat_timeout_s <= 0:
            raise ValueError("speed, tick_s and heartbeat_timeout_s must be positive")
        self.plant = plant
        self._scenario = scenario
        self._seed = seed
        self._host = host
        self._port = port
        self._speed = speed
        self._tick_s = tick_s
        self._heartbeat_timeout_s = heartbeat_timeout_s

        self._server: Server | None = None
        self._nodes: dict[str, Node] = {}
        self._task: asyncio.Task[None] | None = None
        self._publishing = False
        self._heartbeat_value = 0
        self._last_heartbeat_change = time.monotonic()
        self._heartbeat_ok = True

    @property
    def endpoint(self) -> str:
        return f"opc.tcp://{self._host}:{self._port}"

    async def __aenter__(self) -> PlantServer:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def start(self) -> None:
        """Create the address space, start the server and the background tick loop."""
        self.plant.reset(self._seed, self._scenario)
        self._heartbeat_value = 0
        self._heartbeat_ok = True

        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        idx = await server.register_namespace(NAMESPACE_URI)

        plant_obj = await server.nodes.objects.add_object(
            _node_id(idx, PLANT_OBJECT_NAME), PLANT_OBJECT_NAME
        )
        writable: list[tuple[str, Node]] = []
        for spec in self.plant.tags:
            value, _ = self.plant.read(spec.id)
            node = await plant_obj.add_variable(
                _node_id(idx, spec.id),
                spec.id,
                float(value),
                varianttype=ua.VariantType.Double,
            )
            self._nodes[spec.id] = node
            if spec.writable:
                await node.set_writable()
                writable.append((spec.id, node))

        self._nodes[HEARTBEAT_TAG] = await plant_obj.add_variable(
            _node_id(idx, HEARTBEAT_TAG),
            HEARTBEAT_TAG,
            0,
            varianttype=ua.VariantType.Int64,
        )
        await self._nodes[HEARTBEAT_TAG].set_writable()
        writable.append((HEARTBEAT_TAG, self._nodes[HEARTBEAT_TAG]))

        self._nodes[HEARTBEAT_OK_TAG] = await plant_obj.add_variable(
            _node_id(idx, HEARTBEAT_OK_TAG),
            HEARTBEAT_OK_TAG,
            True,
            varianttype=ua.VariantType.Boolean,
        )
        self._nodes[TIME_TAG] = await plant_obj.add_variable(
            _node_id(idx, TIME_TAG),
            TIME_TAG,
            float(self.plant.time_s),
            varianttype=ua.VariantType.Double,
        )

        await server.start()
        self._server = server
        # The watchdog clock starts once the server is up: the server start is the first change.
        self._last_heartbeat_change = time.monotonic()
        for tag_id, node in writable:
            server.set_attribute_value_setter(node.nodeid, self._make_setter(tag_id))

        await self._publish()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the tick loop and the server; releases the port."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._server is not None:
            await self._server.stop()
            self._server = None
        self._nodes = {}

    # ----- simulation loop -------------------------------------------------------------------

    async def _run(self) -> None:
        steps = max(1, round(self._speed * self._tick_s / self._scenario.dt_s))
        while True:
            started = time.monotonic()
            for _ in range(steps):
                self.plant.step()
            self._update_watchdog(time.monotonic())
            await self._publish()
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.0, self._tick_s - elapsed))

    async def _publish(self) -> None:
        """Copy every plant tag, the plant time and the heartbeat status to the address space."""
        for spec in self.plant.tags:
            value, _ = self.plant.read(spec.id)
            await self._write(spec.id, float(value))
        await self._write(TIME_TAG, float(self.plant.time_s))
        await self._write(HEARTBEAT_OK_TAG, self._heartbeat_ok)

    async def _write(self, tag_id: str, value: float | bool) -> None:
        """Write a value on behalf of the server (not a client write)."""
        if isinstance(value, bool):
            variant = ua.Variant(value, ua.VariantType.Boolean)
        else:
            variant_type = (
                ua.VariantType.Int64 if tag_id == HEARTBEAT_TAG else ua.VariantType.Double
            )
            variant = ua.Variant(value, variant_type)
        self._publishing = True
        try:
            await self._nodes[tag_id].write_value(ua.DataValue(variant))
        finally:
            self._publishing = False

    # ----- heartbeat watchdog ----------------------------------------------------------------

    def _heartbeat_alive(self, now: float) -> bool:
        return now - self._last_heartbeat_change <= self._heartbeat_timeout_s

    def _update_watchdog(self, now: float) -> None:
        alive = self._heartbeat_alive(now)
        if self._heartbeat_ok and not alive:
            # The DCS takes the loops back: CAS loops fall to AUTO and keep their local SP.
            for spec in self.plant.tags:
                if spec.role == "MODE" and self.plant.read(spec.id)[0] == CAS:
                    try:
                        self.plant.write(spec.id, float(AUTO))
                    except (PermissionError, ValueError, KeyError):
                        pass
        self._heartbeat_ok = alive

    # ----- client writes ---------------------------------------------------------------------

    def _make_setter(self, tag_id: str) -> Callable[[NodeData, AttributeIds, ua.DataValue], None]:
        def setter(node: NodeData, attr: AttributeIds, value: ua.DataValue) -> None:
            if self._publishing:
                node.attributes[attr].value = value
                return
            if tag_id == HEARTBEAT_TAG:
                self._on_heartbeat(int(value.Value.Value))  # type: ignore[union-attr]
                node.attributes[attr].value = value
                return
            self._on_client_write(tag_id, float(value.Value.Value))  # type: ignore[union-attr]
            # The node always reflects what the plant holds after the write attempt.
            stored = float(self.plant.read(tag_id)[0])
            node.attributes[attr].value = ua.DataValue(ua.Variant(stored, ua.VariantType.Double))

        return setter

    def _on_heartbeat(self, value: int) -> None:
        if value != self._heartbeat_value:
            self._heartbeat_value = value
            self._last_heartbeat_change = time.monotonic()

    def _on_client_write(self, tag_id: str, value: float) -> None:
        """Forward a client write to the plant; a refused write leaves the plant unchanged."""
        spec = self.plant.tags[tag_id]
        if spec.role == "MODE" and value == CAS and not self._heartbeat_alive(time.monotonic()):
            return  # the DCS holds the loop while the heartbeat is lost
        try:
            self.plant.write(tag_id, value)
        except (PermissionError, ValueError, KeyError):
            pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m crosscut_opcua.server",
        description="Serve a simulated plant over OPC UA until interrupted (Ctrl+C).",
    )
    parser.add_argument("--plant", required=True, choices=sorted(PLANTS), help="plant identifier")
    parser.add_argument("--scenario", default="nominal", help="scenario name (default: nominal)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    parser.add_argument("--host", default="127.0.0.1", help="listen address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=4840, help="listen port (default: 4840)")
    parser.add_argument(
        "--speed", type=float, default=1.0, help="plant time per wall-clock second (default: 1)"
    )
    parser.add_argument(
        "--tick", type=float, default=0.1, help="publish period in seconds (default: 0.1)"
    )
    parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=10.0,
        help="seconds without heartbeat changes before CAS loops fall back (default: 10)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the OPC UA server until interrupted; returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        scenario = build_scenario(args.plant, args.scenario, duration_s=24 * 3600.0)
    except ValueError as e:
        parser.error(str(e))

    server = PlantServer(
        PLANTS[args.plant](),
        scenario,
        seed=args.seed,
        host=args.host,
        port=args.port,
        speed=args.speed,
        tick_s=args.tick,
        heartbeat_timeout_s=args.heartbeat_timeout,
    )

    async def serve_forever() -> None:
        async with server:
            print(f"serving {args.plant} at {server.endpoint} (Ctrl+C to stop)", flush=True)
            await asyncio.Event().wait()

    try:
        asyncio.run(serve_forever())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
