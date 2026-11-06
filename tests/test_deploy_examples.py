"""Tests for deployment examples and systemd service file consistency.

Validates that example deployment configuration files conform to their JSON schemas
and that the systemd service unit mirrors the command-line interface defined by the
write gateway entry point.
"""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path, PurePosixPath
from typing import Any
from unittest.mock import patch

import jsonschema
from crosscut_gateway import __main__ as gw_main

# Directory anchors relative to the suite repository root
REPO_ROOT = Path(__file__).resolve().parent.parent
PLANT_MAP_EXAMPLE = REPO_ROOT / "deploy" / "examples" / "plant-map.example.json"
WRITE_POLICY_EXAMPLE = REPO_ROOT / "deploy" / "examples" / "write-policy.example.json"
PLANT_MAP_SCHEMA = REPO_ROOT / "schemas" / "plant-map.schema.json"
WRITE_POLICY_SCHEMA = REPO_ROOT / "schemas" / "write-policy.schema.json"
GATEWAY_SERVICE_FILE = REPO_ROOT / "deploy" / "crosscut-gateway.service"
RUN_GATEWAY_CMD = REPO_ROOT / "deploy" / "windows" / "run-gateway.cmd"
SETPOINT_RELATED_KEYS = ("setpoint_node",)


def _load_json(path: Path) -> dict[str, Any]:
    """Read and parse a UTF-8 JSON file from disk into a dictionary mapping.

    # Intuition:
    # Schema validation tests require in-memory dictionary trees parsed from disk.
    # We load the exact file as an operator would to catch encoding and syntax issues.
    """
    try:
        content = path.read_text(encoding="utf-8")
        loaded = json.loads(content)
    except (OSError, ValueError) as err:
        raise AssertionError(f"Failed to read or parse JSON file {path}: {err}") from err
    if not isinstance(loaded, dict):
        raise AssertionError(f"Expected JSON object in {path}, got {type(loaded).__name__}")
    return loaded


def _extract_gateway_cli_flags() -> set[str]:
    """Extract registered CLI option flags from crosscut_gateway.__main__.parse_args.

    # Intuition:
    # Instead of hardcoding expected flags, we inspect the live ArgumentParser built by
    # __main__.parse_args by intercepting parser execution via mock.
    """
    captured: argparse.ArgumentParser | None = None

    def _mock_parse(self: argparse.ArgumentParser, *args: Any, **kwargs: Any) -> argparse.Namespace:
        nonlocal captured
        captured = self
        return argparse.Namespace()

    with patch.object(argparse.ArgumentParser, "parse_args", _mock_parse):
        gw_main.parse_args([])

    if captured is None:
        raise AssertionError("Failed to capture ArgumentParser from crosscut_gateway.__main__")

    return {opt for action in captured._actions for opt in action.option_strings}


def _extract_service_exec_args(service_content: str) -> list[str]:
    """Extract argument list from the ExecStart directive of a systemd unit.

    # Intuition:
    # The service file defines an ExecStart command line. We extract the tokens
    # following the module invocation 'crosscut_gateway' to test CLI parameter validity.
    """
    for line in service_content.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("ExecStart="):
            tokens = shlex.split(trimmed.removeprefix("ExecStart="))
            if "crosscut_gateway" in tokens:
                idx = tokens.index("crosscut_gateway")
                return tokens[idx + 1:]
    raise AssertionError("No ExecStart directive with 'crosscut_gateway' found in service file")


def test_plant_map_example_validates_against_schema() -> None:
    """Verify that plant-map.example.json strictly conforms to plant-map.schema.json."""
    # Arrange: Load the draft schema and the concrete example configuration
    schema = _load_json(PLANT_MAP_SCHEMA)
    example = _load_json(PLANT_MAP_EXAMPLE)
    validator = jsonschema.Draft202012Validator(schema)

    # Act: Collect all schema validation discrepancies
    errors = list(validator.iter_errors(example))

    # Assert: Ensure zero validation errors
    error_summary = "; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors)
    assert not errors, f"Plant map example failed schema validation: {error_summary}"


def test_write_policy_example_validates_against_schema() -> None:
    """Verify that write-policy.example.json strictly conforms to write-policy.schema.json."""
    # Arrange: Load the draft schema and the concrete example configuration
    schema = _load_json(WRITE_POLICY_SCHEMA)
    example = _load_json(WRITE_POLICY_EXAMPLE)
    validator = jsonschema.Draft202012Validator(schema)

    # Act: Collect all schema validation discrepancies
    errors = list(validator.iter_errors(example))

    # Assert: Ensure zero validation errors and verify advisory mode
    error_summary = "; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors)
    assert not errors, f"Write policy example failed schema validation: {error_summary}"
    assert example.get("mode") == "advisory", "Write policy example must use advisory mode"


def test_gateway_service_file_contains_systemd_sections() -> None:
    """Verify that crosscut-gateway.service contains [Unit], [Service], and [Install]."""
    # Arrange & Act: Read the systemd unit configuration
    content = GATEWAY_SERVICE_FILE.read_text(encoding="utf-8")
    expected_sections = ["[Unit]", "[Service]", "[Install]"]

    # Assert: Every required systemd section header must be present
    for section in expected_sections:
        assert section in content, f"Missing required systemd section {section} in service file"


def test_gateway_service_file_mirrors_main_cli_flags() -> None:
    """Verify that crosscut-gateway.service includes CLI flags defined by __main__.py."""
    # Arrange: Dynamically discover CLI options and read service text
    defined_flags = _extract_gateway_cli_flags()
    content = GATEWAY_SERVICE_FILE.read_text(encoding="utf-8")
    required_flags = ["--root", "--policy", "--plant-map", "--mode"]

    # Act & Assert: Ensure all expected flags are defined by the parser and present in service
    for flag in required_flags:
        assert flag in defined_flags, f"Flag {flag} not defined in crosscut_gateway.__main__"
        assert flag in content, f"Flag {flag} missing from crosscut-gateway.service"


def test_gateway_service_execstart_is_valid_for_parse_args() -> None:
    """Verify that the ExecStart arguments parse cleanly using crosscut_gateway.parse_args."""
    # Arrange: Extract the actual argument tokens from ExecStart line
    content = GATEWAY_SERVICE_FILE.read_text(encoding="utf-8")
    exec_args = _extract_service_exec_args(content)

    # Act: Parse the arguments through the real __main__.parse_args function
    parsed = gw_main.parse_args(exec_args)

    # Assert: Verify that the parsed namespace holds valid configured targets
    assert parsed.root == Path("/var/lib/crosscut")
    assert parsed.policy == Path("/var/lib/crosscut/_gateway/policy/write-policy.json")
    assert parsed.plant_map == Path("/var/lib/crosscut/plant-map.json")
    assert parsed.mode == "advisory"


def _unit_paths(service_content: str, directive: str) -> list[PurePosixPath]:
    """Return the paths of every ``directive=`` line of a systemd unit, split on blanks."""
    found: list[PurePosixPath] = []
    for line in service_content.splitlines():
        trimmed = line.strip()
        if trimmed.startswith(directive + "="):
            found.extend(PurePosixPath(p) for p in trimmed.split("=", 1)[1].split())
    return found


def _is_inside(path: PurePosixPath, folder: PurePosixPath) -> bool:
    """Return True when ``path`` equals ``folder`` or lies below it."""
    return path == folder or folder in path.parents


def test_gateway_policy_folder_is_writable_in_unit() -> None:
    """The folder of --policy (live policy and its pin) must be writable, not read-only."""
    # Arrange: the policy path comes from the real parser, the paths from the unit
    content = GATEWAY_SERVICE_FILE.read_text(encoding="utf-8")
    parsed = gw_main.parse_args(_extract_service_exec_args(content))
    policy_dir = PurePosixPath(parsed.policy.as_posix()).parent
    writable = _unit_paths(content, "ReadWritePaths")
    read_only = _unit_paths(content, "ReadOnlyPaths")

    # Assert: inside a ReadWritePaths entry and under no ReadOnlyPaths entry
    assert any(_is_inside(policy_dir, folder) for folder in writable), policy_dir
    assert not any(_is_inside(policy_dir, folder) for folder in read_only), policy_dir
    assert "ProtectSystem=strict" in content


def test_gateway_service_restart_and_umask_hardening() -> None:
    """Config errors (exit 2) must not loop and files must not be readable by 'other'."""
    content = GATEWAY_SERVICE_FILE.read_text(encoding="utf-8")
    lines = {line.strip() for line in content.splitlines()}

    assert "RestartPreventExitStatus=2" in lines
    umask = next(line for line in lines if line.startswith("UMask="))
    assert umask.split("=", 1)[1].endswith("7"), umask
    assert "Group=crosscut-sec" in lines


def test_plant_map_readback_node_is_a_setpoint_node() -> None:
    """The gateway compares read-back with the written setpoint, so it must not be the PV."""
    example = _load_json(PLANT_MAP_EXAMPLE)

    for tag, target in example["targets"].items():
        allowed = {target[key] for key in SETPOINT_RELATED_KEYS}
        assert target["readback_node"] in allowed, f"{tag}: readback_node is not a setpoint node"
        assert not target["readback_node"].endswith(".PV"), tag


def test_run_gateway_cmd_has_no_restart_loop() -> None:
    """NSSM restarts the process; the wrapper must not loop or call timeout itself."""
    text = RUN_GATEWAY_CMD.read_text(encoding="utf-8").lower()
    code = [line for line in text.splitlines() if not line.strip().startswith("rem")]
    body = " ".join(code)

    assert "goto" not in body
    assert "timeout" not in body
    assert "crosscut_gateway" in body


def test_runbook_documents_policy_folder_and_readback() -> None:
    """The runbook names the policy folder the unit uses and explains the read-back node."""
    runbook = (REPO_ROOT / "docs" / "GATEWAY_RUNBOOK.md").read_text(encoding="utf-8")
    parsed = gw_main.parse_args(
        _extract_service_exec_args(GATEWAY_SERVICE_FILE.read_text(encoding="utf-8"))
    )

    assert "_gateway/policy/write-policy.json" in runbook
    assert parsed.policy.as_posix().endswith("_gateway/policy/write-policy.json")
    assert "import verify_chain, read_records" not in runbook
    assert "readback_node" in runbook and "PV" in runbook
