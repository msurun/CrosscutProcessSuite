"""Golden-hash guard for the pinned RougherSim release (rs-v0.10.0).

Records two 24 h scenarios with the sibling RougherSim checkout and compares the
hash recipe in golden.py with pin.json. Skips unless the checkout is the pin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from golden import (
    SCENARIOS,
    checkout_problem,
    golden_hash,
    load_pin,
    record,
    roughersim_dir,
    write_golden,
)


@pytest.mark.slow
@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_recording_matches_golden(
    scenario_id: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """The recorded scenario hashes to the golden stored in pin.json."""
    pin = load_pin()
    rs_dir = roughersim_dir()
    problem = checkout_problem(rs_dir, pin)
    if problem:
        pytest.skip(problem)
    scenario = rs_dir / "scenarios" / f"{scenario_id}.json"
    seed = json.loads(scenario.read_text(encoding="utf-8"))["seed"]
    key = f"{scenario_id}/{seed}"
    out = tmp_path / "rec"
    record(rs_dir, scenario, out)
    digest = golden_hash(out)
    if request.config.getoption("--update-goldens"):
        write_golden(pin, key, digest)
        return
    expected = pin["goldens"].get(key)
    assert expected is not None, f"no golden for {key}; run with --update-goldens"
    assert digest == expected, (
        f"golden mismatch for {key} on pinned {pin['tag']}: a RougherSim model change needs "
        "a minor bump with a CHANGELOG entry; see README.md"
    )
