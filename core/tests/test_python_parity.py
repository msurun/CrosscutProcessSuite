"""Parity test: the C++ Fopdt (via pybind11) must match the Python reference implementation.

The compiled module is looked up in the directory given by the environment variable
CROSSCUT_CORE_MODULE_DIR (set by CI and by the build instructions in core/README.md).
The test is skipped when the module has not been built.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest
from crosscut_sim.core import Fopdt as PyFopdt

module_dir = os.environ.get("CROSSCUT_CORE_MODULE_DIR")
if module_dir:
    sys.path.insert(0, str(Path(module_dir)))

crosscut_core = pytest.importorskip("crosscut_core")


@pytest.mark.parametrize(
    ("gain", "tau_s", "delay_s", "dt_s"),
    [(2.5, 30.0, 0.0, 1.0), (-19.4, 14.4 * 60, 3.0 * 60, 1.0), (6.6, 654.0, 420.0, 10.0)],
)
def test_cpp_fopdt_matches_python(gain: float, tau_s: float, delay_s: float, dt_s: float) -> None:
    py = PyFopdt(gain, tau_s, delay_s, dt_s)
    cpp = crosscut_core.Fopdt(gain, tau_s, delay_s, dt_s)
    rng = np.random.default_rng(0)
    for u in rng.normal(size=3000):
        assert cpp.update(float(u)) == pytest.approx(py.update(float(u)), abs=1e-12, rel=1e-12)
    assert cpp.value == pytest.approx(py.value, abs=1e-12)


def test_cpp_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError):
        crosscut_core.Fopdt(1.0, 0.0, 1.0, 1.0)
