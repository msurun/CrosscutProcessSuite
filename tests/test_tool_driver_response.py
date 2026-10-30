"""Tests for tools/driver_response.py: the step-size limit is an argument, not a constant.

The tool is loaded by path (it is not an installed package). A synthetic driver gets one step
of 1.2 and one of 3.0 units, and min_step decides which of them are kept.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "driver_response.py"
DT_S = 10.0


def load_tool_module() -> ModuleType:
    """Import the tool by file path; the module must be in sys.modules for dataclasses."""
    spec = importlib.util.spec_from_file_location("tool_driver_response", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = load_tool_module()


def stepped_driver() -> tuple[np.ndarray, np.ndarray]:
    """Six hours at 10 s: 10 -> 11.2 at 30 min, then 11.2 -> 14.2 at 90 min."""
    t_s = np.arange(0.0, 6 * 3600.0, DT_S)
    driver = np.full_like(t_s, 10.0)
    driver[t_s >= 1800.0] = 11.2
    driver[t_s >= 5400.0] = 14.2
    return t_s, driver


def sizes(min_step: float) -> list[float]:
    """Rounded sizes of the steps kept for a given min_step."""
    t_s, driver = stepped_driver()
    events = TOOL.driver_events(t_s, driver, DT_S, min_step=min_step)
    return [round(float(event.size), 2) for event in events]


@pytest.mark.parametrize(
    ("min_step", "expected"),
    [(0.4, [1.2, 3.0]), (2.0, [3.0]), (5.0, [])],
)
def test_driver_events_keep_only_steps_above_min_step(
    min_step: float, expected: list[float]
) -> None:
    """The kept steps follow the min_step argument."""
    assert sizes(min_step) == expected


def test_driver_events_default_min_step_is_the_documented_value() -> None:
    """Without an argument the default step limit applies."""
    t_s, driver = stepped_driver()
    default = TOOL.driver_events(t_s, driver, DT_S)
    assert len(default) == len(sizes(TOOL.DEFAULT_MIN_STEP))


def test_command_line_options_are_parsed() -> None:
    """--min-step, --pre-s and --post-s are read; positionals keep their order."""
    args = TOOL._parse(
        ["--min-step", "2", "--pre-s", "60", "--post-s", "600", "root", "ds", "drv", "a:fopdt"]
    )
    assert (args.min_step, args.pre_s, args.post_s) == (2.0, 60.0, 600.0)
    assert (args.root, args.dataset, args.driver_tag, args.outputs) == (
        "root", "ds", "drv", ["a:fopdt"],
    )
