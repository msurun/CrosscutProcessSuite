# Implementation log

**Read this first in every new session.** It records what is done, what is pending and in which order.
Update it at the end of every work block (task board, session log, open items) and before suggesting a new session.

Last updated: 2026-10-11 (session 2: C2, C3 and B3 (SQL via sqlite) done)

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
**CI was observed green (owner's screenshot, 2026-10-10, runs #1 to #7 incl. the C++ job on Ubuntu and Windows).**

## Task board (stage 0)

Stage 0 is complete except the demo notebook (optional). Next: stage 1 (see below) (T0.2 ADRs alongside).
Status: done / in progress / todo.

| ID | Task | Status | Notes |
|---|---|---|---|
| T0.1 | Repo scaffold, license, CI, lint config | done | CI green |
| T0.2 | PROVENANCE, docs skeleton, ADRs | done | ADRs 001-006 accepted, ADR 007 (GUI) proposed in `docs/adr/` |
| T0.3 | JSON Schemas (tags, dataset, project, artifact manifest) + contract tests | done | `schemas/`, `tests/test_schemas.py` |
| T0.4 | Artifact manifest read/write, hashing, compatibility rule | done | package `artifacts/` (`crosscut_artifacts.manifest`): deterministic npz, payload path safety, integrity check, major-version rule |
| T0.5 | Simulator core: Plant interface, FOPDT with delay, noise, disturbances, determinism | done | `sim/src/crosscut_sim/{core,disturbances}.py` |
| T0.6 | Wood-Berry plant + PID + scenarios + tests | done | `pid.py`, `plants/wood_berry.py`; scenarios are `Scenario` + `Event` objects, a named-scenario registry comes with T0.8 |
| T0.7 | Grinding-circuit plant v0 + OperatorPolicy + ground-truth gains | done | `plants/mill_circuit.py`; scenarios `nominal`, `observational`, `excited`, `quiet`, `hardness_shift`; `plant.true_gain(driver, cv, hardness)` and hidden `plant.true_hardness` |
| T0.8 | Parquet recorder and dataset export, validated against schema | done | `dataset.py`, `scenarios.py`, `run.py`; `python -m crosscut_sim.run --plant wood_berry --scenario nominal --duration 6h --out data/` is reproducible (same sha256) |
| T0.9 | OPC UA test server (tags, SP/mode writes, heartbeat) | done | `opcua/src/crosscut_opcua/server.py`; tested with an asyncua client only, NOT yet with an external client such as UaExpert |
| T0.10 | OPC UA collector to Parquet | done | `collector.py`; timestamps follow the plant clock (`sim.time_s`), `dataset.write_dataset` is shared with `record` |
| T0.11 | C++ smoke test: CMake, GoogleTest, pybind11, CI on both OS | done | `core/` (`crosscut::Fopdt`, 4 GoogleTest tests, pybind11 module, Python parity test). Built locally with clang via the pip package `ziglang`; MSVC, GCC, `/W4 /WX` and the sanitizer job verified by CI (green) |
| T0.12 | README polish, demo notebook | done (README); notebook skipped | top-level README with quick start and the experiment figure |
| T0.13 | Stretch: experiment 0 (SP-based vs MV-based identification) | done | `experiments/exp00_sp_vs_mv/` (script, tests, results, README). Finding: with the operator on, raw SP/PV models see ~0 gain; high-pass (10 min) recovers it for SP and PV alike; OUT is a poor input |

Exit criteria for stage 0 are in the private spec; in short: CI green on both OS, deterministic dataset from
`python -m crosscut_sim.run`, OPC UA server + collector working with an external client, C++ module built and
imported from Python, PROVENANCE complete.

## Validation roadmap (testing without a real installation)

Full strategy: `docs/TESTING_STRATEGY.md`; assumptions to retire: `docs/ASSUMPTIONS.md`; UX idea notes for the fuzzy
editor: `docs/design/fuzzy-studio.md`. Backlog, in the order to do it:

| ID | Task | Stage | Status |
|---|---|---|---|
| V1 | Fault-injection layer for the simulators (sensor freeze/spike/drift/bad quality, stiction, jitter, dropouts, mode flips) | 1 | partly done: `sim/src/crosscut_sim/faults.py` (`FaultyPlant` wrapper: freeze, drift, spike, bad_quality, dropout on what the client reads). Stiction, timestamp jitter and mode flips still todo (stiction needs the actuator inside the plant; mode flips are possible with `Event`s) |
| V2 | Messy-export corpus generator + importer robustness tests | 1 | todo |
| V6 | Customer-run validation kit (export guide, readiness checklist, anonymizer, report template) | 1 | todo |
| V3 | Public dataset benchmarks (flotation quality, anomaly, degradation); add licence rows to PROVENANCE | 1-2 | todo |
| V4 | Lab testbed bridge via OPC UA (low-cost thermal control kit) | 2 | todo |
| V5 | Virtual DCS with a soft PLC and write-path test suite; must pass before any real write | 2-3 | todo |
| V7 | Pilot partner package (agreement outline, security checklist) | 3 | todo |
| V8 | Review ASSUMPTIONS.md at each stage end | continuous | todo |

## Stage 1 task board

| ID | Task | Status | Notes |
|---|---|---|---|
| A1 | Fault-injection wrapper (V1) | done (measurement faults) | see V1 |
| B1/B2 | FastAPI backend: `/health`, `/datasets`, `/datasets/{id}/tags`, `/datasets/{id}/series` with min/max downsampling | done | package `api/` (`crosscut_api.app`, `downsample`); NaN is sent as null; dataset ids are resolved inside the data root only |
| A2 | Messy-export corpus generator + importer robustness tests (V2) | done | `connectors/src/crosscut_connectors/messy.py`, 6 styles (delimiters, decimal comma, local time, BOM + preamble, text for bad values, duplicates + shuffled rows); round-trip tests |
| A3 | CSV connector | done | `csv_import.py`: wide format, first column = timestamp, stdlib csv (fine for MB-sized files; switch to Arrow's CSV reader for GB-sized exports). Not yet: long-format exports, per-column units, DST-ambiguous local times |
| B3 | OPC UA read connector, SQL connector | done (SQL, OPC UA) | `connectors/src/crosscut_connectors/sql_import.py`: `import_sql(database, query, out_dir, dataset_id=, tz=)`, long-format SELECT (ts, tag, value[, quality]) from a sqlite file opened read-only, pivoted to wide; ISO text or epoch seconds; last duplicate wins; NULL/missing -> NaN + BAD. Not yet: other DB drivers (ODBC/GE Historian), OPC UA read connector. Original note: OPC UA recording already exists (`crosscut_opcua.collector`, T0.10); SQL (testable with sqlite) and GE Historian last |
| C1 | Loop monitoring (CPM) | done | package `loops/`: `metrics.py` (Harris index, Hagglund oscillation, saturation, flatline), `monitor.py` (`analyze_loop` -> `LoopReport` with classification manual / saturated / oscillating / poor_performance / ok and findings). Tested on synthetic signals with known answers and on a Wood-Berry run with a frozen sensor. Known limit: Hagglund flags slow wandering errors as oscillation |
| C2 | Stiction detection | done | `loops/src/crosscut_loops/stiction.py`: THD of the PV oscillation (healthy disturbance-driven cycle ~0.02, stiction 1.0-1.8). Self-regulating process only; `out` validated but unused; wired into `analyze_loop` (`LoopReport.stiction_verdict`, finding "stiction suspected") |
| C3 | PID tuning report | done (library) | `loops/src/crosscut_loops/{tuning_rules,identification,tuning_report}.py`: FOPDT fit (ARX + delay scan), SIMC and AMIGO PI, robustness slider, DCS parameter forms, Markdown report blocked when stiction is suspected. Not yet: PID/derivative, closed-loop data handling, cascade order, wiring to datasets/API |
| C4 | Benefit report | done (library) | `loops/src/crosscut_loops/benefit.py`: `estimate_benefit(pv, BenefitAssumptions)` -> `BenefitEstimate` (freed room = margin_sigmas * std * std_reduction, capped at the gap to the limit; value per hour), `render_benefit_markdown`; assumptions in `ASSUMPTIONS.md`. Not yet: wiring to datasets/API, deriving std_reduction from loop reports |
| D1-D3 | Screen sketches, trend viewer (React/TS, needs ADR 007 decision), loop views | todo | ask the owner before D2 |
| E1/E2 | Customer validation kit (V6), public benchmarks (V3) | todo | |

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

- Try the OPC UA server with an external client (UaExpert) once.
- Verify literature citations in `docs/PROVENANCE.md` and the Wood-Berry parameters against the original paper.
- Trademark registers (EUIPO, UPRP, WIPO, USPTO) for "Crosscut" not checked; firm Crosser is a phonetic neighbour.
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
- T0.13: wrote the experiment myself (FIR least squares, 7 signal variants, 2 scenarios, 5 seeds x 48 h, ~30 s). Result is documented honestly in the experiment README,
  including that timescale separation, not SP-vs-PV, is what matters in this simulator. CI confirmed green for runs #1 to #7.
- Stage 0 closed: top-level README, ADRs 001-007 (007 = GUI approach, proposed).
- Next (stage 1 "Loop & Data Insight", read-only product): connectors (OPC UA read, CSV, SQL, GE Historian), Data Studio with trend viewer, loop monitoring (CPM), PID tuning report,
  benefit report. Start with the backend API and the trend viewer on simulator datasets. Stage plan lives in the private planning documents.

### 2026-10-10, session 1 (stage 1 start)
- agentkit `budget.daily_usd` raised from 1.0 to 2.0 (monthly stays 5.0).
- A1: tests first (`sim/tests/test_faults.py`, 15), `faults.py` delegated (mistral/codestral, passed first try, $0); I fixed 3 lint nits.
- B1/B2: tests first (`api/tests`, 18); `downsample.py` delegated and accepted; the delegated `app.py` passed the tests but used global state,
  a lexical-only path check and would have emitted invalid JSON for NaN, so I rewrote it by hand and added tests for both cases.
- Note: the MCP `delegate` tool returned a bare error twice in this session; the CLI (`agentkit delegate ...` via `agentkit.cli.main`) worked.
- A2/A3: tests first (round trip over 6 messy styles), generator and importer delegated (codestral, gpt-oss-120b). Generator needed one fix (numpy 2 `repr(np.float64)`),
  the importer failed 2 tests (sort before dedup, strptime errors) plus a bare `except`; fixed by hand. 
- C1: tests first (10 metrics + 7 monitor). Free models failed `metrics.py` twice (shape errors in the AR fit and windowing) and `hard_code` went to DeepSeek which spent $0.05 and returned nothing
  (reasoning ate the whole 4000-token budget): do not use `hard_code` for numerics with a small output cap. I wrote `metrics.py` by hand. The delegated `monitor.py` passed the tests but had 428 lines
  and 7-parameter helpers, so I rewrote it in ~130 lines.

### 2026-10-11, session 2
- Pushed the 4 local commits. agentkit: paid models no longer think (DeepSeek thinking disabled at all levels, Gemini sent as `low`).
- C2: tests written by mistral/codestral (I fixed the simulation: constant load needed, noise 0.005, S=0.5/J=0.25), `stiction.py` by codestral passed first try; lint/type/size fixes by a Haiku subagent. A first attempt with a Claude subagent writing everything was stopped: tests and bulk code go to agentkit free models. MCP `delegate` still errors; CLI works with `PYTHONPATH=<agentkit dir> python -m agentkit.cli delegate ...`.
- C3: tests and implementations written by DeepSeek flash (pro once, for the SIMC/AMIGO formulas), all passed `verify`; Haiku did lint/type/size fixes. Local-LLM code review (Legion + Firefly, 20 files) found only two minor edge cases (stiction on empty input raises IndexError, harris_index on a constant series raises ZeroDivisionError); the rest was noise.

- B3 (SQL): tests by DeepSeek flash, implementation by codestral (verify failed only on 3 test bugs: pandas API on a pyarrow table), Haiku fixed tests, removed an undeclared pandas import, split long functions; I fixed a local-time bug in `_start_iso`. Also: edge cases (empty stiction input, constant Harris series) and mypy cleanup (`py.typed` for sim) via Haiku. `import_sql` has 5 parameters (3 positional + 2 keyword-only), accepted.

- ADR 007 accepted by the owner (web GUI: FastAPI + React/TypeScript). Pushed.
- B3 (OPC UA read): `connectors/src/crosscut_connectors/opcua_import.py`, `import_opcua(endpoint, nodes, out_dir, *, dataset_id, period_s, n_samples)`: read-only wall-clock sampler of given NodeIds; bad status or failed read -> NaN + BAD; unreachable endpoint -> ConnectionError. Tests (11) run against the `crosscut_opcua` test server, written by DeepSeek flash; implementation by DeepSeek flash needed three hand fixes (a test helper used a pyarrow filter wrongly, wrong tag names in tests, `Value.Value` unwrapping). Haiku fixed lint/types; local-LLM review found one real issue (blocking `time.sleep` inside the event loop, now `asyncio.sleep`). Not yet: subscriptions, security policies/certificates, reconnect, namespace lookup by URI (tests assume `ns=2`).
- C4: tests by DeepSeek flash from my spec; the delegated implementation passed my own review of semantics better than my spec (my formula claimed the whole gap to the limit, the model's counted only room freed by the variance cut), so I changed the tests, not the code. Local-LLM review: no findings.
