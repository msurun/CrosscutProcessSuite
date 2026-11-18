"""L5-P1-dq: strict xfail while the default detector misses the owner targets (issue #53).

Held-out seed 100105 of rs.sensor_faults.mix.v1: precision 0.75, recall 1.0 against 0.9 and 0.8; see
docs/L5_FINDINGS.md. When the detector meets the targets this test XPASSes (strict, so it fails)
and the matrix row moves to ready.
"""

from __future__ import annotations

import pytest
from golden import checkout_problem, load_pin, roughersim_dir
from p1_dq import execute


@pytest.mark.slow
@pytest.mark.xfail(strict=True, reason="held-out seed 100105: P 0.75 (FIC203 drift), R 1.0")
def test_dq_report_meets_owner_targets() -> None:
    """The onboarding report flags the injected faults with precision >= 0.9, recall >= 0.8."""
    problem = checkout_problem(roughersim_dir(), load_pin())
    if problem:
        pytest.skip(problem)
    execute()
