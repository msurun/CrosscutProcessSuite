"""OPC UA implementation of the ControlSystem adapter used by the write gateway.

This is the only gateway module allowed to import asyncua: every OPC UA socket,
session and variant detail stays behind this file. The rest of the gateway sees
plain floats, strings and exceptions (ADR 012: only the gateway writes, and it
does so through adapters like this one).

Without a ``take_remote`` entry in the plant map, a write only touches the setpoint
node, so a real control system stays in local setpoint source and the engine's next
tick sees "local" (operator takeover, hold_off) after every write. ``take_remote`` is
plant-map data that makes ``write()`` put the source into remote first.

Targets are of two kinds (ADR 014): setpoint targets (``setpoint_node``) used with
``read``/``write``/``release``/``setpoint_source``, and ``pid_param`` targets
(``param_node``) used with ``read_param``/``write_param``. ``loop_mode`` works for both.
Using a method of one kind on a tag of the other raises ``ValueError``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import math
import threading
import time
from collections.abc import Coroutine, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, Self, TypeVar

import jsonschema
from asyncua import Client, Node, ua
from asyncua.ua.status_codes import get_name_and_doc

PLANT_MAP_SCHEMA_NAME = "plant-map.schema.json"
MAX_PARENT_WALK = 10  # levels searched upwards for the schemas/ directory
DEFAULT_TIMEOUT_S = 2.0  # OPC UA call budget, in seconds
HEARTBEAT_COUNTER_MAX = 2**31 - 1  # OPC UA Int32 maximum; the counter wraps back to 1
FLOAT32_MAX = 3.4028234663852886e38  # largest finite value an OPC UA Float can hold
# Variant type used to write a pid_param target; always the CONFIGURED one, never inferred.
PARAM_VARIANT_TYPES: Mapping[str, ua.VariantType] = {
    "Float": ua.VariantType.Float,
    "Double": ua.VariantType.Double,
}
T = TypeVar("T")

# Status codes that mean "the session or the socket is gone", not "the server said no".
# A write failing with one of them is a transport failure, never a refused value.
TRANSPORT_STATUS_NAMES: frozenset[str] = frozenset(
    {
        "BadConnectionClosed",
        "BadSessionClosed",
        "BadSessionIdInvalid",
        "BadSecureChannelClosed",
        "BadCommunicationError",
        "BadServerNotConnected",
        "BadTimeout",
        "BadNoCommunication",
        "BadNotConnected",
    }
)

_SCHEMA_CACHE: dict[str, Any] | None = None


class PlantMapError(ValueError):
    """The plant map is not valid JSON or does not match plant-map.schema.json."""


def validate_plant_map(data: Mapping[str, Any]) -> None:
    """Validate a plant map against schemas/plant-map.schema.json.

    Raises:
        PlantMapError: if any schema rule is violated; the message lists every error.
    """
    schema = _load_plant_map_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(dict(data)), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise PlantMapError(details)


def load_plant_map(path: Path) -> dict[str, Any]:
    """Read a JSON plant map from disk and validate it.

    Raises:
        PlantMapError: if the file cannot be read or parsed, or fails validation.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PlantMapError(f"cannot read plant map {path}: {error}") from error
    if not isinstance(data, dict):
        raise PlantMapError(f"plant map {path} must contain a JSON object")
    validate_plant_map(data)
    return data


def _load_plant_map_schema() -> dict[str, Any]:
    """Return the plant-map schema, parsing the file only on the first call."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        schema_path = _find_schema_path(PLANT_MAP_SCHEMA_NAME)
        _SCHEMA_CACHE = json.loads(schema_path.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


def _find_schema_path(schema_name: str) -> Path:
    """Walk up from this file's directory to the first schemas/<schema_name>."""
    current = Path(__file__).resolve().parent
    for _ in range(MAX_PARENT_WALK):
        candidate = current / "schemas" / schema_name
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise PlantMapError(f"schema file schemas/{schema_name} not found")


class OpcUaPlant:
    """ControlSystem adapter: reads, writes and heartbeat over OPC UA.

    One background thread runs an asyncio loop; every public method is synchronous
    and blocks the calling thread until its single OPC UA call has finished or the
    timeout has elapsed. The session is opened on first use and reused.
    """

    def __init__(
        self,
        plant_map: Mapping[str, Any],
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        """Store and validate the plant map; start the loop thread without connecting."""
        validate_plant_map(plant_map)
        self._plant_map: dict[str, Any] = dict(plant_map)
        self._timeout_s = timeout_s
        self._client: Client | None = None
        self._closed = False
        self._heartbeat_counter = 0
        self._last_heartbeat_s: float | None = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="opcua-plant", daemon=True
        )
        self._thread.start()

    @classmethod
    def from_file(cls, path: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> Self:
        """Build an adapter from a plant map file on disk."""
        return cls(load_plant_map(path), timeout_s)

    def __enter__(self) -> Self:
        """Enter a ``with`` block, returning this adapter."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the adapter on leaving a ``with`` block."""
        self.close()

    def close(self) -> None:
        """Disconnect, stop the loop and join the thread; safe to call twice."""
        if self._closed:
            return
        self._closed = True
        self._disconnect_quietly()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()
        self._client = None

    def read(self, tag: str) -> float:
        """Current read-back value of ``tag``, in the engineering units of that tag.

        Raises:
            KeyError: if ``tag`` is not in the plant map.
            ConnectionError: on transport failure or a status code that is not good.
            TimeoutError: if the server does not answer within the timeout.
        """
        target = self._setpoint_target(tag)
        return self._call(self._read_async(target["readback_node"]))

    def write(self, tag: str, value: float) -> bool:
        """Write ``value`` to the setpoint node of ``tag``; engineering units of the tag.

        If the plant map has a ``take_remote`` entry for ``tag``, the source node is
        written first (or after, when ``before_setpoint`` is false) to take the
        setpoint into remote control.

        Returns:
            True if the server accepted the write, False if it refused it
            (for example ``BadNotWritable`` or ``BadOutOfRange``), or if the
            ``take_remote`` write was refused before the setpoint was written.

        Raises:
            KeyError: if ``tag`` is not in the plant map.
            ConnectionError: on transport failure.
            TimeoutError: if the server does not answer within the timeout.
            ValueError: if ``tag`` is a pid_param target.
        """
        target = self._setpoint_target(tag)
        take = target.get("take_remote")
        if take is None:
            return self._write_setpoint(target, value)
        if take.get("before_setpoint", True):
            if not self._write_take_remote(target):
                return False
            return self._write_setpoint(target, value)
        sp_ok = self._write_setpoint(target, value)
        take_ok = self._write_take_remote(target)
        return sp_ok and take_ok

    def _write_setpoint(self, target: Mapping[str, Any], value: float) -> bool:
        """Write ``value`` to the setpoint node of ``target``; False when refused."""
        node = self._call(self._node(target["setpoint_node"]))
        variant = ua.Variant(float(value), ua.VariantType.Double)
        return self._call(self._write_or_refuse(node, variant))

    def _write_take_remote(self, target: Mapping[str, Any]) -> bool:
        """Write the ``take_remote`` value to its node; False when the server refuses it."""
        take: Mapping[str, Any] = target["take_remote"]
        node_text: str = take.get("node", target["source_node"])
        return self._call(self._take_async(node_text, take["value"]))

    def heartbeat_seen(self) -> bool:
        """True while the control system acknowledges the gateway heartbeat.

        When the plant map configures no ``heartbeat.ack_node``, there is nothing
        to observe and this returns True.

        Raises:
            ConnectionError: if the acknowledgement node cannot be read.
            TimeoutError: if the server does not answer within the timeout.
        """
        ack_node = self._plant_map["heartbeat"].get("ack_node")
        if not ack_node:
            return True
        return self._call(self._heartbeat_seen_async(ack_node))

    def send_heartbeat(self) -> None:
        """Increment and write the heartbeat counter, but at most once per period.

        Raises:
            ConnectionError: on any failure to write the counter.
            TimeoutError: if the server does not answer within the timeout.
        """
        if self._is_heartbeat_too_soon():
            return
        counter = self._next_heartbeat_counter()
        self._call(self._heartbeat_async(self._plant_map["heartbeat"]["node"], counter))
        self._heartbeat_counter = counter
        self._last_heartbeat_s = time.monotonic()

    def read_param(self, tag: str) -> float:
        """Current read-back value of the pid_param target ``tag``, as a float.

        Reads ``readback_node`` (``param_node`` when the map gives none). Fails closed:
        a bad status, a non-numeric value, NaN or infinity raises ``ConnectionError``.

        Raises:
            KeyError: if ``tag`` is not in the plant map.
            ValueError: if ``tag`` is a setpoint target.
            ConnectionError: on transport failure or an unusable value.
            TimeoutError: if the server does not answer within the timeout.
        """
        target = self._param_target(tag)
        node_text = target.get("readback_node", target["param_node"])
        return self._call(self._read_param_async(node_text))

    def write_param(self, tag: str, value: float) -> bool:
        """Write ``value`` to the parameter node of ``tag`` as its configured data type.

        The variant type is the plant map's ``data_type`` (Float or Double); it is never
        taken from the node. Nothing is written, and False is returned, when ``value``
        is not a finite real number, or when it lies outside the float32 range for a
        ``Float`` target (no silent saturation or rounding to infinity).

        Returns:
            True if the server accepted the write; False if the value was refused locally
            or by the server (for example ``BadTypeMismatch`` or ``BadNotWritable``).

        Raises:
            KeyError: if ``tag`` is not in the plant map.
            ValueError: if ``tag`` is a setpoint target.
            ConnectionError: on transport failure.
            TimeoutError: if the server does not answer within the timeout.
        """
        target = self._param_target(tag)
        variant_type = PARAM_VARIANT_TYPES[target["data_type"]]
        number = _param_number(value, variant_type)
        if number is None:
            return False
        return self._call(self._write_param_async(target["param_node"], number, variant_type))

    def param_tags(self) -> frozenset[str]:
        """Tags of the plant map's pid_param targets; never touches the network."""
        targets: Mapping[str, Mapping[str, Any]] = self._plant_map["targets"]
        return frozenset(tag for tag, entry in targets.items() if "param_node" in entry)

    def loop_mode(self, tag: str) -> str:
        """Current loop mode name of ``tag``, or ``"UNKNOWN:<raw>"`` if unmapped."""
        target = self._target(tag)
        return self._call(self._loop_mode_async(target))

    def setpoint_source(self, tag: str) -> str:
        """``"remote"`` or ``"local"``, depending on who owns the setpoint of ``tag``.

        Any raw value other than ``remote_value`` or ``local_value`` is treated as
        ``"local"``: an unrecognised state must never be read as gateway ownership.
        """
        target = self._setpoint_target(tag)
        return self._call(self._source_async(target))

    def release(self, tag: str) -> None:
        """Hand the setpoint of ``tag`` back to local control.

        Raises:
            ConnectionError: on any failure, including a server refusal.
            TimeoutError: if the server does not answer within the timeout.
        """
        target = self._setpoint_target(tag)
        self._call(self._release_async(target))

    def _target(self, tag: str) -> Mapping[str, Any]:
        """Return the plant-map entry of ``tag``; never touches the network."""
        targets: Mapping[str, Mapping[str, Any]] = self._plant_map["targets"]
        try:
            return targets[tag]
        except KeyError as error:
            raise KeyError(tag) from error

    def _setpoint_target(self, tag: str) -> Mapping[str, Any]:
        """Return the entry of ``tag``; ValueError if it is a pid_param target."""
        target = self._target(tag)
        if "setpoint_node" not in target:
            raise ValueError(f"tag {tag!r} is a pid_param target; use read_param/write_param")
        return target

    def _param_target(self, tag: str) -> Mapping[str, Any]:
        """Return the entry of ``tag``; ValueError if it is a setpoint target."""
        target = self._target(tag)
        if "param_node" not in target:
            raise ValueError(f"tag {tag!r} is a setpoint target; use read/write")
        return target

    def _is_heartbeat_too_soon(self) -> bool:
        """True when less than one heartbeat period has passed since the last send."""
        if self._last_heartbeat_s is None:
            return False
        elapsed_s = time.monotonic() - self._last_heartbeat_s
        return elapsed_s < float(self._plant_map["heartbeat"]["period_s"])

    def _next_heartbeat_counter(self) -> int:
        """Return the next counter value: 1, 2, ... up to Int32 max, then back to 1."""
        if self._heartbeat_counter < HEARTBEAT_COUNTER_MAX:
            return self._heartbeat_counter + 1
        return 1

    def _call(self, coroutine: Coroutine[Any, Any, T]) -> T:
        """Run ``coroutine`` on the background loop and block until it returns.

        Raises:
            ConnectionError: if the adapter is already closed.
            TimeoutError: if the coroutine outlives the call budget.
        """
        if self._closed:
            raise ConnectionError("OpcUaPlant is closed")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        done, _ = concurrent.futures.wait([future], timeout=self._timeout_s + 1.0)
        if not done:
            future.cancel()
            raise TimeoutError("OPC UA call did not finish in time")
        return future.result()

    def _disconnect_quietly(self) -> None:
        """Drop the session if one exists, swallowing transport errors.

        The adapter is being torn down, so a failure to disconnect has no
        consequence and must not hide the caller's own exception.
        """
        if self._client is None:
            return
        client = self._client
        self._client = None
        try:
            asyncio.run_coroutine_threadsafe(client.disconnect(), self._loop).result(
                timeout=self._timeout_s
            )
        except (OSError, ua.UaError, TimeoutError):
            return

    async def _ensure_client(self) -> Client:
        """Return the connected client, opening a session lazily on first use."""
        if self._client is not None:
            return self._client
        client = Client(url=self._plant_map["endpoint"], timeout=self._timeout_s)
        await self._protected(client.connect())
        self._client = client
        return client

    async def _node(self, node_text: str) -> Node:
        """Return the asyncua node for ``node_text``, resolving ``nsu=`` namespace URIs."""
        client = await self._ensure_client()
        node_id = await self._resolve_node_id(client, node_text)
        return client.get_node(node_id)

    async def _resolve_node_id(self, client: Client, node_text: str) -> str:
        """Turn ``nsu=<uri>;<rest>`` into ``ns=<index>;<rest>``; other forms pass through."""
        if not node_text.startswith("nsu="):
            return node_text
        uri, separator, rest = node_text[len("nsu=") :].partition(";")
        if not separator or not uri:
            raise PlantMapError(f"node id {node_text!r} must look like 'nsu=<uri>;s=<name>'")
        index = await self._protected(client.get_namespace_index(uri))
        return f"ns={index};{rest}"

    async def _protected(self, awaitable: Any) -> Any:
        """Await ``awaitable`` under the call budget and map failures to our exceptions."""
        try:
            return await asyncio.wait_for(awaitable, self._timeout_s)
        except TimeoutError as error:
            self._drop_client_after_failure()
            raise TimeoutError("OPC UA call timed out") from error
        except (OSError, ua.UaError) as error:
            self._drop_client_after_failure()
            raise self._translate_error(error) from error

    def _drop_client_after_failure(self) -> None:
        """Forget the client so that the next call opens a fresh session."""
        self._client = None

    @staticmethod
    def _translate_error(error: OSError | ua.UaError) -> Exception:
        """Map a transport or status error to ConnectionError, or re-raise it as is."""
        if isinstance(error, ua.UaStatusCodeError) and not _is_transport_status(error.code):
            return error
        return ConnectionError(f"OPC UA transport failure: {error}")

    async def _read_async(self, readback_node: str) -> float:
        """Read one DataValue and return its numeric value, in engineering units."""
        node = await self._node(readback_node)
        data_value = await self._read_node(node.read_data_value())
        if not data_value.StatusCode.is_good():
            raise ConnectionError("read-back status code is not good")
        try:
            number = float(data_value.Value.Value)
        except (AttributeError, TypeError, ValueError) as error:
            raise ConnectionError("read-back value is not a number") from error
        if not math.isfinite(number):
            raise ConnectionError("read-back value is not finite")
        return number

    async def _read_node(self, awaitable: Any) -> Any:
        """Await a node read under the call budget; a bad status code raises ConnectionError."""
        try:
            return await self._protected(awaitable)
        except ua.UaStatusCodeError as error:
            raise ConnectionError(f"OPC UA read status is not good: {error}") from error

    async def _read_param_async(self, node_text: str) -> float:
        """Read one DataValue; a bad status or an unusable number raises ConnectionError."""
        node = await self._node(node_text)
        try:
            data_value = await self._protected(node.read_data_value())
        except ua.UaStatusCodeError as error:
            raise ConnectionError(f"parameter read-back status is not good: {error}") from error
        if not data_value.StatusCode.is_good():
            raise ConnectionError("parameter read-back status code is not good")
        raw = data_value.Value.Value if data_value.Value is not None else None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ConnectionError("parameter read-back value is not a number")
        if not math.isfinite(raw):
            raise ConnectionError("parameter read-back value is not finite")
        return float(raw)

    async def _write_param_async(
        self, node_text: str, number: float, variant_type: ua.VariantType
    ) -> bool:
        """Write ``number`` as ``variant_type``; False when the server refuses it."""
        node = await self._node(node_text)
        return await self._write_or_refuse(node, ua.Variant(number, variant_type))

    async def _write_or_refuse(self, node: Node, variant: ua.Variant) -> bool:
        """Write ``variant`` to ``node``; False when the server refuses the value."""
        try:
            await self._protected(node.write_value(variant))
        except ua.UaStatusCodeError as error:
            if _is_transport_status(error.code):
                raise ConnectionError(f"OPC UA transport failure: {error}") from error
            return False
        except (TimeoutError, OSError, ua.UaError) as error:
            raise ConnectionError(f"OPC UA write failed: {error}") from error
        return True

    async def _heartbeat_async(self, heartbeat_node: str, counter: int) -> None:
        """Write ``counter`` to the heartbeat node, keeping the node's own type."""
        node = await self._node(heartbeat_node)
        variant_type = await self._read_node(node.read_data_type_as_variant_type())
        variant = ua.Variant(counter, variant_type)
        await self._write_or_raise(node, variant)

    async def _heartbeat_seen_async(self, ack_node: str) -> bool:
        """Read the acknowledgement node and return its value as a boolean."""
        node = await self._node(ack_node)
        value = await self._read_node(node.read_value())
        return bool(value)

    async def _loop_mode_async(self, target: Mapping[str, Any]) -> str:
        """Read the mode node and reverse-map its raw integer to a mode name."""
        node = await self._node(target["mode_node"])
        raw = await self._read_node(node.read_value())
        mode_values: Mapping[str, int] = target["mode_values"]
        for mode_name, mode_value in mode_values.items():
            if _raw_equal(mode_value, raw):
                return mode_name
        return f"UNKNOWN:{raw}"

    async def _source_async(self, target: Mapping[str, Any]) -> str:
        """Read the source node and classify the owner of the setpoint."""
        node = await self._node(target["source_node"])
        raw = await self._read_node(node.read_value())
        if _raw_equal(raw, target["remote_value"]):
            return "remote"
        return "local"

    async def _take_async(self, node_text: str, raw_value: object) -> bool:
        """Write ``raw_value`` to ``node_text``, keeping the node's type; False when refused."""
        node = await self._node(node_text)
        variant_type = await self._read_node(node.read_data_type_as_variant_type())
        variant = ua.Variant(raw_value, variant_type)
        return await self._write_or_refuse(node, variant)

    async def _release_async(self, target: Mapping[str, Any]) -> None:
        """Write the release value to the source node, keeping the node's own type."""
        node = await self._node(target["source_node"])
        variant_type = await self._read_node(node.read_data_type_as_variant_type())
        variant = ua.Variant(target["release_value"], variant_type)
        try:
            await self._protected(node.write_value(variant))
        except ua.UaStatusCodeError as error:
            raise ConnectionError(f"OPC UA release was refused: {error}") from error
        except (TimeoutError, OSError, ua.UaError) as error:
            raise ConnectionError(f"OPC UA release failed: {error}") from error

    async def _write_or_raise(self, node: Node, variant: ua.Variant) -> None:
        """Write ``variant`` to ``node``; any failure, refusal included, becomes ConnectionError."""
        try:
            await self._protected(node.write_value(variant))
        except ua.UaStatusCodeError as error:
            raise ConnectionError(f"OPC UA write was refused: {error}") from error
        except (TimeoutError, OSError, ua.UaError) as error:
            raise ConnectionError(f"OPC UA write failed: {error}") from error


def _is_transport_status(status_code: int) -> bool:
    """True when ``status_code`` means the session or socket is gone, not "refused"."""
    name, _documentation = get_name_and_doc(status_code)
    return name in TRANSPORT_STATUS_NAMES


def _param_number(value: object, variant_type: ua.VariantType) -> float | None:
    """``value`` as a float that ``variant_type`` can hold, or None when it must not be written."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    if not math.isfinite(number):
        return None
    if variant_type == ua.VariantType.Float and abs(number) > FLOAT32_MAX:
        return None
    return number


def _raw_equal(left: object, right: object) -> bool:
    """True when ``left`` and ``right`` have the same Python type and equal value.

    The type check keeps a boolean ``True`` from matching the integer ``1``, so a
    plant map value of one kind never matches a raw read of the other kind.
    """
    return type(left) is type(right) and left == right
