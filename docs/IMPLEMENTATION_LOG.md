# Implementation log

**Read this first in every new session.** It records what is done, what is pending and in which order.
Update it at the end of every work block (task board, session log, open items) and before suggesting a new session.

Last updated: 2026-10-10 (session 1, after T0.5/T0.6)

## Project snapshot

Crosscut Process Suite: modular process-control toolkit for mineral processing (loop monitoring, PID tuning,
soft sensors, anomaly detection, MPC, fuzzy/expert rules, ML-based operating-range recommendation, optimization).
Every module is optional. Status: **stage 0 (foundations)**; nothing is usable yet.

- Stack: C++20 core (CMake, pybind11) + Python offline tooling; Windows and Linux from one code base.
- Rules: code, comments, commit messages and docs in English; all data synthetic; no code, data or parameters
  from any employer; every method listed in `docs/PROVENANCE.md` before it is implemented; do not publish to PyPI
  until the trademark registers have been checked.
- Planning documents (Polish: strategy, plan, stage specs) are private and live outside this repository
  (owner's machine, `OpenExpert/docs/`). They are not available in clones of this repo.
- Repository is private. Never force-push. Commit at natural milestones.

## Environment and commands

Python 3.12; dev dependencies in `requirements-dev.txt` (user-site install on the owner's machine).

```bash
python -m pip install -r requirements-dev.txt
python -m pytest                 # all tests
python -m ruff check .           # lint
python -m mypy <package or tests>  # type check
```

CI (`.github/workflows/ci.yml`) runs ruff and pytest on ubuntu-latest and windows-latest.
**CI has not been observed yet** (no GitHub CLI on the owner's machine); ask the owner to check the Actions tab
or confirm the result.

## Task board (stage 0)

Recommended order of the remaining work: T0.8, T0.4, T0.7, T0.9, T0.10, T0.11, T0.12, T0.13 (T0.2 ADRs alongside).
Status: done / in progress / todo.

| ID | Task | Status | Notes |
|---|---|---|---|
| T0.1 | Repo scaffold, license, CI, lint config | done | CI not yet observed |
| T0.2 | PROVENANCE, docs skeleton, ADRs | partly | provenance + this log done; ADRs 001-006 todo |
| T0.3 | JSON Schemas (tags, dataset, project, artifact manifest) + contract tests | done | `schemas/`, `tests/test_schemas.py` |
| T0.4 | Artifact manifest read/write, hashing, compatibility rule | todo | |
| T0.5 | Simulator core: Plant interface, FOPDT with delay, noise, disturbances, determinism | done | `sim/src/crosscut_sim/{core,disturbances}.py` |
| T0.6 | Wood-Berry plant + PID + scenarios + tests | done | `pid.py`, `plants/wood_berry.py`; scenarios are `Scenario` + `Event` objects, a named-scenario registry comes with T0.8 |
| T0.7 | Grinding-circuit plant v0 + OperatorPolicy + ground-truth gains | todo | confounding by ore hardness |
| T0.8 | Parquet recorder and dataset export, validated against schema | todo | |
| T0.9 | OPC UA test server (tags, SP/mode writes, heartbeat) | todo | asyncua |
| T0.10 | OPC UA collector to Parquet | todo | |
| T0.11 | C++ smoke test: CMake, GoogleTest, pybind11, CI on both OS | todo | |
| T0.12 | README polish, demo notebook | todo | |
| T0.13 | Stretch: experiment 0 (SP-based vs MV-based identification) | todo | |

Exit criteria for stage 0 are in the private spec; in short: CI green on both OS, deterministic dataset from
`python -m crosscut_sim.run`, OPC UA server + collector working with an external client, C++ module built and
imported from Python, PROVENANCE complete.

## Decisions

- Dataset storage: Parquet, long format (`ts`, `tag_id`, `value`, `quality`); time = UTC int64 ns; quality 0/1/2.
- Simulator: fixed step (default 1 s), deterministic (`numpy.random.Generator`, PCG64), exact discretization.
  `Plant.step()` advances by `scenario.dt_s` (no argument).
- Loop modes encoded as `0 = MAN`, `1 = AUTO`, `2 = CAS`. In CAS the setpoint follows the remote setpoint tag.
- Simulator fidelity: believable causal properties and known ground truth, not believable physics.
- Licence: Apache-2.0.
- PID: positional form, derivative on measurement, conditional-integration anti-windup, bumpless MAN to AUTO by integral tracking.
- Wood-Berry plant: six FOPDT transfer functions in deviation variables; two PID loops with BLT tuning; feed disturbance is additive (base value + OU deviation);
  writes: OUT only in MAN, local SP not in CAS, PV never. Tag ids are `sim.wb.*`.
- Test-first workflow: tests define the behaviour, implementations are delegated to cheap models and verified by the tests.

## Open items

- Observe the first CI run on both operating systems.
- Verify literature citations in `docs/PROVENANCE.md` and the Wood-Berry parameters against the original paper.
- Trademark registers (EUIPO, UPRP, WIPO, USPTO) for "Crosscut" not checked; firm Crosser is a phonetic neighbour.
- ADRs 001-006 not written yet.
- Wood-Berry transfer-function coefficients, nominal values and BLT tuning were typed from memory; verify against the originals.
- `Scenario` has no registry of named scenarios yet and `python -m crosscut_sim.run` does not exist (T0.8).

## Session log

### 2026-10-10, session 1
- Planning completed in private docs (PLAN v0.11, stage 0 spec). Name chosen: Crosscut.
- Created repo scaffold (T0.1), contract schemas and tests (T0.3), README, provenance log, this log.
- Schemas were generated by free models via agentkit and verified by the contract tests (34 tests pass).
- Pushed scaffold to `main` (commit ce31bea). Repository confirmed private (unauthenticated API returns 404).
- T0.5/T0.6: wrote core primitives and all tests myself, delegated `pid.py`, `disturbances.py` and `plants/wood_berry.py`
  to agentkit (mistral/codestral for the first two, gemini flash for Wood-Berry, about $0.02 in total); all passed on the first try. 71 tests pass, ruff and mypy clean.
- Git identity is set repo-locally to `msurun <msurun@users.noreply.github.com>`.
- Next: T0.8 (Parquet recorder, dataset export, `python -m crosscut_sim.run`, named scenarios), then T0.4, T0.7.
