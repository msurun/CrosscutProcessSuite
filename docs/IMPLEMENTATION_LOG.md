# Implementation log

**Read this first in every new session.** It records what is done, what is pending and in which order.
Update it at the end of every work block (task board, session log, open items) and before suggesting a new session.

Last updated: 2026-10-11 (session 2: fuzzy versions and diff backend, mypy clean)

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
| C2 | Stiction detection | done (revised 2026-10-11, see ASSUMPTIONS C5) | `loops/src/crosscut_loops/stiction.py`: THD of the PV oscillation (healthy disturbance-driven cycle ~0.02, stiction 1.0-1.8). Self-regulating process only; `out` validated but unused; wired into `analyze_loop` (`LoopReport.stiction_verdict`, finding "stiction suspected") |
| C3 | PID tuning report | done (library) | `loops/src/crosscut_loops/{tuning_rules,identification,tuning_report}.py`: FOPDT fit (ARX + delay scan), SIMC and AMIGO PI, robustness slider, DCS parameter forms, Markdown report blocked when stiction is suspected. Not yet: PID/derivative, closed-loop data handling, cascade order, wiring to datasets/API |
| C4 | Benefit report | done (library) | `loops/src/crosscut_loops/benefit.py`: `estimate_benefit(pv, BenefitAssumptions)` -> `BenefitEstimate` (freed room = margin_sigmas * std * std_reduction, capped at the gap to the limit; value per hour), `render_benefit_markdown`; assumptions in `ASSUMPTIONS.md`. Not yet: wiring to datasets/API, deriving std_reduction from loop reports |
| D1 | Screen sketches (datasets, trend viewer, loop overview/detail, tuning wizard, benefit report) | done (draft) | `docs/design/screens.md`; references from a web search (ISA-101, loop monitors, PI Vision, Grafana); owner decided: health score in %, UI languages en + pl + es with pluggable catalogues, light and dark themes (see "Decisions" in the file). Consequence for the API: findings are returned as code + parameters, not prose |
| D2 | Frontend skeleton + trend viewer v1 | done (seen in Edge via Playwright on a 24 h simulator dataset, light and dark) | `frontend/` (Vite, React 18, TS, uPlot, Vitest): i18n (en/pl/es catalogues in `src/locales`), light/dark/system themes (`theme.css` tokens, `useTheme`), `api.ts` client, `trendData.ts`, `StatusChip`, `TopBar`, `TagList`, `TrendPane`, `App` (panes grouped by unit, shared cursor, downsampled badge). `tsc`, 57 Vitest tests and `vite build` pass. Not yet: overview strip, undo zoom, range presets, mode bands, link/unlink per pane, Playwright, CI job |
| D3 | Loop overview and loop detail screens (S3, S4) | done (v1) | backend `loops/src/crosscut_loops/overview.py` (discovery by naming convention, finding codes + params, status, health %, sparkline) + `GET /datasets/{id}/loops`; frontend `LoopsPage`, `LoopsOverview`, `LoopDetail`, `Sparkline`, `findings.ts`, tabs in `App`. Seen in Edge (en, pl) on the nominal and a fault-injected demo dataset. Not yet: per-loop settings from the project file, links from a finding to its time window, tuning/benefit report screens (S5, S6), evidence scatter plot |
| D4 | Tuning report screen (S5) | done (v1) | backend: `loops/tuning_view.py` (model simulation, R² fit verdict, closed-loop step preview, test-window hints), `loops/tuning_payload.py`, `GET /datasets/{id}/loops/{loop}/tuning?start_s&end_s&robustness`; simulator scenario `mill_circuit/step_test` (open-loop OUT steps for identification); frontend `TuningPage`, `SettingsTables`, three numbered sections instead of a click-through wizard. Not yet: manual window drag on a trend, PID/derivative, closed-loop identification, cascade order, benefit report screen (S6) |
| D5 | Benefit report screen (S6) | done (v1) | backend `loops/benefit_payload.py` (default limit when none is given and flagged as such, notes as codes, normal curves now/after), `GET /datasets/{id}/loops/{loop}/benefit`; frontend `BenefitPage` (assumptions marked as such, result, distribution sketch, Markdown export). The estimate itself is the existing C4 library. Not yet: deriving the variability cut from a tuning result, histogram of real data, saving assumptions per loop |
| F1 | Fuzzy Studio backend | done (v1) | new package `fuzzy/` (`model.py` data model + validation, `inference.py` Mamdani with centroid, `library.py` examples + user systems in `<data>/_fuzzy`, `payload.py` what-if and replay), `schemas/fuzzy.schema.json`, API routes `GET /fuzzy`, `GET/PUT /fuzzy/{id}`, `POST /fuzzy/infer`, `POST /datasets/{id}/fuzzy/replay`; example `mill_feed_supervisor`. Tests found a real bug (right shoulder membership 0 at its edge), fixed. Not yet: weighted-average defuzzification, rule matrix view, versions/diff, backtest against operator moves, any write path (stays advisory) |
| F2 | Fuzzy Studio screen | done (v1) | tab Fuzzy: library select + save-as (user copy), membership charts (SVG) with live value marker and term parameter fields, rules as editable sentences with weights/switches/add/delete, what-if sliders with firing bars, aggregated output shape, 'because' line, replay on the chosen dataset (fuzzy output next to the actual tag). Verified in Edge: what-if -8.367 t/h for power 3300 / P80 150 equals the engine. Not yet: dragging handles on the chart, matrix view of rules, versions and diff, auto-calibration, explanations in operator language, tests for the page components (only `fuzzy.ts` is unit-tested) |
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
- Licence: AGPL-3.0-only (changed from Apache-2.0 on 2026-10-13, see ADR 008).
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

- D1/D2: screen sketches in `docs/design/screens.md` (owner decisions: health in %, en/pl/es, light/dark). Node 24 LTS installed portably in `%USERPROFILE%	ools
ode` (winget install was cancelled at the UAC prompt); add it to PATH to use `npm`. Frontend scaffold written by me, all source files and tests by DeepSeek flash via the agentkit CLI (about $0.02), Haiku fixed 3 test bugs. Lesson: MCP `delegate` works only without `verify`; with `--verify "python -m ruff check <existing file>"` the CLI writes the answer to the target file for non-Python code (the check is a no-op).
- D2 browser check: found and fixed (a) wrong tag/dataset field names in the TS client (I had described the API from memory: tags are `id`/`name`, `source` is an object, `time_range.start_utc`), (b) translation keys used by `App` that did not exist in the catalogues, (c) missing layout CSS, (d) uPlot kept stale colours after a theme switch. `playwright-core` added as a dev dependency (uses the installed Edge, no browser download). Run: `python -m crosscut_sim.run --plant mill_circuit --duration 24h --sample-period 10 --out data/`, serve `create_app(Path('data'))` with uvicorn on :8000, `npx vite` in `frontend/` (proxies `/api`).

- D3: tests by DeepSeek flash from my spec (split in two files after the first answer was cut off at 4000 tokens), implementation by DeepSeek flash (tests passed, `agentkit check` failed on function length; Haiku split four functions). I corrected two deviations from my spec: the health score had additive penalties and ignored service/saturation/flatline (now the product in ASSUMPTIONS C5), finding percentages were not rounded. Frontend components by DeepSeek flash; I fixed a broken JSX line and a missing import; Haiku fixed a test helper. CI job `frontend` added (typecheck, Vitest, build).
- Finding: the stiction detector (C2) fires on EVERY loop of the noise-driven mill-circuit simulator (high THD of random variation). The overview therefore reports stiction only when the oscillation detector also finds a sustained cycle (`overview._stiction_suspected`). It can still be wrong (a periodic saturation cycle looks like stiction). C2 needs a data set with real stiction and a better criterion (e.g. PV-OUT shape) before anyone trusts it.
- Loop discovery relies on the naming convention `X`, `X_sp`, `X_out`, `X_mode`; Wood-Berry does not follow it. Needs explicit loop definitions in the project file.

- Fixes for the known problems (session 2, after D3): (1) stiction detector: root cause was the periodicity test (maximum autocorrelation at small lags is always ~1); replaced by the first repeat peak plus a zero-crossing consistency check, sweep results in ASSUMPTIONS; new tests (20 random-wander seeds never flagged, 20 stiction seeds at least 14 found); the overview also excludes cycles explained by saturation. (2) explicit loop definitions: `project.schema.json` loops got name, delay_s, ultimate_period_s, amplitude_limit (schema tests added); `crosscut_loops.project_loops.loops_from_project` (tests by DeepSeek flash, implementation by DeepSeek flash, passed after one fix round); the API reads `<dataset>/project.json` when present (Wood-Berry now analysable). I wrote the detector fix by hand (numerics) and, by mistake, ran `ruff format` over unrelated files; reverted those four.
- Still open from the D3 list: link from a finding to its time window, remaining trend-viewer features, validation of C2 on real stiction data.
- D4 (tuning): `tuning_view.py` written by hand (array numerics), tests by DeepSeek flash (one fix round), `tuning_payload.py` by hand with Haiku splitting functions for the style gate, SettingsTables/TuningPage by DeepSeek flash (passed first time; I removed a wrong unit label). Verified in Edge on a step-test dataset: windows found automatically, models R² 0.72 to 0.91, step preview plausible. The model is identified on OUT-to-PV in MAN; closed-loop (AUTO) windows only get a warning.
- D5 (benefit): `benefit_payload.py` by hand (glue), page by DeepSeek flash (first try; I fixed the grid layout after the first screenshot). Principle kept: no number without its assumptions next to it, and a placeholder limit is flagged in red.
- CI was red from run #15 (OPC UA read connector) to #20 and I had not looked after pushing. Cause, reproduced in WSL Ubuntu (Python 3.14, venv `~/ci-venv`, no `gh` CLI on this machine): `test_opcua_import.read_column` turned nanosecond timestamps into Python objects (`to_pylist`), which fails when a Linux clock reading is not a whole microsecond. Fixed by selecting in Arrow. Lesson: after every push check the CI result (or run the suite in WSL first); the new `frontend` job has not been seen green yet.
- F1 (fuzzy backend): engine and payload written by hand (array numerics), tests by DeepSeek flash in two files (the first single request was cut off and the router spent $0.027 on Gemini before reporting it; lesson: split test requests above ~2500 tokens of expected output), Haiku fixed the style gates. API route builder `build_fuzzy_router` is one 49-line closure (same pattern as `create_app`), accepted.
- F2 (fuzzy screen): types, membership port, API client and texts by me; seven components by DeepSeek flash/codestral via the CLI. First attempt failed to compile (invented field names such as `term.id`, `clause.term`) because I forgot to pass `frontend/src/fuzzy.ts` and `api.ts` as `--files` context: ALWAYS attach the contract files when the prompt refers to types. Second attempt compiled except four unused names. Text inside a non-uniformly scaled SVG is stretched: axis numbers are HTML now.

- Fuzzy Studio, versions and diff (backend): `fuzzy/versions.py` (snapshot per save in `<data>/_fuzzy/_history/<id>/`, list/load, `diff_documents` returns change codes), routes `GET /fuzzy/{id}/versions`, `GET /fuzzy/{id}/versions/{v}`, `POST /fuzzy/diff`. Tests by DeepSeek flash (the implementation failed two verify rounds on one wrong test expectation, kept by hand), Haiku fixed style. Added `py.typed` to `loops` and `fuzzy`: this removed all mypy errors in `api/src` (they came from untyped imports). Not yet: versions/diff screen, rule matrix view, backtest against operator moves (output `feed_change` is a delta of the SP tag).
- Fuzzy Studio, versions screen: `VersionsPanel` (pick a snapshot, see the diff against the edited rules, load it), `fuzzyDiff.ts` (change codes to sentences, en/pl/es keys `fuzzy.change.*`, `fuzzy.field.*`, `fuzzy.versions.*`), API client functions. The delegated panel compiled and passed all tests but did not work (diff never started); rewritten by hand and verified in Edge. Lesson: no test renders the page components, so check every delegated component in the browser. A stale dev server from an earlier session can hold port 8000 and serve old routes: check `netstat` before trusting a browser check.

- Clean-code pass (session 2). `agentkit check` found 132 findings in 46 Python files (53 functions too long, 43 meaningless names, 17 missing docstrings, 13 too many parameters, 6 deep nesting); the gate covers Python only, so C++ (`core/`) and TypeScript (`frontend/`) were never checked and still need a manual review (e.g. `fopdt.cpp`: names `a_`, `y_`, `n`, no comment on the discretisation formula, 5 constructor parameters). A first attempt with Haiku subagents was wasteful (one agent misread the task, six were stopped); replaced by `tools/refactor_loop.py`: for each finding it sends ONE function to DeepSeek via `agentkit delegate`, keeps the result only if the file parses, the finding count drops and the package tests pass, otherwise restores the file (second try with `--escalate`). It fixes the easy majority; big functions (50-100 lines), builders with many parameters and changes that need callers updated are skipped and remain manual work (the tool does not log why a fix was rejected yet). Lesson: do not hand a Claude subagent a job that is a loop of "function -> cheap model -> test"; build the loop.
- Result of the Python pass: gate findings 132 -> 50 (remaining ones are the big functions listed by `agentkit check`, mostly the plant `reset`/`step`/tag-catalog builders, the route-builder closures in `api/app.py`, and functions whose parameters need caller changes); `ruff`, `mypy` (sim, loops, fuzzy, api) and the whole test suite pass. The tool at first accepted fixes without running ruff/mypy, which let in long lines, missing annotations, a removed import (`Axes`) and a duplicate stub definition; it now counts ruff E501 and mypy errors as findings too. Haiku (one small agent) wrapped the last long lines and fixed types; I checked the result myself. Still to do: the 50 remaining findings by hand (with context), C++ and TypeScript review, and a note in the tool about why a fix was rejected.
- C++ review (`core/`): renamed members and locals so they reveal intent (`decay_per_step_`, `output_`, `delayed_inputs_`, `oldest_input_index_`, `input`), extracted the parameter check, commented the exact-discretisation step, named the test tolerances, spelled out test variables. Interface unchanged (five parameters mirror the Python reference; pybind keyword names `y0`/`u` kept on purpose). Verified locally afterwards with the user-level toolchain in `~/tools/cpp` (`build_core.cmd`, no admin): 4 C++ tests with -Werror and 4 parity tests pass. A stricter local run (`build_strict.cmd`: -Wconversion -Wsign-conversion -Wshadow -Wold-style-cast as errors on the library) is also clean. Still only in CI: real MSVC /W4 /WX, GCC, and the ASan/UBSan job (zig does not appear to link the ASan runtime).

- Explanatory comments pass (session 2). `tools/comment_loop.py` asked DeepSeek flash to add teaching comments (model, formula, units, data structure) to 296 Python functions across all packages, one function per call; a result is kept only if the syntax tree without docstrings is identical (no code changed), ruff is not worse and the package tests pass. The comments are NOT reviewed yet: the model sees one function, not the project, and tests cannot catch a wrong comment. Known error: `sim/.../pid.py` says `td_filter_n` is "how many samples the filter averages over" while its docstring says the filter time constant is `Td / td_filter_n` (so it is a filter coefficient, not a sample count): fix the comment. Review order (numerics first): `sim/.../{pid,core,disturbances,faults}.py`, `sim/.../plants/*.py`, `loops/.../{stiction,identification,tuning_rules,tuning_view,metrics,benefit}.py`, `fuzzy/.../inference.py`, then the rest; delete comments that only restate the code. Also changed agentkit `codecheck`: function length now counts CODE lines only (blank lines, comments and the docstring are free), otherwise comments pushed 289 functions over the limit; gate findings now 48.
- State at the end of session 2. Done: stage 0, stage 1 screens D1-D5, Fuzzy Studio v1 + versions/diff (backend and screen), clean-code pass (names, long functions), C++ core readable and verified locally (`~/tools/cpp/build_core.cmd`), comments pass for Python. Pending, in this order: (1) review the generated comments (list above); (2) the 48 remaining gate findings by hand (big plant `reset`/`step`/tag-catalog builders, route-builder closures in `api/app.py`, builders with many parameters); (3) comments and the same clean-code pass for TypeScript (`frontend/`), run one worker per directory in parallel and verify unchanged code by comparing `esbuild --minify` output before and after; (4) Fuzzy Studio: rule matrix view and backtest against operator moves (output `feed_change` is a delta of the SP tag); (5) Modules map page; (6) open items below. Check the CI result of the last pushes (jobs `cpp`, `frontend`) first: there is no `gh` on this machine.

### 2026-10-12, session 3
- `gh` was missing: a portable build is installed in `%USERPROFILE%/tools/gh/bin` (also on the user PATH) and logged in as `msurun`. All CI runs up to the comments commit 2ea3b07 are green, jobs `cpp` and `frontend` included. `gh run list` works now.
- Comment review: the generated comments were partly wrong or only restated the code because the model saw one function. New tool `tools/comment_review.py`: a model sees the WHOLE file and returns edits of whole comment blocks (delete / replace). An edit touches pure comment lines only, partial blocks are rejected, and a chunk is kept only if the code fingerprint is unchanged, ruff is not worse and the package tests pass. Every accepted edit is logged with the model's reason (JSON lines) for a human audit. A trial on `pid.py` found the known `td_filter_n` error.
- Result of the comment review (8 workers, one per package, DeepSeek with `--escalate`): 482 edits accepted (353 replacements, 129 deletions), about 60 rejected (partial blocks or failed checks); 42 comment lines wrapped afterwards (the tool counted 95 characters without the indentation: fix the limit in the tool). Many replacements are "kept as is" rewrites (noise, harmless). Three wrong comments in `pid.py` (sign of the error, sign of the derivative term, `td_filter_n`) were corrected by hand. The edits are NOT fully audited: spot checks of `tuning_view`, `identification` and `pid` were correct; the log of every edit with the model's reason was in the session temp directory (not kept). Ruff and all tests pass.
- Next (in this order): (1) the 48 remaining gate findings by hand; (2) TypeScript in `frontend/`: comments and clean-code review, one worker per directory; (3) Fuzzy Studio rule matrix and backtest; (4) modules map page; (5) open items. For the portfolio goal prefer depth over breadth: finish and document 2 or 3 modules well (loop monitoring, tuning report, Fuzzy Studio), then a 5-minute demo in the README. Before the repository becomes public: trademark check, no employer traces, written confirmation that the project does not conflict with the employment contract.
- Style gate, second pass (`tools/refactor_loop.py`, 8 workers, one per package, tests included): findings 190 -> 56. The loop broke three things that I fixed by hand: a missing `Scenario` import in a test, three untyped `loop` parameters in `mill_circuit.py`, and about 40 long lines (comments wrapped by script, 16 docstrings shortened by a Haiku agent). Remaining 56 are the big functions and builders with many parameters, which need callers updated: `api/app.py` (`create_app` 198 lines, three 5-parameter routes), `fuzzy_routes.build_fuzzy_router`, `manifest.write_artifact` (10 parameters), `csv_import.import_csv` (79 lines), `opcua/collector.collect` (85 lines, 12 parameters), `opcua/server.start`, `sim/dataset.record` and `write_dataset` (11 parameters), `sim/run.main`, `wood_berry.reset/step`, `scenarios._build_mill_circuit_scenario`, `pid.__init__/update`; plus a few tests and `tools/`. Do these with the callers in context, one function per delegation, with `--files` for the callers.
- Rule added to `CLAUDE.md` (9): teaching comments are written together with the code, with whole-file context, not in a later pass.
- File headers: every Python file already had a module docstring; 7 TypeScript and 3 C++ files got a `//` header saying what the file does (comments only, `tsc`, 135 Vitest tests and the C++ build with parity test pass). Rule 10 added to `CLAUDE.md`. The style gate checks it for Python only.

### 2026-10-12, session 4
- This machine has no Python >= 3.11, no WSL and no project venv (only Python 3.10 in `anaconda3`), so tests and ruff could not be run here. ForemanKit (renamed from AgentKit) runs from `ForemanKit/.venv`; `foremankit.cli check` takes files, not directories.
- Style gate, dataset module: `record` (11 parameters, 57 lines) and `write_dataset` (11 parameters, 69 lines) split into small helpers and grouped into `RunInfo`, `Samples` and `DatasetInfo` dataclasses in `sim/dataset.py`. Callers updated: three connectors, the OPC UA collector, `sim/run.py`, `exp00`, two test files. Python 3.12 venv at `~/crosscut-venv` (WSL is being installed by the owner). Full suite, ruff and mypy pass.
- Style gate cleared (56 -> 0 findings, `foremankit check` clean on all Python files). Five Sonnet subagents in parallel, one per package group (sim; opcua; connectors; api+artifacts+loops; tests+tools), I did `dataset.py` and the test-env setup. Signature changes (all callers updated): `record(plant, scenario, out_dir, RunInfo)`, `write_dataset(out_dir, Samples, DatasetInfo)`, `collect(endpoint, out_dir, CollectorConfig)`, `ServerConfig`, `import_sql(db, query, ImportTarget)`, `import_opcua(endpoint, nodes, ImportTarget, PollPlan)`, `write_artifact(..., ArtifactMetadata)`, `PID(PidTuning, dt_s, OutputLimits, direct)`, `OrnsteinUhlenbeck(OuShape, dt_s, rng)`, `random_binary_events(tag_id, BinarySignal, seed)`; `Fopdt` lost the unused `y0`; `Envelope.t` -> `timestamps` (JSON key `t` unchanged). `create_app` and `build_fuzzy_router` are now small wirings of endpoint classes; URLs and payloads unchanged.
- Real bug found by the agents: `fuzzy.versions.save_version` used a microsecond timestamp as the version id, and the Windows clock is coarse, so two quick saves overwrote each other (flaky `test_every_save_adds_a_version...`). It now moves the stamp forward 1 us until the id is free. Also 2 mypy errors in `connectors/messy.py` fixed.
- Test environment on this machine: Python 3.12 venv `~/crosscut-venv` (Windows) and WSL Ubuntu with Python 3.14 venv `~/ci-venv` (`wsl ... ~/ci-venv/bin/python -m pytest`). State: 534 passed, 1 skipped on both; ruff and mypy clean. Not committed yet.
- Owner's direction (2026-10-13): go module by module, simplest first: loop health monitoring and PID tuning ("module 1"). The simulator must run in REAL TIME, show the reaction to our actions, and be wired to a DCS simulation that we connect to over OPC UA. Existing base: `opcua/server.py` (PlantServer: real-time with `speed`, all tags as Double nodes, client writes forwarded to the plant, heartbeat watchdog that returns CAS loops to AUTO). Open points for module 1: stiction as a fault with ground truth, closed-loop identification, finding -> time window link, live trend from OPC, second plant (boiler drum suggested), README demo.

### 2026-10-13, module 1 start (loop monitoring and tuning, real-time simulator)
- Stiction as a plant fault: `sim/valve.py` (`StictionSpec(deadband, jump)`, `StictionValve.move`, same stick-slip rule as the detector's test helper) is applied between the PID output and the actuator of every `mill_circuit` loop. Scenario params `stiction_band_<loop>` and `stiction_jump_<loop>` (% of travel, `<loop>` = `hpgr_press`, `mill_feed`, `cyc_water`); `MillCircuitPlant.ground_truth()` lists the loops that have it. Tests first (`sim/tests/test_valve.py`, 8), full suite, ruff, mypy and the style gate pass.
- Validation of `detect_stiction` on the simulator FAILED to confirm: on `hpgr_press` with band 2 to 8 % the verdict is always "inconclusive" ("Signal is not periodic"), with or without noise. What was seen: stiction does change the loop (OUT std 0.19 -> 1.58 with all noise on; period lengthens with the band), but the valve stays inside a noisy limit cycle, not a clean sawtooth. Bands 4 % and 8 % gave identical results in a low-noise run (OUT std 0.402, period 75 s), which looks like the cycle being bounded by something other than the valve (PID output limits or the actuator lag): check that before trusting any number. Next: look at PV/OUT plots for one stiction run, find a loop and a scenario where the stiction cycle is visible, and decide whether the fix belongs in the simulator (loop dynamics) or in the detector (noise-robust criterion).
- Not done yet: ground truth in the dataset (the `source` block of `dataset.schema.json` forbids extra keys, so a schema change with tests is needed), real-time run against the OPC UA server with the faults, second plant.
- Ground truth in the dataset (done): `dataset.schema.json` `source.ground_truth` (optional, loop -> {fault parameter: number}); `record` copies `plant.ground_truth()` into it when non-empty. Tests in `tests/test_schemas.py` and `sim/tests/test_dataset.py`. Next: real-time run against the OPC UA server with faults, then validation of `detect_stiction` on a cleaner stick-slip case. mypy on `sim` still reports 9 older errors (generic `dict` in test_dataset.py and others).
- Real-time run with a fault (done): mill-circuit scenario `stiction` (HPGR press valve, band 3 %, jump 1.5 %, operator off) in `scenarios.py`; `opcua/tests/test_server_faults.py` runs it on `PlantServer` and checks that an asyncua client sees the loop react to an SP step and sees no ground-truth node. Run it: `python -m crosscut_opcua.server --plant mill_circuit --scenario stiction --speed 60`. Next: validate `detect_stiction` on this scenario.
- Validation of `detect_stiction` (done, `experiments/exp01_stiction_validation/`): script by DeepSeek flash ($0.011, the verify step used a Python without ruff and restored the file; I took the first answer from `.agent-out` and fixed two things by hand). Root cause of the old "always inconclusive": a loop at its setpoint never leaves the valve deadband; with one SP step the loop hunts. Result: low noise and band >= 4 % -> "stiction" 5/5; healthy valve never flagged; band 2 % and full noise -> "inconclusive". Still open: a detector that copes with noise and small bands; real stiction data.

## Work plan, module 1 (agreed 2026-10-13, run without per-step approval)

Rules for the whole block: tests first; gates before every commit (`ruff`, `mypy` on touched packages, `pytest`, `foremankit check`);
one commit per step; method added to `docs/PROVENANCE.md` before it is implemented; delegate tests and bulk code, keep integration;
stop and ask only for: a decision between designs that changes a public contract, a paid call above $0.10, or two failed attempts
at the same step (then log the state and move on to the next independent step).

| Step | Work | Done when |
|---|---|---|
| P1 | Stiction detector robust to noise and small bands: sweep where `exp01` fails, `opus-advisor` for the approach (e.g. use OUT-PV relation), PROVENANCE row, tests, implementation | `exp01` at both noise levels: healthy valve 0 false alarms in 20 seeds, band >= 4 % found in >= 4 of 5; result for band 2 % reported honestly |
| P2 | Explicit loop definitions in the project file (schema + tests), overview uses them, Wood-Berry runs through loop monitoring | Wood-Berry loops listed with health and findings in the API |
| P3 | Frontend: link from a finding to its time window in the trend viewer (Vitest + check in Edge) | click on a finding zooms the trend |
| P4 | Live demo: `PlantServer` with `stiction` scenario plus a scripted asyncua client (SP steps, prints loop health live); short guide for connecting UaExpert | script runs end to end; guide in `docs/` |
| P5 | Module 1 write-up (README section, results, limits), log update | docs consistent with code |

P1, P2 and P3 touch different packages and run in parallel (worker per package); P4 waits for P1, P5 for all.
Owner-only items: test with UaExpert, review of ADR 008 reasons.

### P6: PID tuning proven in closed loop (added to the module 1 plan, 2026-10-13)

State: identification of FOPDT models from step windows, SIMC and AMIGO rules, DCS form conversions, report and `TuningPage` exist
and are tested against synthetic models. Missing: proof that the recommended settings really improve a loop, and a plant that can be
mistuned. The mill-circuit PID gains are fixed in code (`kc` from the loop spec, `ti_s=60`), so nothing can be retuned yet.
Tuning stays advisory: no automatic writes to a DCS before the write-path suite (V5) exists.

| Step | Work | Done when |
|---|---|---|
| P6.1 | Plant side: scenario params `kc_<loop>` and `ti_s_<loop>` for the three mill loops (defaults = today's values, so nothing existing changes); new scenario `detuned` (gains too aggressive or too slow) | tests: defaults reproduce today's data (same sha256), a detuned scenario measurably worsens IAE |
| P6.2 | Identification accuracy vs ground truth: step-test data from `step_test` over noise levels and seeds; compare identified gain, delay and time constant with `true_gain` and the plant's real dynamics; table in `experiments/exp02_identification_accuracy/` | table with error percentiles; limits written down (known: closed loop with the operator on gives ~0 gain, see exp00) |
| P6.3 | Closed-loop validation `experiments/exp03_retune/`: detuned loop -> step test -> tuning report -> apply SIMC (and AMIGO) -> SP-step run before and after, 5 seeds x 3 loops; metrics IAE, overshoot, settling time, loop health from the overview | retuned loop: IAE lower by >= 20 % on at least 2 of 3 loops in >= 4 of 5 seeds, no instability; failures listed honestly |
| P6.4 | Guards: tuning refused when the stiction verdict is "stiction" (exists) or when R^2 of the model is low; test that a sticking valve gives a blocked report instead of settings | tests for both refusals, wording of the reasons checked |
| P6.5 | Benefit link: feed the before/after variance of the retuned loop into the benefit report (D5) with its assumptions shown | benefit page shows a number only with assumptions next to it |
| P6.6 | Live demo (extends P4): `PlantServer` with `detuned`, the scripted client records a step test, calls the tuning API, restarts the scenario with the proposed gains and prints health before and after | script runs end to end |
| P6.7 | A7 (open): DCS form conversions checked against vendor documentation | OWNER: supply the documents or confirm which vendors; until then A7 stays open |

Order: P6.1 first (everything depends on it), then P6.2 and P6.4 in parallel, P6.3 after both, P6.5 and P6.6 last.
Acceptance targets are set before the experiment is run; if P6.3 misses them the finding is logged as it is, not tuned away.

### P7: final review (requested by the owner, runs after P1 to P6 are done)
Review of everything changed in this plan for clean code (`foremankit check`, naming, function size, duplication, comments with whole-file context),
possible bugs (edge cases, error handling at boundaries, flaky or slow tests, CRLF/LF and Windows-vs-Linux differences, CI status via `gh run list`),
and shortcomings (open assumptions, missing tests, documentation drift, the 9 older mypy errors in `sim`). Use `foremankit review --diff` (different source
than the author) and check each finding against the code before accepting it. Result: a to-do list in this log, split into must-fix, should-fix and ideas, and the same list in the final chat summary.
- P6.1 done: scenario params `kc_<loop>` / `ti_s_<loop>` (default = old gains, so existing data is unchanged), `DEFAULT_KC` exported from `mill_circuit.py`, scenario `detuned` (kc x0.25, ti 300 s). Tests `sim/tests/test_mill_tuning.py` by DeepSeek flash ($0.002), style/mypy fixes by a Haiku agent.
