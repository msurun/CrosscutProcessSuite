"""No-write guard for the PLS soft sensor.

Only the Write Gateway (gateway/) may write to a control system (ADR 012); analysis packages
must never import write capability.

Static checks (import graph, forbidden calls) and a dynamic check (filesystem writes stay in
tmp_path) that make a plant write path or hidden side channel visible in CI.
"""

from __future__ import annotations

import ast
import builtins
import io
import json
import os
import pathlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from crosscut_softsensor.config import SoftSensorConfigError, load_config
from crosscut_softsensor.pls import PlsModel, fit_pls

ROOT = Path(__file__).resolve().parents[2]
SOFT_SRC = ROOT / "softsensor" / "src" / "crosscut_softsensor"
API_ROUTES = ROOT / "api" / "src" / "crosscut_api" / "softsensor_routes.py"

# Top-level names that reach a plant: OPC UA clients/servers and the connector packages.
FORBIDDEN_IMPORTS = frozenset(
    {"opcua", "asyncua", "crosscut_opcua", "connectors", "crosscut_connectors"}
)
FORBIDDEN_CALLS = frozenset({"eval", "exec", "import_module", "__import__"})
FORBIDDEN_MODULES = frozenset({"subprocess", "socket", "requests", "urllib", "importlib"})

VALID_CONFIG: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "mc",
    "target_tag": "y",
    "input_tags": ["a", "b", "c"],
    "mode": "advisory",
    "lags_s": [0, 60],
    "sample_period_s": 60,
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


def _soft_files() -> list[Path]:
    """Every softsensor source file."""
    return sorted(SOFT_SRC.rglob("*.py"))


def test_softsensor_has_no_plant_imports() -> None:
    """No softsensor module imports an OPC UA or connector package."""
    files = _soft_files()
    assert files
    for path in files:
        bad = _top_levels(_parse(path)) & FORBIDDEN_IMPORTS
        assert not bad, f"{path.name} imports {sorted(bad)}"


def test_softsensor_routes_have_no_plant_imports() -> None:
    """The API routes for the softsensor detector (when present) import no plant package."""
    if not API_ROUTES.exists():
        pytest.skip(f"{API_ROUTES.relative_to(ROOT)} does not exist yet")
    bad = _top_levels(_parse(API_ROUTES)) & FORBIDDEN_IMPORTS
    assert not bad, f"softsensor_routes imports {sorted(bad)}"


def test_softsensor_depends_on_no_other_crosscut_package() -> None:
    """The softsensor package imports no other crosscut_* package, so its closure is itself."""
    names = set().union(*(_top_levels(_parse(f)) for f in _soft_files()))
    others = {n for n in names if n.startswith("crosscut_")} - {"crosscut_softsensor"}
    assert not others, f"unexpected crosscut dependencies: {sorted(others)}"


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
    """Load a config, fit on synthetic data, and write the model dictionary into tmp_path."""
    config = load_config(dict(VALID_CONFIG))
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 6))
    y = x[:, 0] - 2.0 * x[:, 3] + rng.normal(scale=0.1, size=200)
    model = fit_pls(x, y, config)
    (tmp_path / "model.json").write_text(json.dumps(model.to_dict()), encoding="utf-8")
    assert PlsModel.from_dict(model.to_dict()).sha256() == model.sha256()


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
    with pytest.raises(SoftSensorConfigError):
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


def test_softsensor_source_has_no_dynamic_or_network_code() -> None:
    """No eval/exec/import_module/subprocess/socket/requests/urllib in the package or routes."""
    files = [*_soft_files(), *([API_ROUTES] if API_ROUTES.exists() else [])]
    problems = {p.name: v for p in files if (v := _violations(_parse(p)))}
    assert not problems, f"forbidden constructs: {problems}"


def test_violation_scanner_detects_forbidden_code() -> None:
    """The scanner itself flags the constructs it is meant to catch."""
    tree = ast.parse("import subprocess\nfrom urllib.request import urlopen\neval('1')\n")
    assert len(_violations(tree)) == 3
