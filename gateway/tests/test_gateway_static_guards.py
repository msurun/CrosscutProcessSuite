"""Static guards for the write path (ADR 012).

Only the Write Gateway (gateway/) may write to a control system; analysis packages must
never import write capability.

Scope: loops, fuzzy, supervisor, anomaly, softsensor and the API. The ``opcua`` and
``connectors`` packages are excluded on purpose: they are the connectivity layer and may
legitimately use OPC UA. The gateway skeleton itself must contain no OPC UA import at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCOPE = {
    "loops": ROOT / "loops/src/crosscut_loops",
    "fuzzy": ROOT / "fuzzy/src/crosscut_fuzzy",
    "supervisor": ROOT / "supervisor/src/crosscut_supervisor",
    "anomaly": ROOT / "anomaly/src/crosscut_anomaly",
    "softsensor": ROOT / "softsensor/src/crosscut_softsensor",
    "api": ROOT / "api/src/crosscut_api",
}
GATEWAY_SRC = ROOT / "gateway/src/crosscut_gateway"
OPCUA_MODULES = frozenset({"asyncua", "opcua"})
WRITE_NAMES = frozenset(
    {"write_value", "set_value", "call_method", "write_attribute", "WriteValue"}
)


def _files(directory: Path) -> list[Path]:
    """All Python files below ``directory``."""
    return sorted(directory.rglob("*.py"))


def _imports(tree: ast.Module) -> set[str]:
    """Top-level names of all imported modules."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _write_uses(tree: ast.Module) -> set[str]:
    """Names of write capabilities used as attribute, name or imported alias."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in WRITE_NAMES:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in WRITE_NAMES:
            found.add(node.id)
        elif isinstance(node, ast.ImportFrom):
            found.update(a.name for a in node.names if a.name in WRITE_NAMES)
    return found


def _problems(tree: ast.Module) -> set[str]:
    """Everything forbidden in an analysis package: OPC UA, write calls, the gateway."""
    bad = _imports(tree) & (OPCUA_MODULES | {"crosscut_gateway"})
    return bad | _write_uses(tree)


@pytest.mark.parametrize("name", sorted(SCOPE))
def test_package_has_no_write_capability(name: str) -> None:
    """No OPC UA import, write call or gateway import in the package."""
    files = _files(SCOPE[name])
    assert files, f"no sources found for {name}"
    found = {f.name: p for f in files if (p := _problems(ast.parse(f.read_text("utf-8"))))}
    assert not found, f"{name}: {found}"


def test_gateway_skeleton_has_no_opcua_import() -> None:
    """The skeleton has no connectivity: no OPC UA import and no write call anywhere."""
    files = _files(GATEWAY_SRC)
    assert files
    for f in files:
        tree = ast.parse(f.read_text("utf-8"))
        assert not _imports(tree) & OPCUA_MODULES, f.name
        assert not _write_uses(tree), f.name


def test_scanner_detects_forbidden_code() -> None:
    """The scanner flags the constructs it is meant to catch."""
    tree = ast.parse(
        "import asyncua\nfrom opcua import ua\nimport crosscut_gateway\n"
        "node.write_value(1)\nx = ua.WriteValue()\n"
    )
    assert _problems(tree) == {"asyncua", "opcua", "crosscut_gateway", "write_value", "WriteValue"}
