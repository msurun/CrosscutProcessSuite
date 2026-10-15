# Implementation log

**Read this first in every new session, then `docs/HANDOFF.md` (owner to-do for when the owner is at the computer, and next steps the assistant can do alone).** It records what is done, what is pending and in which order.
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
| V1 | Fault-injection layer for the simulators (sensor freeze/spike/drift/bad quality, stiction, jitter, dropouts, mode flips) | 1 | done except stiction: `faults.py` (`FaultyPlant`: freeze, drift, spike, bad_quality, dropout), `timing_faults.py` (timestamp jitter `jitter_timestamps`/`jitter_samples`, mode flips `ModeFlip` + `mode_flip_events` as scenario `Event`s), experiment `experiments/exp05_timing_faults/`. Stiction in the plant: see the valve model (`valve.py`) |
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
| C3 | PID tuning report | done (library) | `loops/src/crosscut_loops/{tuning_rules,identification,tuning_report}.py`: FOPDT fit (ARX + delay scan), SIMC and AMIGO PI, robustness slider, DCS parameter forms, Markdown report blocked when stiction is suspected. Part 2 (2026-10-14): `tuning_pid.py` (AMIGO PID, improved SIMC PI, derivative advice, ideal/series conversion), `identification_cl.py` (setpoint-instrument closed-loop fit), `cascade.py` (order and time-scale separation), experiments exp06-exp08; PID shown in the report and the vendor tags. Not yet: frontend view of the new report parts (no Node here), cascade and closed-loop fits are not wired into the API |
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
| P6.7 | A7 (open): DCS form conversions checked against vendor documentation | Scope fixed by the owner (2026-10-14): ABB and Siemens only for now. Owner supplies the vendor documents (or I cite public manuals and mark each form as unverified until the owner confirms); other vendors later |

Order: P6.1 first (everything depends on it), then P6.2 and P6.4 in parallel, P6.3 after both, P6.5 and P6.6 last.
Acceptance targets are set before the experiment is run; if P6.3 misses them the finding is logged as it is, not tuned away.

### P7: final review (requested by the owner, runs after P1 to P6 are done)
Review of everything changed in this plan for clean code (`foremankit check`, naming, function size, duplication, comments with whole-file context),
possible bugs (edge cases, error handling at boundaries, flaky or slow tests, CRLF/LF and Windows-vs-Linux differences, CI status via `gh run list`),
and shortcomings (open assumptions, missing tests, documentation drift, the 9 older mypy errors in `sim`). Use `foremankit review --diff` (different source
than the author) and check each finding against the code before accepting it. Result: a to-do list in this log, split into must-fix, should-fix and ideas, and the same list in the final chat summary.
- P6.1 done: scenario params `kc_<loop>` / `ti_s_<loop>` (default = old gains, so existing data is unchanged), `DEFAULT_KC` exported from `mill_circuit.py`, scenario `detuned` (kc x0.25, ti 300 s). Tests `sim/tests/test_mill_tuning.py` by DeepSeek flash ($0.002), style/mypy fixes by a Haiku agent.
- P2 done (narrowed): explicit loop definitions already existed (`project.json` next to a dataset, read by the API), so the work was on the simulator side: `sim/loop_definitions.py` (`loop_definitions`, `write_project_file`), the runner writes `project.json` for every run; Wood-Berry now shows "Top composition" and "Bottom composition" with health in the API. Mill-circuit names equal the ids because tuning URLs address a loop by name. Tests by DeepSeek flash ($0.001).
- P1 plan (from opus-advisor, to implement next): use OUT instead of PV. Method: He, Wang, Pottmann, Qin (2007) curve fitting, Ind. Eng. Chem. Res. 46:4549 (verify citation): fit each OUT half-cycle with a half-sine and a triangle, SI = MSE_sine / (MSE_sine + MSE_triangle), median over half-cycles; stiction if OUT is periodic, >= 6 cycles and SI > 0.6, no stiction if SI < 0.4, else inconclusive. Thresholds frozen BEFORE the run; seeds 1-10 development, 11-20 held-out; 20 seeds for positives and negatives; negative classes reported separately: nominal wander, aggressive tuning (Kc x3, Ti/3), sinusoidal load disturbance 900-1500 s, square-wave load (adversarial), setpoint step only. Not applicable to integrating plants. If band 4 % gives OUT amplitude below ~3 sigma at full noise, relax the target to band >= 6 % or amplitude >= 3 sigma.
- P1 done: `detect_stiction` now judges the shape of OUT (`loops/stiction_curvefit.py`, He et al. 2007; thresholds 0.6/0.4 frozen), the old PV method is kept as `detect_stiction_from_pv` for comparison. Needs >= 6 limit cycles (legacy tests use 20000-sample records). Acceptance run (`experiments/exp01_stiction_validation/acceptance.py`, 20 seeds, dev/held-out split, negative classes reported separately): low noise band >= 4 % found 10/10; full noise only band 8 % (8/10); healthy classes (wander, aggressive tuning, sine forcing) 0 false alarms in 10; square-wave forcing 10/10 FALSE alarms (known limit). Tests by DeepSeek flash, the acceptance script by DeepSeek flash (it had a dict-key bug that hid the low-noise rows, found by reading the report), style fixes by Haiku. Open: the PV-based code could be removed once nothing compares against it; the monitor docs still describe the old THD method; real-data validation. mypy: sim tests have 9 older errors.
- Owner decisions 2026-10-14: (1) A7 / P6.7 limited to ABB and Siemens PID forms. (2) NOTE FOR LATER: test the OPC UA server with UaExpert (external client); only the owner can do it, the guide comes with P4. (3) NOTE: ADR 008 (AGPL-3.0) reasons await the owner's review; ForemanKit work is paused. (4) Work P3, P4, P5, P6.x, then P7 without further approval until the plan is closed.
- P6.2 done: `experiments/exp02_identification_accuracy/` (script by Gemini flash after DeepSeek was cut off; I fixed the reference gain: it used a window that holds both the up-step and the restore, now it uses the scripted step times). Result, 10 seeds, step 8 % OUT, open loop: low noise gain exact, tau within 1.5 %; full noise gain median error 5-7 % (p90 up to 21 %), tau median 8-49 % (p90 130-490 %), relative delay error not meaningful (reference delay is one sample). Table and limits in `results/identification_accuracy.md`.
- P6.4 done: `build_tuning_report` withholds the settings (blocked_reason "poor model fit ...", payload `blocked_code` "poor_fit", texts en/es/pl) when R squared of the model is below `FAIR_R_SQUARED` (0.5); a stiction block keeps priority and the poor-fit sentence goes to the notes. Tests `loops/tests/test_tuning_guards.py`. Note: `identify_fopdt` has its own floor (MIN_FIT_QUALITY), so poor_fit only appears when that passes but the replayed fit is bad (sd 2.0 test case, R squared about 0).
- P3 part 1 done: findings of kind manual, saturated and flatline carry `window_s` = [start_s, end_s] (longest stretch, `loops/finding_windows.py`); findings about the whole record carry no key. Frontend part follows.
- Environment note: this PC had no Python env for the repo; gates run from a venv in the session scratchpad (`pip install -r requirements-dev.txt`, py -3.12).
- P3 done: in the loop detail a finding with `window_s` shows a "Show in trend" link that zooms both trend panes to that stretch (`TrendPane` prop `xRange`, helper `windowToRange`, en/es/pl texts); "Show whole record" resets. Vitest 141 tests, `tsc` and `vite build` pass; seen in Edge via playwright-core on the `step_test` dataset (manual finding, 97 %). Node came from the pip package `nodejs-wheel-binaries` in the scratch venv (no Node on this PC). Not done: windows for oscillation, stiction and poor performance (they describe the whole record).
- P6.3 done: `experiments/exp03_retune/` (script by Gemini flash; I fixed one wrong DataFrame call). Frozen targets met: PASS, 5 of 5 seeds; 14 of 15 loop runs improved (IAE 70-93 % lower with SIMC at robustness 0.5, AMIGO about the same), the 15th (seed 5, cyc_water) was blocked by the P6.4 poor-fit guard (R squared -1.18). Honest caveats are in `results/retune_validation.md` (settling-time column is noise-limited, overshoot of mill_feed 58-67 %, only setpoint steps).
- P6.5 done (API side): `BenefitRequest.std_before/std_after` (measured PV spread before/after a retune) replace the assumed `std_reduction`; the payload echoes `std_reduction_source` ("assumed" | "retune_measured") with both numbers; API query params `std_before`, `std_after`. The benefit page already marks every input as an assumption; it does not yet have fields for the measured pair (the demo script P6.6 passes them through the API).
- P4 + P6.6 done: `opcua/examples/live_demo.py` (scripted asyncua client on the stiction plant, prints loop health per simulated hour; seen: 36 % -> 21 %, verdict "stiction" at 4 h with a 12 % band) and `opcua/examples/retune_demo.py` (detuned loop -> open-loop step test over OPC UA -> SIMC gains -> same setpoint step; seen: health 48 % -> 100 %, error integral 1566 -> 75). Guide with the UaExpert steps in `docs/LIVE_DEMO.md`. Finding on the way: the 8 % band of the exp01 acceptance is detected in only 2 of 6 seeds in this demo set-up (seeds 1-6, full noise), so the demo uses 12 %; sampling slower than about 15 s hides stiction (30 samples per half cycle are needed). Helper tests in `opcua/tests/test_examples.py`. The UaExpert connection itself is NOT tested (owner).
- P5 done: README has a "Module 1" section with results and limits; layout table lists loops, api, frontend, connectors, fuzzy. Style gate (`foremankit check`) clean on all new Python files (fixes by Haiku agents), the 9 older mypy errors in `sim` tests are fixed. Found by a browser check with a narrow window: `setData` reset the zoom, so the `xRange` effect now runs after the data effect (seen: 10:00-10:30 on both panes).

### P7 final review (2026-10-14)
Tools: `foremankit check` clean on all new Python files; ruff, mypy (sim, loops, api) and pytest green; reviewer = DeepSeek flash through `delegate` (the `foremankit review` CLI had no provider: no keys in the shell, local LLM servers off). Each finding checked against the code.
- Fixed: NaN/inf `std_before`/`std_after` leaked into the benefit estimate (test added); docstrings copied from another domain ("count-rate", "fab tool") in `tuning_report.py`; `SIDE_ANY_OTHER_VALUE` and "three sigma" drift in `benefit_payload.py`; the poor-fit guard wording (settings stay in the report like with the stiction block; the screen hides them).
- Not a defect: tie-break of the longest run, NaN in flat runs, the padding trick of `_longest_true_run`.
- **Must-fix open:** none.
- **Should-fix:** (1) `finding_windows` and `overview` assume an output range of 0-100 %, a 4-20 mA tag would report wrong saturation (per-loop range exists in `LoopTags`, not passed on); (2) `LoopDetail.pickSeries` throws during render when the backend omits a tag, show the error state instead; (3) `TrendPane` `onZoom` can fire with undefined bounds on an empty series (older code); (4) A7 ABB/Siemens PI forms against vendor documents (owner supplies documents); (5) `exp03`: overshoot of mill_feed 58-67 % is unexplained, settling-time column is noise-limited.
- **Ideas:** `_sparkline` drops tail samples; `health_percent` hides `service_factor > 1`; `NOTE_CODES[...]` raises KeyError for a future note code; windows for oscillation/stiction (whole-record findings); fields for measured std on the benefit page; `foremankit review` needs keys in the shell.
- **Owner-only:** UaExpert check (`docs/LIVE_DEMO.md`), review of ADR 008, vendor documents for A7. CI status could not be read (no `gh` here): check the last pushes on GitHub.

### To-do after P7 (2026-10-14, later)
- Done: `finding_windows` takes `out_low`/`out_high` (keyword, default 0-100) and saturation is computed against it; NOT wired yet: `LoopTags` has no output range (only the PV range `eng_min/eng_max`), so `overview` still uses the defaults. Needs a decision: add optional `out_low/out_high` to `LoopTags` and `project.json` (schema change). `_sparkline` keeps the tail samples; `health_percent` logs a warning when `service_factor > 1`; unknown note codes no longer raise KeyError.
- Done: `LoopDetail` shows the error text instead of throwing when the backend omits a tag (test); `TrendPane` no longer calls `onZoom` with undefined bounds on an empty series (`visibleRange`, tests); benefit page has optional fields "std before / after a retune" and shows the measured source (tests).
- Overshoot of mill_feed explained (`experiments/exp03_retune/overshoot_diagnosis.md`): the 58-67 % was sensor noise in the raw maximum (PV sd about 0.8 on a step of 5), not loop behaviour. exp03 now measures overshoot and settling on a 60 s moving average: the verdict is unchanged (PASS 5/5), mill_feed overshoot median is about 9 %. Loop interaction is excluded (variants A and B are identical: the mill_feed loop does not depend on the other loops' gains in this plant). Variants C (noise-free identification, median 13.9 %) and D (robustness 1.0, 14.8 %) are not better than A (9.4 %); with 5 seeds the differences are small and not explained, so do not read them as an effect. Known: the diagnosis script shows detuned numbers for a blocked seed instead of a marker (did not occur).
- Still open: wire the output range (above); windows for whole-record findings; items needing the owner (UaExpert, ADR 008, ABB/Siemens documents for A7).

### Open points closed (2026-10-14, evening)
- Output range: `LoopTags.out_low/out_high` come from the OUT tag's own `eng_min/eng_max` (no change to `project.json` or its schema: the tag list already carries them). Saturation, `default_settings` and finding windows use them; no range = 0-100 as before. Tests `loops/tests/test_output_range.py` (4-20 mA loop).
- Whole-record findings (oscillating, poorPerformance, stiction) now carry an example window: `loops/example_windows.py` picks 6 oscillation periods (or a quarter of the record) with the largest mean |PV - SP|. Findings with a window have `window_kind` "cause" or "example"; the UI says "Show in trend" or "Show an example in trend" (en/es/pl). Seen in Edge (link zooms both panes). Limit: "largest error" is a heuristic for what is most visible, not a proof of where the problem is.
- Still open (owner): UaExpert check, ADR 008 review, ABB/Siemens documents for A7. Plan item for later: real or public data (V3, V6).

### Session 2026-10-14 (night): handoff steps 1-4
- Environment: `.venv/` recreated from `requirements-dev.txt` (Python 3.12); no Node.js, so the frontend gates (tsc, vitest, vite) were NOT run; nothing in `frontend/` changed.
- Step 1 (stiction band): the "8 of 10 vs 2 of 6" gap is seed-set noise. Band 8 %, full noise, seeds 1-20: 14 of 20 (70 %, Wilson 95 % about 48-85 %); seeds 1-6 give 2 of 6, 11-20 give 8 of 10. With the operator moving the loop: 0 of 20. Written in `experiments/exp01_stiction_validation/README.md`; README claim updated.
- Step 2 (V3): `connectors/flotation_public.py` + `experiments/exp04_public_flotation/` on the CC0 Kaggle flotation data (licence read from the Kaggle API, PROVENANCE row added). No setpoint/OUT in the data, so no stiction or accuracy claim. The loader check was frozen at "lab columns flat > 99 %": FAILED for the two concentrate columns because the file holds linearly interpolated lab values in 310 hours; reported, threshold kept. The oscillation flag is on for 17 of 19 columns (no setpoint, untuned limit): not informative.
- Step 3 (V6): `docs/customer_kit/` (README, EXPORT_GUIDE, REPORT_TEMPLATE), `connectors/anonymise.py` (renames tags, per-group affine map, time shift), `loops/readiness.py` (duration, sample period, regularity, missing, stuck, tag roles). Test `loops/tests/test_anonymised_findings.py`: same findings, same stiction verdict and health on the anonymised stiction recording. Not tried on real customer data.
- Step 4 (connectors): (a) CSV: local times repeated at DST fall-back are now kept (second pass = file order, `n_dst_repeats_resolved`); before, one hour was silently dropped as duplicates. (b) CSV: units from `Name [unit]` / `Name (unit)` headers go to the tags document. (c) `csv_long.import_csv_long` (long format, reuses the SQL pivot). (d) SQL: `import_sql_connection` / `fetch_rows` take any DB-API connection (pyodbc for ODBC); tested with sqlite and a fake driver only, NOT with a real ODBC driver. (e) OPC UA: node ids by namespace URI (`nsu=<uri>;s=Tag`), and reconnect after a round with no usable value when the session is dead (test restarts the server mid-import; fails without the reconnect code). NOT done: OPC UA subscriptions; DST handling in the SQL importer's naive timestamps; units in long format.
- Delegation notes: tests/docs went to DeepSeek flash / gpt-oss; `readiness.py` and `anonymise.py` from the delegate needed rewriting by hand (duplicate dataclass field, inverted warn/fail thresholds, unformatted check names, missing length validation); one `summarize` call returned a summary of the prompt instead of the document. The MCP `verify` runs from the parent folder with an allow-list that rejects absolute interpreter paths, so results were installed and checked by hand.

### Code review of the session (2026-10-14, `/code-review high`, 10 findings, all fixed)
- Export guide had MODE coding reversed (code: MAN 0, AUTO 1, CAS 2): fixed, the customer is asked to send a mapping if theirs differs. The anonymiser test uses the simulator's own coding, so it could not catch this.
- `readiness`: SP and MODE are no longer tested for being stuck; duplicate or NaN timestamps give a `time_order` FAIL instead of ZeroDivisionError; a named but absent OUT/MODE tag is a WARN (as an unnamed one), PV/SP absent is a FAIL.
- `anonymise`: default seed is random (`seed=None`) and stored in `AnonymisedData.seed`; a tag both linked and kept, and an empty group, raise ValueError.
- `split_unit`: needs whitespace or a letter before the bracket, a numeric or multi-word bracket is not a unit; headers that collide once the suffix is cut keep their full text.
- `csv_long`: quality accepts 0/1/2, good/ok/uncertain/bad or empty; anything else is a clear ValueError.
- OPC UA: namespace URIs are looked up again after a reconnect.
- SQL `fetch_rows`: one SELECT or WITH...SELECT, no comments, no INTO/INSERT/EXEC/... words. It is a screen, not a sandbox: use a read-only account. (A regression test found that my first version of the regex contained a backspace character instead of `\b` and blocked nothing.)
- Regression tests: `connectors/tests/test_review_fixes.py`, four more in `loops/tests/test_readiness.py`.

### A7 / P6.7 (2026-10-14): ABB and Siemens PI forms from public manuals
- Read: Siemens FAQ 109481448, application example 79047707 (equation p.15), S7-1500 PID Control manual (p.90-91); ABB Pid01A functional description 3AST001596D013 rev D. Facts and page numbers: `docs/VENDOR_PID_FORMS.md`.
- Siemens PID_Compact: verified (ideal form with weightings, times in seconds, positive Gain, TI = 0 disables I). Our `gain_seconds` form is right; traps added as caveats: set PWeighting = 1, scale Gain by out_span/pv_span.
- ABB: ideal PID, deviation in percent of range (so no gain scaling) verified; the TI/TD unit is NOT stated and the library manual returned 403: `partly_verified`, used as seconds.
- Code: `loops/src/crosscut_loops/vendor_forms.py` (`VENDOR_FORMS`, `siemens_gain`, `siemens_pid_compact`, `abb_pidcc`), 10 tests. Not yet wired into `tuning_report.py` (next small step). Gates: ruff, mypy, pytest pass.
- Second pass (same day): ABB Binary and Analog Handling manual 3BSE041488-600 A read in full text. New facts: Gain is normalised (G = Gain x OutRange / PvRange inside the block, so kc is used as is), setpoint weight beta editable in PidCC (set 1). TI/TD unit still not stated anywhere (formulas are images); forum posts say seconds, not evidence. Code caveat added.
- Limit: the Siemens range formula is derived from the FAQ principle, not tested against a controller. Delegation: none used for this step (small code and tests written directly).
- Step 1 of the 2026-10-14 list (wire into the report): `TuningReport.vendor_forms`, Markdown section "Vendor blocks", payload key `vendor_forms`, new kwargs `pv_span`/`out_span` of `build_tuning_report`. Correction found on the way: identified `kc` is a RAW gain (output units per PV unit), so Siemens takes it as it is and ABB needs `kc * pv_span / out_span`; the first version of `vendor_forms` had this the wrong way round. Tests: `loops/tests/test_tuning_report_vendor.py` (delegated to deepseek-flash, 7 tests, passed as delivered), updated `test_vendor_forms.py`. The frontend does not show the new key yet (no Node here).
- Step 2 of the 2026-10-14 list (V1 rest): `sim/src/crosscut_sim/timing_faults.py` + `sim/tests/test_timing_faults.py` (both delegated to deepseek-flash; the test file needed 2 hand fixes: missing CAS import, return_mode value that was a valid mode) and `experiments/exp05_timing_faults/` (script delegated to gemini-flash after deepseek cut off; targets frozen in the README before the run; all PASS). Finding: timestamp jitter raises the Harris index by 7 % (1 s) and 11 % (3 s) because `monitor` derives dt from the median stamp step; fix proposed, not applied (see the exp05 README). Mode flips are handled exactly.
- Step 3 of the 2026-10-14 list (connector gaps): (a) SQL importer: repeated local times at DST fall-back are read as the second pass per tag (same rule as the CSV importer, `csv_import._resolve_instant`), counted in `SqlImportReport.n_dst_repeats_resolved`; this also covers the long-format CSV. The rule needs rows of one tag in time order; a query sorted differently for one tag can mis-resolve an ambiguous hour. (b) Long CSV: optional columns found by header word (`quality`/`q`/`status`, `unit`/`units`/`eu`), units go to the tags document, two units for one tag raise ValueError; without header words the 4th column stays the quality (old behaviour). (c) OPC UA data-change subscription: `opcua_subscribe.py` (`import_opcua_subscription`, `hold_resample`): notifications are stamped with the local receive time, resampled onto a regular grid with sample-and-hold, a node without a value stays NaN/BAD; tested against the test server only (asyncua 2.1.0), never against a real PLC or a server that sends source timestamps differently. Delegated: 4 files to deepseek-flash (tests for DST and units passed as delivered; the subscription module needed two hand fixes: `subscribe_data_change` wants Node objects, `str(node.nodeid)` is not the string form, use `to_string()`).
- Step 4 of the 2026-10-14 list (tuning part 2, C3). Sources read for it (PROVENANCE rows added): Astrom and Hagglund 2006 ch. 7 (AMIGO PID eq. 7.7, benefit of derivative action), Skogestad and Grimholt (SIMC chapter, improved PI rule, N = 10, series/ideal conversion), Skogestad lecture APC6 pp. 12-15 (cascade order, sigma 4-10, Shinskey).
  - **Derivative (exp06, targets frozen first):** P1 PASS (IAE ratio <= 0.41 for tau_n <= 0.3), P2 PASS (Ms <= 1.45), **P3 FAIL** (at tau_n 0.7 the PID still gains 30 %, at 0.9 only 6 %; the advice threshold 0.5 was kept, it is conservative). Cost: controller-output noise 13-27 times larger than with the PI. The report now shows AMIGO PID, the advice and Kc(1+N); vendor tags with Td and the filter (Siemens TdFiltRatio = 1/N, DWeighting 0; ABB TF = Td/N) appear only when derivative is advised.
  - **Closed-loop identification (exp07):** the direct fit is biased with a coloured disturbance (gain 41 % low, time constant +133 %). The first IV version failed I1 and I3 (delay +14 samples); it was fixed after diagnosis on seeds 1-20 (same rows for all delays, projected residual as score) and checked on seeds 21-40: gain 19 % off (I1 FAIL, 15 % target), time constant 26 %, delay 1 sample. Usable as an advisory model with a stated error bar, not as a replacement for a step test. Not wired into the API.
  - **Cascade (exp08):** C1 and C2 MET (outer overshoot 1.1-3.3 % at sigma 10/4; disturbance IAE 8 times lower than a single loop). Too little separation (sigma 1) gives 12 % overshoot and 47 % worse disturbance IAE but no instability on this plant. A bug in my first helper (y2 identified instead of y1) made the first run show instability everywhere; found by looking at the identified models.
  - **Found on the way (for the code review):** `identify_fopdt` on a record with ONE step and little noise returned gain 0.55 instead of 2 (collinear input and constant); the R squared guard did not catch it. The exp08 identification uses a pulse instead.
  - Delegation: 9 files to deepseek-flash (4 tests, `tuning_pid.py`, `identification_cl.py`, `cascade.py`, 3 experiment scripts, one cut off at the token limit and re-split into two); hand fixes: `ideal_to_series` formulas (my specification had the inverse wrong; the delegated round-trip test caught it), exp07 (`PiSettings` unpack, `tau_s` name), exp08 (missing outer process), mypy return type.
- **Code review of this session (`/code-review high d32fe39..HEAD`, 10 findings; 9 fixed, 1 partly):**
  - `jitter_timestamps` returned float64 (offsets were float): at epoch scale the 1 ns gap vanished. Fixed (int64 offsets), test added.
  - exp06 noise ratio was the std of the second difference: fixed, re-run, numbers moved by < 0.3; the PID advice text and A17 keep "13-27 times" (12.6-25.4 on the grid, 26.7 post hoc).
  - SQL rows shorter than 3 fields: explicit ValueError (the reviewer's claim that this raised ValueError before was wrong, it was an IndexError; the documented ValueError now exists).
  - OPC UA subscription: output sorted by time before sample-and-hold (wall clock can step back); `ns=0;i=...` ids compared in canonical form; a session that died during the recording now raises ConnectionError instead of writing flat GOOD data (one read at the end; a bad-status answer counts as alive). Test added. Still open: no automatic reconnect inside a recording.
  - `plan_cascade` floor: exp08 now also simulates the planner as shipped (requested sigma 1/2/4 all give achieved 5.0 here); README documents it.
  - `mode_flip_events`: per-flip `return_to` (so a loop that ran in CAS is handed back to CAS), docstring corrected.
  - `build_tuning_report`: a non-positive `pv_span`/`out_span` degrades to empty ABB tags with a caveat instead of raising; one shared `DEFAULT_OUT_SPAN`.
  - `simc_pi_improved` now shares `tuning_rules.simc_pi_with_lag` with `simc_pi` (no duplicated formula, no borrowed constant); docstring corrected.
  - exp08 helper: dead `outer_pi_for` and no-op calls removed, the redundant inner simulation in `identify_outer_open` dropped (baseline IAE 35.3 -> 38.6 because the noise sequence changed).
  - `identify_fopdt_closed_loop`: clear error for a record that is too short, lists accepted, helper takes 3 parameters, misplaced codecheck comment moved.
  - Not changed: `sql_import` still sanitises the tag name twice per row (cheap, left for clarity).

## 2026-10-14 - Opus consultation and two fixes

- Opus advisor reviewed the open points. Accepted: shared `sampling_period` (no resampling,
  because interpolation itself biases Harris); free-run fit plus excitation count for
  identification confidence.
- `monitor.sampling_period` and `LoopSettings.scan_period_s`: jitter bias in Harris removed (exp05 re-run).
- `identification_quality.py`: `assess_fit` gives `free_run_r2`, `excitation_events`,
  `low_confidence`; `build_tuning_report` adds a note (does not block) when a record has
  fewer than 2 input moves or free-run R2 < 0.6.
- Not done: output-error refit for step records. Note that on a clean 2-gain single-step
  test `identify_fopdt` returned tau 7 s (true 40) and delay 18 s (true 5) with gain
  close to right: tau and delay from a single step are poor even when the gain is not.
- Open from Opus: exp07 diagnosis (noise-free run, signed errors, 24 h records, weaker
  disturbance); derivative advice to include PV noise vs OUT range; ABB TI/TD printed as
  UNCONFIRMED with export blocked until A7 is confirmed.
- `identification_oe.py` (output-error refit, numpy only): on a single-step record with noise
  sd 0.05 it recovers gain 2.0, tau 39-41, delay 4.7-5.6 (true 2 / 40 / 5) where ARX gave tau 6 and
  delay 26. At noise sd 0.2 gain stays right (1.97-2.0) but tau/delay trade off (27-29 s / 16 s).
  `tuning_report` uses the refit only when its free-run R2 beats the ARX fit.
- exp07 diagnosis (table in its README): no bug; the gain miss is a finite-sample effect of the
  load disturbance (error ~1/sqrt(N)). Target I1 stays failed.

## ABB time tags marked UNCONFIRMED (2026-10-14)
The vendor section of the tuning report now prints a banner for every form whose evidence is not
"verified" and writes ABB TI/TD/TF as "<value> s (UNCONFIRMED)". There is no export or auto-apply
path in the code yet; when one is added it must refuse unconfirmed forms. Still open: derivative
advice that weighs PV noise x Kc(1+N) against the OUT range (exp06 P3 reported as failed).

## Derivative advice checks PV noise (2026-10-14)
`pv_noise_sd(y)` (MAD of first differences / sqrt 2) and `noise_checked_advice` in tuning_pid:
"use derivative" is withdrawn when 3 * Kc(1+N) * noise sd exceeds 5 % of the OUT range (our
heuristic, thresholds not yet validated on plant data). Wired into `build_tuning_report` before
the PID vendor tags are built. exp06 P3 (IAE ratio 0.70) stays reported as failed; unchanged.

## Fuzzy Studio: backtest and rule matrix (2026-10-15)
- `crosscut_fuzzy.backtest`: finds operator moves (jumps of the SP tag above a dead band), averages the
  fuzzy advice over the 900 s before each move and scores sign agreement, correlation, majority share
  and silent share. `backtest_payload` + `POST /datasets/{id}/fuzzy/backtest` give it for the whole
  record and each half. Advisory only, nothing is written.
- `crosscut_fuzzy.matrix.rule_matrix` + `POST /fuzzy/matrix`: rows x columns of two inputs, rules
  placed by AND with exactly those two inputs, the rest listed as unplaced. The screen itself is NOT
  built (no Node.js); the data is ready for it.
- exp09 (targets frozen before the run): B1-B4 met, B5 missed (43 % of operator moves met a silent
  rule base, target <= 30 %). Rule base not edited. The operator is our own simulation, so this
  shows the pipeline works, not agreement with a real operator.
- Open: reason for the silent moves, a tuning round on the first half, a real record with SP/OUT.

## Public data round two: SACAC PID repository, first look (2026-10-15)
- Source: https://sacac.org.za/resources/ (32 datasets, 81 files, ZIP of all). The page states NO licence for the
  data ("All rights reserved" in the footer; the CC BY 4.0 belongs to the 2019 article). Treated as: local research
  use only, nothing committed or redistributed, PROVENANCE row added first. Ask piddata@sacac.org.za before
  publishing any derived table. Files are `;`-separated with CR line ends; the sampling rate is only in the .txt.
- EXPLORATORY run, not an experiment: thresholds were NOT frozen first and the per-loop settings (delay = 5 samples,
  ultimate period = 60 samples, amplitude limit = 5 % of the PV span) are guesses. No claim of validation.
  Script lives in the session scratchpad, not in the repo; no `expNN` folder yet.
- Four loops (dt from the .txt except the last, assumed 1 s):
  - Eastman LC2 level, known sticking valve (20 s): monitor "poor_performance", Harris 0.03 (a level loop is
    integrating, so the Harris benchmark is of doubtful use), stiction verdict "inconclusive"; curve-fit index 0.52
    (23 cycles, period ~7170 s), i.e. between the 0.4 and 0.6 thresholds: the known stiction is NOT confirmed.
    Tuning identification returned delay 5640 s (an artefact of closed-loop cycling) and the low-confidence note
    fired (free-run R2 0.58), which is the right behaviour.
  - Pisa oil&gas pressure, stiction (12 s mean, minute timestamps): "oscillating", period 216 s. Curve fit refused:
    half-cycles have fewer than 30 samples (about 11 per half cycle here), so the 30-sample floor excludes this data.
    Tuning blocked by a poor fit (R2 -3.0), 0 input moves: correct.
  - Horch pulp level, tight tuning (1 s): "oscillating", period 95 s, Harris 0.04; curve fit found 0 cycles (only 1146
    samples); tuning gave a model with a low-confidence note (1 input move).
  - Pisa chemical flow tuning case: "poor_performance", Harris 0.10; no oscillation; model tau 180 s, no note.
- Take-aways: the oscillation check agrees with the dataset labels on 2 of 2 labelled oscillations; stiction is not
  detected on either stiction loop (inconclusive, curve fit unusable at these sampling rates or borderline); the
  low-confidence flags and the poor-fit guard behave sensibly on closed-loop data; Harris on level loops needs a
  note. All four are single loops, so this is anecdote.
- Next: freeze targets, then run the stiction loops from `stiction-*` (11 files) and the DB runs together; decide
  whether the 30-sample half-cycle floor should be lowered (test on exp01 first).

## exp10: stiction index on the SACAC stiction loops, half-cycle floor 30 -> 10 (2026-10-15)
- Targets frozen in a separate commit before the run (`experiments/exp10_sacac_stiction/README.md`). 6 distinct
  loops (12 files), all labelled stiction by the repository, so detection only; no negatives.
- Floor 30: index for 2 of 6 loops. Floor 10: 4 of 6, 3 of them >= 0.6; both targets met. Not found: Horch flow
  (irregular half-cycles) and Pisa oil&gas pressure (under 10 samples per half-cycle).
- `MIN_SAMPLES_PER_HALF_CYCLE` in `stiction_curvefit.py` lowered from 30 to 10 after the exp01 acceptance run with
  the new value gave an identical `results/acceptance.md` (no healthy-class false alarm among the 10 held-out seeds
  per class, 95 % upper bound 27.8 %; the square-wave limit is unchanged). Test updated. ruff, mypy, pytest green.
- Caveat: exp01 is simulated, so it can only show that the lower floor did not add false alarms THERE; on real
  healthy loops with short oscillations the lower floor is untested. The data licence is unstated (local use only).

## exp10 correction: floor back to 30 (2026-10-15, after review by the owner and an Opus advisor)
- The change 30 -> 10 is reverted. Reasons: floor 10 was picked after seeing the SACAC data; the exp01 check gave an
  identical report because no simulated half-cycle has 10-30 samples (vacuous); the two loops it added are level loops,
  outside the method's stated scope; the "75 %" used the wrong denominator. Real result: 1 clean detection (Pisa chemical
  pressure), LC2 inconclusive (0.53), 4 loops without an index. The earlier log entry "floor 30 -> 10" is superseded.
- Open (in order): (1) read He et al. 2007 to see whether integrating loops are fitted on PV, not OP; (2) re-score exp10
  by process type with targets frozen first (self-regulating on OP, level loops on PV as a separate variant); (3) any new
  floor only from a simulation sweep of the sampling step (half-cycles of 8-40 samples, healthy and sticking).

## exp10 round 2: level loops on PV (2026-10-15)
- Targets frozen first (separate commit). He et al. 2007 fit PV for integrating processes (abstract-level check only).
- Target L (>= 2 of 3 level loops with index >= 0.6 on PV) MISSED, 0 of 3: unfiltered PV has noisy zero crossings, so
  every half-cycle floor check fails and no index is produced. No package change.
- State of the stiction detector on real data: 1 of 6 known sticking loops flagged, 1 borderline, 4 no verdict, no
  information on false alarms. Do not describe it as validated. Next possible work (new frozen targets needed): PV
  filtering / robust segmentation, a sweep of sampling step in simulation, and real HEALTHY loops from the repository
  (sensor-fault, tuning, unknown categories) as negatives.

## exp10 round 3: real negatives (2026-10-15)
- Targets frozen first. 6 non-sticking SACAC loops (external-disturbance oscillation, normal operation, tight and sluggish
  tuning). Result: 0 of 6 flagged but also 0 of 6 get an index, so N1 is met trivially and says nothing. Combined with
  rounds 1-2: of 12 real loops the curve-fit detector gives 1 clear and 1 borderline index; the rest is "no verdict".
- Conclusion to keep stating: the OUT-shape stiction detector is validated on simulation only; on real data at 1-30 s
  sampling it mostly abstains. Do not rely on it for decisions. Possible next work (needs new frozen targets): robust
  half-cycle segmentation (noise chatter, hysteresis relative to noise), PV filtering for level loops, longer records.
