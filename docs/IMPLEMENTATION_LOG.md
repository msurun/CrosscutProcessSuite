# Implementation log

**Read this first in every new session.** It records what is done, what is pending and in which order.
Update it at the end of every work block (task board, session log, open items) and before suggesting a new session.

Last updated: 2026-10-10 (session 1, after T0.11)

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

Recommended order of the remaining work: T0.12, T0.13 (T0.2 ADRs alongside).
Status: done / in progress / todo.

| ID | Task | Status | Notes |
|---|---|---|---|
| T0.1 | Repo scaffold, license, CI, lint config | done | CI not yet observed |
| T0.2 | PROVENANCE, docs skeleton, ADRs | partly | provenance + this log done; ADR 001 written (`docs/adr/`); ADRs 002-006 todo |
| T0.3 | JSON Schemas (tags, dataset, project, artifact manifest) + contract tests | done | `schemas/`, `tests/test_schemas.py` |
| T0.4 | Artifact manifest read/write, hashing, compatibility rule | done | package `artifacts/` (`crosscut_artifacts.manifest`): deterministic npz, payload path safety, integrity check, major-version rule |
| T0.5 | Simulator core: Plant interface, FOPDT with delay, noise, disturbances, determinism | done | `sim/src/crosscut_sim/{core,disturbances}.py` |
| T0.6 | Wood-Berry plant + PID + scenarios + tests | done | `pid.py`, `plants/wood_berry.py`; scenarios are `Scenario` + `Event` objects, a named-scenario registry comes with T0.8 |
| T0.7 | Grinding-circuit plant v0 + OperatorPolicy + ground-truth gains | done | `plants/mill_circuit.py`; scenarios `nominal`, `observational`, `excited`, `quiet`, `hardness_shift`; `plant.true_gain(driver, cv, hardness)` and hidden `plant.true_hardness` |
| T0.8 | Parquet recorder and dataset export, validated against schema | done | `dataset.py`, `scenarios.py`, `run.py`; `python -m crosscut_sim.run --plant wood_berry --scenario nominal --duration 6h --out data/` is reproducible (same sha256) |
| T0.9 | OPC UA test server (tags, SP/mode writes, heartbeat) | done | `opcua/src/crosscut_opcua/server.py`; tested with an asyncua client only, NOT yet with an external client such as UaExpert |
| T0.10 | OPC UA collector to Parquet | done | `collector.py`; timestamps follow the plant clock (`sim.time_s`), `dataset.write_dataset` is shared with `record` |
| T0.11 | C++ smoke test: CMake, GoogleTest, pybind11, CI on both OS | done locally | `core/` (`crosscut::Fopdt`, 4 GoogleTest tests, pybind11 module, Python parity test). Built locally with clang via the pip package `ziglang` (no MSVC/GCC here); MSVC and GCC builds, `/W4 /WX` and the sanitizer job are UNVERIFIED until CI runs |
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
- Dataset directory: `dataset.json`, `tags.json`, `data/date=YYYY-MM-DD/part-0.parquet` (zstd, one file per UTC day); samples are taken BEFORE each step
  (sample k has time k*dt); `data_sha256` hashes the logical content (ts int64, tag ids joined by newline, value float64, quality uint8), not the Parquet bytes.
- Named scenarios per plant in `scenarios.py` (`nominal`, `noisy_feed`, `feed_step`, `excited` for Wood-Berry); `excited` = random-binary setpoint events.
- Artifacts: directory with `manifest.json` + payload files; `read_manifest` verifies SHA-256 of every payload file and rejects a higher major schema version;
  payload paths must be relative and free of `..`, backslashes and drive letters; `npz_bytes` is byte-deterministic across OS.
- Mill circuit: 3 actuator loops (HPGR press, mill feed, cyclone water) with PV/SP/RSP/MODE/OUT tags `sim.mc.*`; actual actuator state = lag of OUT + OU inner noise (this
  noise-driven variation of the actual PV is the exogenous excitation); CVs p80, mill_power, hpgr_power with hardness-dependent gains (table in the module docstring/tests);
  operator changes local SPs every 30 min as a function of observed hardness (confounder, only for loops in AUTO). Plant-specific options travel in `Scenario.params`.
- OPC UA server: NodeIds `ns=<idx>;s=<tag_id>` in namespace `urn:crosscut:sim`, anonymous/no security (test server only); extra nodes `sim.heartbeat` (client counter),
  `sim.heartbeat_ok`, `sim.time_s`. Client writes go through an asyncua value setter into `plant.write`; refused writes revert. Heartbeat loss returns CAS loops to AUTO
  and blocks selecting CAS until the counter moves again. Run: `python -m crosscut_opcua.server --plant wood_berry --scenario nominal --port 4840 --speed 10`.
- Simulator fidelity: believable causal properties and known ground truth, not believable physics.
- Licence: Apache-2.0.
- PID: positional form, derivative on measurement, conditional-integration anti-windup, bumpless MAN to AUTO by integral tracking.
- Wood-Berry plant: six FOPDT transfer functions in deviation variables; two PID loops with BLT tuning; feed disturbance is additive (base value + OU deviation);
  writes: OUT only in MAN, local SP not in CAS, PV never. Tag ids are `sim.wb.*`.
- Test-first workflow: tests define the behaviour, implementations are delegated to cheap models and verified by the tests.

## Open items

- Observe the first CI run on both operating systems (CI has not been confirmed green; the OPC UA tests take ~25 s and use local ports).
- Try the OPC UA server with an external client (UaExpert) once.
- Verify literature citations in `docs/PROVENANCE.md` and the Wood-Berry parameters against the original paper.
- Trademark registers (EUIPO, UPRP, WIPO, USPTO) for "Crosscut" not checked; firm Crosser is a phonetic neighbour.
- ADRs 002-006 not written yet.
- C++ CI job has never run: MSVC (`/W4 /WX`), GCC (`-Werror`), ASan/UBSan and the Windows module path `build/Release` are unverified.
- Wood-Berry transfer-function coefficients, nominal values and BLT tuning were typed from memory; verify against the originals.

## Session log

### 2026-10-10, session 1
- Planning completed in private docs (PLAN v0.11, stage 0 spec). Name chosen: Crosscut.
- Created repo scaffold (T0.1), contract schemas and tests (T0.3), README, provenance log, this log.
- Schemas were generated by free models via agentkit and verified by the contract tests (34 tests pass).
- Pushed scaffold to `main` (commit ce31bea). Repository confirmed private (unauthenticated API returns 404).
- T0.5/T0.6: wrote core primitives and all tests myself, delegated `pid.py`, `disturbances.py` and `plants/wood_berry.py`
  to agentkit (mistral/codestral for the first two, gemini flash for Wood-Berry, about $0.02 in total); all passed on the first try. 71 tests pass, ruff and mypy clean.
- Git identity is set repo-locally to `msurun <msurun@users.noreply.github.com>`.
- T0.8: tests written first (dataset, scenarios, run). `scenarios.py` and `run.py` passed on the first try; `dataset.py` failed twice in the verify loop
  (wrong column lengths, naive local-time parsing, row-wise partitioning, wrong `to_wide`), so I fixed it by hand. 100 tests pass, ruff and mypy clean.
- Lesson: for code with several array-shape subtleties, specify the shapes explicitly or write the core myself; free models handle isolated functions well.
- T0.4: tests first (27), `manifest.py` delegated; it failed the verify loop on an invented extra path rule and a wrong exception type, fixed by hand. Pushed.
- T0.7: tests first (19 new + scenario/run tests), `Scenario.params` added; the 560-line plant was implemented by a Haiku subagent (agentkit free models cannot handle files this size reliably)
  and independently re-verified: 146 tests, ruff, mypy clean.
- T0.9/T0.10: tests first (8 server/collector tests), implemented by a Haiku subagent incl. a `write_dataset` refactor; I fixed two lint/type nits in my own tests. 155 tests, ruff, mypy clean.
- T0.11: wrote `core/` myself (small); local toolchain via pip (`cmake`, `ninja`, `ziglang`, `pybind11`) with zig wrappers for CC/CXX/AR; 4 C++ tests and 5 parity tests pass locally.
  Local-only helper scripts live in the session scratchpad, not in the repo. CI job `cpp` added to the workflow. ADR 001 written.
- Next: T0.12 (README/demo notebook), T0.13 (experiment 0 on the mill circuit), ADRs 002-006; then check CI.
