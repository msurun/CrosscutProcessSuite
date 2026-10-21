"""No-write guard for the advisory supervisor (ADR 010).

Static checks (import graph, forbidden calls) and a dynamic check (filesystem writes stay in
tmp_path) that together make a plant write path or hidden side channel visible in CI.
"""

from __future__ import annotations

import ast
import builtins
import io
import json
import os
import pathlib
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from crosscut_fuzzy.model import system_from_dict
from crosscut_supervisor.advise import advise
from crosscut_supervisor.audit import AckRequest, AuditLog, ack
from crosscut_supervisor.config import SupervisorConfigError, load_config
from crosscut_supervisor.gates import GateResult

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR_SRC = ROOT / "supervisor" / "src" / "crosscut_supervisor"
API_ROUTES = ROOT / "api" / "src" / "crosscut_api" / "supervisor_routes.py"
FUZZY_EXAMPLE = ROOT / "fuzzy" / "examples" / "mill_feed_supervisor.json"

# Top-level names that reach a plant: OPC UA clients/servers and the connector packages.
FORBIDDEN_IMPORTS = frozenset(
    {"opcua", "asyncua", "crosscut_opcua", "connectors", "crosscut_connectors"}
)
# Crosscut packages the supervisor may depend on (its pyproject dependencies).
ALLOWED_DEPENDENCIES = ("crosscut_fuzzy", "crosscut_loops")
# Known transitive violations: {package: forbidden names it imports}.
# Empty today; add an entry with a comment instead of failing if a dependency gains one.
KNOWN_TRANSITIVE: dict[str, frozenset[str]] = {}

FORBIDDEN_CALLS = frozenset({"eval", "exec", "import_module", "__import__"})
FORBIDDEN_MODULES = frozenset({"subprocess", "socket", "requests", "urllib", "importlib"})

VALID_CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "mill-feed",
    "fuzzy_system_id": "mill_feed_supervisor",
    "output_id": "feed_change",
    "target_loop": "FIC101",
    "mode": "advisory",
    "gates": [{"loop": "FIC101", "block_on": ["manual"], "warn_on": ["oscillating"]}],
    "silent_band": 0.5,
    "min_activation": 0.2,
    "min_interval_s": 60,
    "display_clamp": [-10, 10],
}


def _parse(path: Path) -> ast.Module:
    """Parse one Python source file."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    """Full dotted names of every module imported anywhere in ``tree``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _top_levels(tree: ast.Module) -> set[str]:
    """Top-level package names imported by ``tree``."""
    return {name.split(".")[0] for name in _imported_modules(tree)}


def _package_files(package: str) -> list[Path]:
    """Source files of a repository package (``crosscut_x`` under ``*/src``)."""
    return sorted(p for src in ROOT.glob(f"*/src/{package}") for p in src.rglob("*.py"))


def _supervisor_files() -> list[Path]:
    """Every supervisor source file."""
    return sorted(SUPERVISOR_SRC.rglob("*.py"))


def _closure() -> dict[str, set[str]]:
    """Map each reachable crosscut_* dependency to the top-level names its sources import."""
    seen: dict[str, set[str]] = {}
    todo = list(ALLOWED_DEPENDENCIES)
    while todo:
        package = todo.pop()
        if package in seen:
            continue
        seen[package] = set().union(*(_top_levels(_parse(f)) for f in _package_files(package)))
        todo.extend(n for n in seen[package] if n.startswith("crosscut_") and _package_files(n))
    return seen


def test_forbidden_names_match_real_packages() -> None:
    """The forbidden list names the real package directories under opcua/ and connectors/."""
    assert (ROOT / "opcua" / "src" / "crosscut_opcua").is_dir()
    assert (ROOT / "connectors" / "src" / "crosscut_connectors").is_dir()


def test_supervisor_has_no_plant_imports() -> None:
    """No supervisor module imports an OPC UA or connector package."""
    files = _supervisor_files()
    assert files
    for path in files:
        bad = _top_levels(_parse(path)) & FORBIDDEN_IMPORTS
        assert not bad, f"{path.name} imports {sorted(bad)}"


def test_supervisor_routes_have_no_plant_imports() -> None:
    """The API routes for the supervisor (when present) import no plant package."""
    if not API_ROUTES.exists():
        pytest.skip(f"{API_ROUTES.relative_to(ROOT)} does not exist yet")
    bad = _top_levels(_parse(API_ROUTES)) & FORBIDDEN_IMPORTS
    assert not bad, f"supervisor_routes imports {sorted(bad)}"


def test_transitive_dependencies_have_no_plant_imports(capsys: pytest.CaptureFixture[str]) -> None:
    """Dependencies of the supervisor do not import plant packages, except known entries."""
    found = {pkg: names & FORBIDDEN_IMPORTS for pkg, names in _closure().items()}
    found = {pkg: names for pkg, names in found.items() if names}
    with capsys.disabled():
        for pkg, names in found.items():
            print(f"\ntransitive plant import: {pkg} -> {sorted(names)}")
    unexpected = {p: n for p, n in found.items() if not n <= KNOWN_TRANSITIVE.get(p, frozenset())}
    assert not unexpected, f"unexpected transitive plant imports: {unexpected}"


def _is_write_mode(mode: object) -> bool:
    """True if an ``open`` mode string can modify a file."""
    return isinstance(mode, str) and any(flag in mode for flag in "wax+")


class _WriteRecorder:
    """Records every write target seen through the patched filesystem entry points."""

    def __init__(self) -> None:
        """Start with no recorded targets."""
        self.targets: list[Path] = []

    def add(self, target: object) -> None:
        """Record one target (path-like); non-path targets such as fds are ignored."""
        if isinstance(target, (str, bytes, os.PathLike)):
            self.targets.append(Path(os.fsdecode(target)).resolve())

    def wrap_open(self, real: Any) -> Any:
        """An ``open`` replacement that records write-mode targets and delegates."""

        def recording_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if _is_write_mode(mode):
                self.add(file)
            return real(file, mode, *args, **kwargs)

        return recording_open

    def wrap_method(self, real: Any) -> Any:
        """A ``Path`` method replacement recording ``self`` (write_text, mkdir, ...)."""

        def recording(path: Path, *args: Any, **kwargs: Any) -> Any:
            self.add(path)
            return real(path, *args, **kwargs)

        return recording

    def wrap_move(self, real: Any) -> Any:
        """An ``os.replace``/``os.rename`` replacement recording source and destination."""

        def recording(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
            self.add(src)
            self.add(dst)
            return real(src, dst, *args, **kwargs)

        return recording


@pytest.fixture
def recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_WriteRecorder]:
    """Patch write entry points after tmp_path exists (so its creation is not recorded)."""
    rec = _WriteRecorder()
    monkeypatch.setattr(builtins, "open", rec.wrap_open(builtins.open))
    monkeypatch.setattr(io, "open", rec.wrap_open(io.open))
    for name in ("write_text", "write_bytes", "mkdir"):
        monkeypatch.setattr(pathlib.Path, name, rec.wrap_method(getattr(pathlib.Path, name)))
    for name in ("replace", "rename"):
        monkeypatch.setattr(os, name, rec.wrap_move(getattr(os, name)))
    yield rec


def _run_public_flow(tmp_path: Path) -> None:
    """Load a config, advise on the fuzzy example with an open gate, append and ack."""
    system = system_from_dict(json.loads(FUZZY_EXAMPLE.read_text(encoding="utf-8")))
    config = load_config(deepcopy(VALID_CONFIG))
    snapshot = {"mill_power": 3000.0, "p80": 125.0}
    advice = advise(system, config, snapshot, GateResult("open", ()), 1)
    assert advice is not None
    log = AuditLog(tmp_path / "audit" / "log.jsonl")
    log.append(advice.to_record())
    ack(log, AckRequest(advice.advice_id, "accepted", "ok", "operator", 2))
    assert log.verify().ok


def test_public_flow_writes_only_inside_tmp_path(recorder: _WriteRecorder, tmp_path: Path) -> None:
    """Every filesystem write target of the public flow lies inside tmp_path."""
    root = tmp_path.resolve()
    _run_public_flow(tmp_path)
    assert recorder.targets, "the recorder saw no writes: the patching is broken"
    outside = [t for t in recorder.targets if not t.is_relative_to(root)]
    assert not outside, f"writes outside tmp_path: {outside}"


@pytest.mark.parametrize("mode", ["closed_loop", "write", "auto", "", None, 1])
def test_modes_other_than_off_and_advisory_are_rejected(mode: object) -> None:
    """load_config refuses every mode except off and advisory."""
    with pytest.raises(SupervisorConfigError):
        load_config({**VALID_CONFIG, "mode": mode})


@pytest.mark.parametrize("mode", ["off", "advisory"])
def test_allowed_modes_load(mode: str) -> None:
    """The two permitted modes load."""
    assert load_config({**VALID_CONFIG, "mode": mode}).mode == mode


def _call_name(node: ast.Call) -> str:
    """Name of the called function (``f`` for both ``f()`` and ``m.f()``)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _violations(tree: ast.Module) -> list[str]:
    """Forbidden calls and imports found in ``tree``."""
    found = [
        f"call {_call_name(n)}()"
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _call_name(n) in FORBIDDEN_CALLS
    ]
    modules = _imported_modules(tree)
    found += [f"import {m}" for m in modules if m.split(".")[0] in FORBIDDEN_MODULES]
    return found


def test_supervisor_source_has_no_dynamic_or_network_code() -> None:
    """No eval/exec/import_module/subprocess/socket/requests/urllib in the supervisor package."""
    problems = {p.name: v for p in _supervisor_files() if (v := _violations(_parse(p)))}
    assert not problems, f"forbidden constructs: {problems}"


def test_violation_scanner_detects_forbidden_code() -> None:
    """The scanner itself flags the constructs it is meant to catch."""
    tree = ast.parse("import subprocess\nfrom urllib.request import urlopen\neval('1')\n")
    assert len(_violations(tree)) == 3
