"""Tests for tools/validation_report.py: the CLI and the site-file missing codes (#40).

The tool is loaded by path. The synthetic dataset comes from the softsensor test module,
which plants a known delay, bias and noise.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from crosscut_connectors import site as site_module

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str) -> ModuleType:
    """Import a file that is not an installed package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = _load(ROOT / "tools" / "validation_report.py", "validation_report_tool")
SYNTH = _load(ROOT / "softsensor" / "tests" / "test_validation_report.py", "validation_synth")


def test_site_file_supplies_the_missing_codes(tmp_path: Path) -> None:
    """A code declared in the site file is counted and dropped; without a site it stays."""
    data = tmp_path / "data.csv"
    SYNTH._write_dataset(data, missing_code=-777.0)
    site_dir = tmp_path / "root" / "_site"
    site_dir.mkdir(parents=True)
    (site_dir / site_module.SITE_FILE).write_text(
        json.dumps({"import": {"missing_codes": [-777]}}), encoding="utf-8")
    settings = TOOL.site_settings(tmp_path / "root")
    with_site = SYNTH.compute_report(data, SYNTH._config(), settings)
    without = SYNTH.compute_report(data, SYNTH._config())
    assert with_site["stamp_checks"]["LAB"]["missing_code"] == 1
    assert without["stamp_checks"]["LAB"]["missing_code"] == 0


def test_cli_writes_both_files_and_reports_errors(tmp_path: Path) -> None:
    """Exit 0 with report.md and report.json; exit 2 for an unknown tag."""
    data, config = tmp_path / "data.csv", tmp_path / "config.json"
    SYNTH._write_dataset(data)
    config.write_text(json.dumps(SYNTH._config()), encoding="utf-8")
    assert TOOL.main([str(data), str(config), str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "report.md").read_text(encoding="utf-8").startswith("# Validation")
    config.write_text(json.dumps({**SYNTH._config(), "lab_tag": "NOPE"}), encoding="utf-8")
    assert TOOL.main([str(data), str(config), str(tmp_path / "out2")]) == 2
