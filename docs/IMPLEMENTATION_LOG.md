# Implementation log

**Read this first in every new session, then `docs/HANDOFF.md` (owner to-do for when the owner is at the computer, and next steps the assistant can do alone).** It records what is done, what is pending and in which order.
Update it at the end of every work block (task board, session log, open items) and before suggesting a new session.

Last updated: 2026-10-19 (end of stage 1 / module 1: state table and next steps are in `docs/HANDOFF.md`; the log
below is chronological, so the task boards further down show the state of their date, not today's)

## Project snapshot

Crosscut Process Suite: modular process-control toolkit for mineral processing (loop monitoring, PID tuning,
soft sensors, anomaly detection, MPC, fuzzy/expert rules, ML-based operating-range recommendation, optimization).
Every module is optional. Status (2026-10-19): stage 0 (foundations) and stage 1 are done; **module 1 (loop
monitoring and tuning) is usable as an advisory library, API and web UI**, validated on simulated loops and, for the
KPI triage, exploratory on two public datasets; nothing in the suite writes to a control system.

- Stack: C++20 core (CMake, pybind11) + Python offline tooling; Windows and Linux from one code base.
- Rules: code, comments, commit messages and docs in English; all data synthetic; no code, data or parameters
  from any employer; every method listed in `docs/PROVENANCE.md` before it is implemented; do not publish to PyPI
  until the trademark registers have been checked.
- There is no written original plan: the project was shaped in conversation, and `docs/design/` holds feature-level plans
  written while the work was done. The assistant has only the repository to reconstruct intent from
  (`docs/PROJECT_DESIGN.md`, provenance note).
- Repository is public under AGPL-3.0-only with a commercial licence offered (`LICENSING.md`, ADR 008, ADR 009).
  Never force-push. Commit at natural milestones.

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
| V2 | Messy-export corpus generator + importer robustness tests | 1 | done (A2: `messy.py`) |
| V6 | Customer-run validation kit (export guide, readiness checklist, anonymizer, report template) | 1 | partly: readiness check (`readiness.py`), anonymiser (`anonymise.py`); export guide and report template todo |
| V3 | Public dataset benchmarks (flotation quality, anomaly, degradation); add licence rows to PROVENANCE | 1-2 | partly: flotation CSV connector (`flotation_public.py`); SACAC and ISDB loop data used locally for the loop experiments (PROVENANCE rows); anomaly and degradation sets todo |
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
| E1/E2 | Customer validation kit (V6), public benchmarks (V3) | partly | see V6 and V3 above |

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

- Clean-code pass (session 2). `agentkit check` found 132 findings in 46 Python files (53 functions too long, 43 meaningless names, 17 missing docstrings, 13 too many parameters, 6 deep nesting); the gate covers Python only, so C++ (`core/`) and TypeScript (`frontend/`) were never checked and still need a manual review (e.g. `fopdt.cpp`: names `a_`, `y_`, `n`, no comment on the discretisation formula, 5 constructor parameters). A first attempt with Haiku subagents was wasteful (one agent misread the task, six were stopped); replaced by `dev/refactor_loop.py`: for each finding it sends ONE function to DeepSeek via `agentkit delegate`, keeps the result only if the file parses, the finding count drops and the package tests pass, otherwise restores the file (second try with `--escalate`). It fixes the easy majority; big functions (50-100 lines), builders with many parameters and changes that need callers updated are skipped and remain manual work (the tool does not log why a fix was rejected yet). Lesson: do not hand a Claude subagent a job that is a loop of "function -> cheap model -> test"; build the loop.
- Result of the Python pass: gate findings 132 -> 50 (remaining ones are the big functions listed by `agentkit check`, mostly the plant `reset`/`step`/tag-catalog builders, the route-builder closures in `api/app.py`, and functions whose parameters need caller changes); `ruff`, `mypy` (sim, loops, fuzzy, api) and the whole test suite pass. The tool at first accepted fixes without running ruff/mypy, which let in long lines, missing annotations, a removed import (`Axes`) and a duplicate stub definition; it now counts ruff E501 and mypy errors as findings too. Haiku (one small agent) wrapped the last long lines and fixed types; I checked the result myself. Still to do: the 50 remaining findings by hand (with context), C++ and TypeScript review, and a note in the tool about why a fix was rejected.
- C++ review (`core/`): renamed members and locals so they reveal intent (`decay_per_step_`, `output_`, `delayed_inputs_`, `oldest_input_index_`, `input`), extracted the parameter check, commented the exact-discretisation step, named the test tolerances, spelled out test variables. Interface unchanged (five parameters mirror the Python reference; pybind keyword names `y0`/`u` kept on purpose). Verified locally afterwards with the user-level toolchain in `~/tools/cpp` (`build_core.cmd`, no admin): 4 C++ tests with -Werror and 4 parity tests pass. A stricter local run (`build_strict.cmd`: -Wconversion -Wsign-conversion -Wshadow -Wold-style-cast as errors on the library) is also clean. Still only in CI: real MSVC /W4 /WX, GCC, and the ASan/UBSan job (zig does not appear to link the ASan runtime).

- Explanatory comments pass (session 2). `dev/comment_loop.py` asked DeepSeek flash to add teaching comments (model, formula, units, data structure) to 296 Python functions across all packages, one function per call; a result is kept only if the syntax tree without docstrings is identical (no code changed), ruff is not worse and the package tests pass. The comments are NOT reviewed yet: the model sees one function, not the project, and tests cannot catch a wrong comment. Known error: `sim/.../pid.py` says `td_filter_n` is "how many samples the filter averages over" while its docstring says the filter time constant is `Td / td_filter_n` (so it is a filter coefficient, not a sample count): fix the comment. Review order (numerics first): `sim/.../{pid,core,disturbances,faults}.py`, `sim/.../plants/*.py`, `loops/.../{stiction,identification,tuning_rules,tuning_view,metrics,benefit}.py`, `fuzzy/.../inference.py`, then the rest; delete comments that only restate the code. Also changed agentkit `codecheck`: function length now counts CODE lines only (blank lines, comments and the docstring are free), otherwise comments pushed 289 functions over the limit; gate findings now 48.
- State at the end of session 2. Done: stage 0, stage 1 screens D1-D5, Fuzzy Studio v1 + versions/diff (backend and screen), clean-code pass (names, long functions), C++ core readable and verified locally (`~/tools/cpp/build_core.cmd`), comments pass for Python. Pending, in this order: (1) review the generated comments (list above); (2) the 48 remaining gate findings by hand (big plant `reset`/`step`/tag-catalog builders, route-builder closures in `api/app.py`, builders with many parameters); (3) comments and the same clean-code pass for TypeScript (`frontend/`), run one worker per directory in parallel and verify unchanged code by comparing `esbuild --minify` output before and after; (4) Fuzzy Studio: rule matrix view and backtest against operator moves (output `feed_change` is a delta of the SP tag); (5) Modules map page; (6) open items below. Check the CI result of the last pushes (jobs `cpp`, `frontend`) first: there is no `gh` on this machine.

### 2026-10-12, session 3
- `gh` was missing: a portable build is installed in `%USERPROFILE%/tools/gh/bin` (also on the user PATH) and logged in as `msurun`. All CI runs up to the comments commit 2ea3b07 are green, jobs `cpp` and `frontend` included. `gh run list` works now.
- Comment review: the generated comments were partly wrong or only restated the code because the model saw one function. New tool `dev/comment_review.py`: a model sees the WHOLE file and returns edits of whole comment blocks (delete / replace). An edit touches pure comment lines only, partial blocks are rejected, and a chunk is kept only if the code fingerprint is unchanged, ruff is not worse and the package tests pass. Every accepted edit is logged with the model's reason (JSON lines) for a human audit. A trial on `pid.py` found the known `td_filter_n` error.
- Result of the comment review (8 workers, one per package, DeepSeek with `--escalate`): 482 edits accepted (353 replacements, 129 deletions), about 60 rejected (partial blocks or failed checks); 42 comment lines wrapped afterwards (the tool counted 95 characters without the indentation: fix the limit in the tool). Many replacements are "kept as is" rewrites (noise, harmless). Three wrong comments in `pid.py` (sign of the error, sign of the derivative term, `td_filter_n`) were corrected by hand. The edits are NOT fully audited: spot checks of `tuning_view`, `identification` and `pid` were correct; the log of every edit with the model's reason was in the session temp directory (not kept). Ruff and all tests pass.
- Next (in this order): (1) the 48 remaining gate findings by hand; (2) TypeScript in `frontend/`: comments and clean-code review, one worker per directory; (3) Fuzzy Studio rule matrix and backtest; (4) modules map page; (5) open items. For the portfolio goal prefer depth over breadth: finish and document 2 or 3 modules well (loop monitoring, tuning report, Fuzzy Studio), then a 5-minute demo in the README. Before the repository becomes public: trademark check, no employer traces, written confirmation that the project does not conflict with the employment contract.
- Style gate, second pass (`dev/refactor_loop.py`, 8 workers, one per package, tests included): findings 190 -> 56. The loop broke three things that I fixed by hand: a missing `Scenario` import in a test, three untyped `loop` parameters in `mill_circuit.py`, and about 40 long lines (comments wrapped by script, 16 docstrings shortened by a Haiku agent). Remaining 56 are the big functions and builders with many parameters, which need callers updated: `api/app.py` (`create_app` 198 lines, three 5-parameter routes), `fuzzy_routes.build_fuzzy_router`, `manifest.write_artifact` (10 parameters), `csv_import.import_csv` (79 lines), `opcua/collector.collect` (85 lines, 12 parameters), `opcua/server.start`, `sim/dataset.record` and `write_dataset` (11 parameters), `sim/run.main`, `wood_berry.reset/step`, `scenarios._build_mill_circuit_scenario`, `pid.__init__/update`; plus a few tests and `tools/`. Do these with the callers in context, one function per delegation, with `--files` for the callers.
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

## exp11: half-cycle floor from a synthetic sweep (2026-10-15)
- Diagnosis first: on the SACAC loops the refusals come from real short, regular half-cycles (10-25 samples) or from too few
  cycles (negatives), not from chatter (hysteresis already exists, CV 0.05-0.22), so "robust segmentation" was not the lever.
- Sweep (design frozen first, `experiments/exp11_stiction_floor/`): no floor meets the criterion. Below about 15 samples a
  sine is read as a triangle (floor 10 was wrong); at noise sd 0.15 of the amplitude detection collapses even at 30 samples,
  because noise pushes SI towards 0.5. Floor stays 30; no package change.
- Consequence for the product: the curve-fit index is only usable on clean OP; on noisy OP it reads about 0.5 or abstains,
  which matches LC2. Next candidate (new frozen targets needed): a noise-aware index.

## exp12: stiction detector iteration on real loops (2026-10-15)
- Protocol agreed with an Opus advisor; labels, split, targets and stop rules frozen first (`experiments/exp12_stiction_scoreboard/`).
  19 SACAC loops (6 sticking, 13 not; 17 counted). Rounds 1-4 in the README with every frozen text and result, including a
  protocol breach (scoreboard run before Gate 1b finished) and an implementation deviation found and fixed (old 30-sample floor
  still applied to upsampled lengths).
- Candidate A (band-limited to 7 harmonics, upsampled, noise variance subtracted from both fit errors, floor 18 samples per
  half-cycle from synthetic data): synthetic detection 84-100 % with 0 % false alarms from 20 samples per half-cycle at noise
  0.15 (shipped index: 4 % at 30). Candidate B adds "level loops on PV" (He et al. 2007, abstract-level).
- Scoreboard: shipped 1/6 detected, A 3/6, B 3/6 (held-out 2/3); false alarms 0/11 for all; Eastman LC2 wrong on OP (A), right on
  PV (B). T1 (>= 4/6) and T3 (>= 11/17 answered) are MISSED; Pisa oil&gas is under the information limit (8 samples per half-cycle).
- Not in the package yet. Open decision for the owner: put B into the package (needs loop kind in settings, exp01 acceptance
  T4, PROVENANCE row for the noise-corrected index as our own construction) and/or allow a round 5.

## exp13: stiction as a ranked suspicion (2026-10-15)
- After the Opus review: the hard passive verdict was the wrong product. New output: oscillation window (>= 6 regular cycles,
  quiet setpoint), curve-fit index (candidate A, PV for level loops) plus Horch cross-correlation oddness, a suspicion score in
  [0, 1], "test the valve" at >= 0.5. Targets frozen first (`experiments/exp13_stiction_suspicion/README.md`).
- Horch constants and its use (F only: AUC 0.83 on synthetic loops; L 0.47, so off for L) were derived on a synthetic closed
  loop (PI + stiction valve), not on SACAC. Label fix: `other-F-chemicals` kind L -> F.
- SACAC: all targets met (AUC 1.00 on 6 vs 2, 6/6 sticking flagged, 0 of 2 ranked non-sticking), but 9 of 11 non-sticking loops
  have no oscillation window, so the test rests on 2 negatives from one source. Treat as a smoke test and demo, not accuracy.
- Not in the package. Next (new frozen targets): classifier trained on synthetic loops over these test outputs, scored on the
  same SACAC targets untouched; then plant data with valve-test labels from the owner.

## exp14: classifier trained on synthetic loops (2026-10-15)
- No plant data with valve-test labels is available (owner). Targets frozen first (`experiments/exp14_stiction_classifier/`).
  Logistic regression (numpy) on He, Horch, samples per half-cycle, regularity, kind; trained on 404 synthetic records (stiction
  versus sine load, square load, tuning limit cycle; decimation 1-8).
- Synthetic held-out AUC 0.84 (target 0.85, missed by 0.01), hand score 0.77. SACAC: AUC 1.00, 5 of 6 sticking flagged, 0 false
  (hand score 6 of 6). Rule applied: the exp13 hand score stays; nothing was tuned afterwards. He carries most of the signal, Horch
  adds about 0.02, level loops are the weak class.
- Open: better features for level loops and for fewer than 18 samples per half-cycle; real evidence still needs plant data with
  valve tests. Package unchanged.

## Ranked stiction suspicion in the package (2026-10-15)
- New `loops/src/crosscut_loops/stiction_suspicion.py` (port of exp12 candidate A and exp13; scores identical to the experiment code on
  40 synthetic and 11 SACAC files, max difference 0.0). Output: score 0..1, advice `test_valve` (>= 0.5) / `unlikely` / `not_ranked`,
  He index, Horch value, period. A ranking that says which valve to test, never a diagnosis; the old `stiction_verdict` stays.
- Wiring: `LoopSettings.process_kind` ("self_regulating" or "integrating", from the new optional `process_kind` key in
  `project.schema.json` / `LoopTags`), `LoopReport.stiction_suspicion` and `stiction_advice`, a report finding "stiction possible
  ... run a valve test", and the two keys in the overview row. Frontend types and locale strings are NOT updated (no Node.js).
- Tests: `test_stiction_suspicion.py`, two tests in `test_monitor_stiction.py`; ruff, mypy, pytest green.
- exp01 acceptance (targets frozen first, `acceptance_suspicion.py`): low noise 10/10 at bands 4-8 %, 0 false alarms in all classes
  (also the square wave), but 0-1 of 10 at full noise because the window search on PV finds no regular oscillation (shipped verdict:
  8 of 10 at band 8 %). Both outputs stay; improving the window at high noise is the first item of the next round.

## exp15 protocol frozen (2026-10-16)
- `experiments/exp15_stiction_robust/README.md` sha256 6f1e7d19fcbb03e203da8656329c2c540b413fbe54803b963f5ecc42e3566bd6 (recorded before any exp15 code ran). Final data: exp01 seeds 21-40, synth14 seeds 500-599, shifted generator seeds 1000-1099: run once.

- exp15 amendment 1 (round 5, combiner C6): README sha256 9ca28c05b61dbbb16eef83a8ca9cd54492d846cf31e6bcdcfabd6f7615f6de22, recorded before any round-5 code.

## exp15: robust stiction suspicion, rounds 1-5 and final run (2026-10-16)
- Protocol agreed with an Opus advisor (README sha256 recorded before any code; amendment 1 for round 5). Dev data and never-seen final
  seeds kept apart; a shifted synthetic generator (Kano-style stiction, coloured noise) added. Details and every rejected candidate in
  `experiments/exp15_stiction_robust/README.md`; final numbers in `results/final.md`.
- Rejected: C1a (lag-1 regularity: a window in 100 % of white-noise records), C3a (OUT/PV agreement: 10/20 false alarms on wander),
  C5 (folded-wave index alone: 77-79 % flags on square forcing), C6 (combiner: failed the exp01 dev gate, 20/20 on square forcing).
- Shipped: C4a = window by spectral-peak prominence (gate 36.5 from noise-only records) with the curve-fit index on the whole record as
  fallback. Final data: exp01 full noise band 8 % 10/20 (was 2/20), no exp01 false alarm above 2/20, SACAC 6/6 and 1 negative flagged.
- NOT achieved: synthetic AUC >= 0.85 (0.77 and 0.65, unchanged by C4a) and <= 10 % flags on healthy synthetic classes (sine about 28 %,
  square about 50 %). A "test_valve" advice is a reason to test the valve, not evidence. Real plant data with valve tests is still missing.
- Open: C6-style combiner scored AUC 0.85-0.95 on synthetic data of its own family but failed exp01 (setpoint forcing); retry needs
  setpoint-forced training data and the SP column in exp01 records.

- exp15 audit follow-up (2026-10-17): README addendum with corrections, ablations of C4a (dev), paired McNemar p = 0.0078 for T2, disclosure of the final.py reformat; docstring LIMITS extended.

## exp16: does stiction suspicion generalise? (2026-10-17)

- Independent data: ISDB v1.0 (Jelali & Huang 2010, 114 loops; 10 are SACAC twins) downloaded, hashed, labelled only from provider comments, sealed; counted set 13 sticking + 14 other (high confidence, independent). New generator G3 written by a different model from a physics spec (setpoint forcing, cascade, multi-tone, sensor chain, three stiction models); a spec gap and a double-integration bug were fixed and logged; ideal-valve twin rule for stick records. G3 differs from G1/G2 more than they differ from each other and is in SACAC's range.
- LOFO (dev): shipped worst-family AUC 0.549, C7a (C6 features retrained on G1+G2+G3) 0.739, C7b (+ shape features) 0.678 -> finalist C7a, threshold 0.5.
- Final single run (salt = commit 2bb08f9...): C7a worst family 0.714 vs 0.522, bootstrap interval [+0.165, +0.218]; exp01 and T7 fine; SACAC veto 3 non-sticking flagged (limit 2) and ISDB other flagged 10/14 vs 1/14 for the shipped module, AUC 0.32 vs 0.67. Not shipped. Package change: stiction finding text now says periodic forcing can look the same and asks for a valve test or a gain change (a stiction cycle changes period with gain, a forced one does not).
- ISDB per-loop scores are kept outside the repository; label table isdb_labels.csv is untracked (third-party derived). Do not publish before asking the data providers.

## Loop health KPIs and tuning from history (2026-10-18)

- Direction change after the Opus strategic review: stiction detection from passive data is closed as a frozen weak hint (C4a, wording asks for a valve test or gain change); the definitive check is a guided valve test (not built yet). Effort moves to KPI triage and tuning.
- New `health_kpis.py`: valve travel and reversals per hour, quantisation step and ratio, valve extremes and sizing hint, grouping of loops by shared oscillation period, Kendall trend. Wired into `analyze_loop` (new LoopReport fields, findings "quantisation" and "valve oversized/undersized", overview row keys). Grouping by period and trend are available as functions but not yet shown in the overview.
- New `history_windows.py` and `history_tuning.py`: natural setpoint steps are found in AUTO data, an output-error FOPDT model is fitted per window, cross-checked on the other windows and graded high/medium/low/none; no step gives "no_excitation" and a bump-test recommendation. Closed-loop IV was rejected (wrong time constant on short windows). `tuning_report` got `identify_model` and `report_from_model`.
- Evidence: simulation (clean data accurate within 2 %, disturbed data never graded high); real data (exp17): 26 of 86 records have a setpoint step, none reached medium or high, so history tuning rarely applies and bump tests remain the main route. KPI thresholds beyond quantisation >= 1 and the sizing medians (15 / 85 %) are not validated on real loops.
- Tests: test_health_kpis, test_history_windows, test_history_tuning, test_monitor_valve_kpis; full loops suite green.


## exp18: KPI triage on real loops (2026-10-18)

- Protocol frozen first (3310b7c), script `run18.py` delegated (Gemini), reviewed: it passed OP as `op=` instead of
  `out` (would have turned every loop into "error"); fixed before the run. One run, 44 loops scored.
- Result: T1 36/38 flagged (pass on paper, vacuous: 4/5 negatives flagged too), T3 quantisation 0/3 and saturation 0/1
  (miss), sizing "oversized" 23/44 (artefact). Cause: OP assumed 0-100 %, real OP is often a deviation variable.
- Consequence: the saturation and valve-sizing findings are unreliable when the OP range is unknown; they need an OP range
  from tag configuration or must be suppressed. Next: exp19 with a frozen OP-range rule and a stricter flag. Details in
  `experiments/exp18_kpi_triage/README.md`.

## Not assessed instead of guessed (2026-10-18, step 1 of the post-exp18 plan)

- Direction (owner + Opus review): no placeholder may drive a status. `LoopSettings.known` names the per-loop knowledge
  backed by configuration (`out_range`, `delay`, `oscillation_limits`; default all, so direct callers are unchanged).
  Missing OUT range: saturation NaN, valve travel/reversals/sizing None (quantisation stays, it is scale-free). Missing
  delay: Harris NaN. Missing oscillation limits: Hagglund not run. `LoopReport.not_assessed` and the overview row key
  `not_assessed` list what was withheld; `saturation_percent` is None when not assessed; health does not penalise it.
- `overview.default_settings` fills `known` only from LoopTags fields actually given (oscillation limits need the
  ultimate period plus an amplitude limit or a PV engineering range).
- Fixed fabricated comments in overview.py (Harris "matrix", "optimizer/trip count"); Harris is a variance ratio.
- Tests: test_not_assessed (delegated, one broken fixture fixed); dataset and finding-window fixtures now configure
  their knowledge explicitly. Frontend type `saturation_percent: number` must become `number | null` and show
  `not_assessed`: NOT done (no Node.js).
- Expected consequence: with nothing configured, loops will mostly show "ok" plus a not_assessed list until the
  parameter-free ACF oscillation detector (step 2) exists.

## Parameter-free oscillation detection (2026-10-18, step 2a of the post-exp18 plan)

- `oscillation_acf.py`: ACF regularity after Thornhill, Huang & Zhang (2003): period estimates from ACF zero
  crossings, r = mean(Tp) / (3 std(Tp)), regular when r > 1 (published default). Two additions of ours, both
  measured on synthetic signals only: (1) a crossing counts only when the ACF leaves a noise band on both sides
  (hysteresis); the band is Bartlett's 95 % band for an MA(q) process with q = first zero crossing. Without it
  white noise passed in 5 of 10 seeds and AR(1) phi=0.9 in 23 %; (2) at least 7 crossings (with 5, AR(1)
  phi=0.99 drift passed 21 %).
- Synthetic rates (100-200 runs each, 3000 samples): false positives white 1 %, AR(1) 0.9/0.97/0.99 0 %, random
  walk 0 %; detection of sine amplitude 0.3-0.5 in white noise sigma 1: 99-100 %; square wave plus AR noise 100 %.
  Known miss: a weak sine buried in stronger coloured noise (sine 0.5 + 0.5*AR(0.9)): 6 % detected; Thornhill's
  band-pass prefilter is not implemented.
- Wiring: `monitor._oscillation` uses Hagglund when oscillation limits are configured, otherwise ACF.
  `LoopReport.oscillation_method` ("hagglund"/"acf") and `oscillation_regularity`; overview row key
  `oscillation_method`. Without limits a regular cycle now classifies "oscillating" again; the finding says its
  amplitude is not assessed, and `not_assessed` lists "oscillation_amplitude" (was "oscillation").
- Delegated: module draft (DeepSeek; four spec bugs fixed by hand, among them second differences instead of
  z[i+2]-z[i]) and tests (DeepSeek + Haiku). Not validated on real loops yet: that is exp19.
- Overview: `analyze_dataset` adds the row key `same_period_as` (other loops whose period is within 10 %,
  `health_kpis.group_by_period`), a hint at a shared disturbance source. Tests delegated (Haiku).
  `kendall_trend` is still not shown: it needs KPI history over several recordings, which the overview has not.
## exp19: triage with no per-loop knowledge (2026-10-18)

- Protocol frozen first (b6d8ceb), script delegated in two parts (the first answer was cut off and loaded every SACAC
  loop with label "no" and a non-existent column; fixed by hand), committed before the run (dc63cdd). One run.
- O1 MISS (oscillating loops detected 9/20), O2 PASS (0/7 calm loops detected), O3 PASS (2/7 calm flagged; 20/44
  flagged overall vs 41/44 in exp18), O4 PASS. Exploratory: both data sets seen before.
- Cause of the misses: the Bartlett noise band and the 7-crossing rule (both my additions) need about 10 cycles
  in the record; ISDB records are short. The synthetic suite never had short records. Detector unchanged; next is a
  frozen short-record synthetic suite before any change. Details in `experiments/exp19_triage_no_knowledge/README.md`.
## exp20: ACF detector on short records (2026-10-18)

- Protocol, generator spec, generator (deepseek-flash, one reviewer fix), harness (one reviewer fix: candidate
  lookup) committed before the run. Development run only: no candidate met the false-alarm target, nothing ships.
- The shipped detector itself misses F: 11 % false alarms on AR(1) phi 0.5 noise (n = 3000), and detects 51 % of
  positive cells with >= 5 cycles. Its "oscillating" finding is not reliable on fast noise. Details and the table
  in `experiments/exp20_acf_short_records/README.md`.
## Night session 2026-10-19: ACF line closed, worklist, valve stroke test, idle index stopped

- **ACF oscillation detector, exp21/exp23/exp24 (all frozen before running):** a peak gate (the first ACF lobe after
  lag 0 must exceed 3 sigma of the estimation noise) removes most fast-noise false alarms and adds about 30 points of
  sensitivity on 5-10-cycle records. Three rounds, none shipped: G (unbiased ACF) lost 4.3 points on long records;
  J (2.5 sigma) missed F by one cell (6/100); the confirmation of I (exp24, 400 negative seeds per cell, rule from an
  Opus advisor) passed F, S and per-cell checks and missed L by 2 runs of 3600. As announced, the ACF-variant line is
  closed; the shipped detector A stays. A fails its own F target on every seed set (up to 36/400 on AR(0.5)
  n=3000); the ACF "oscillating" finding now says so and asks to confirm the cycle on the trend. `AcfConfig` keeps
  the variants (`BAND_BARTLETT_LAG`, `peak_z`) for later work; defaults unchanged.
- **Idle index (exp22): stopped before the dev run.** Hagglund's sign statistic did not separate sluggish from
  well-tuned simulated PI loops in design exploration (best variant 46 % sensitivity). A spec bug (gain-sign estimate
  biased by noise through the proportional term) was found on a smoke seed and fixed with a midpoint error. Draft,
  generator (Sonnet) and harness stay in `experiments/exp22_idle_index`; nothing in the package.
- **Worklist** (`worklist.py`, wired into `analyze_dataset`): each overview row gets `next_action` (code + params:
  ask_why_manual, check_measurement, check_output_limit, valve_test, find_common_source, test_cycle_cause,
  check_output_resolution, bump_test_and_retune, review_valve_sizing, configure_knowledge, none) and `priority_rank`
  (problem, warning, other action, configure, none; then lower health first). An ordering rule, NOT validated: the
  blind review by a control engineer (HANDOFF step 3) is what would validate it. Frontend not updated (no Node).
- **Guided valve stroke test** (`valve_test.py`, `valve_test_cli.py`, exp25): plan (1 % then 0.25 % steps, up-down-up
  legs, dwell >= 4 (tau + theta)), operator procedure text (abort rule first, back to AUTO at the end), analysis of a
  recorded test: deadband as a bracket (T - s, T] of output travel after a reversal until PV visibly moves,
  resolution as an upper bound, abort flag. exp25 on a simulator written by Sonnet from the definitions: V1 deadband
  within 0.25 % in 100 %, V2 healthy valve 100 %, V3 abort 100 %; with load steps or high noise 88-91 %. No real test
  record yet. CLI: `python -m crosscut_loops.valve_test_cli plan --op-start 50 --dwell-s 60` and
  `... analyze record.csv --op-start 50 --dwell-s 60` (columns t_s, op, pv).
- CI: one lint failure (my unchecked commit), fixed in 5e43ff1. Full gates green afterwards.
- **Level loops, exp26:** history tuning on simulated integrating loops: H1 PASS (12/12 high/medium recommendations safe); 98.5 % of runs end low/none (bump test). Low-confidence results no longer carry a tuning report (some implied Ti 20-50x too short). A read-only review of the new modules (different model) found segmentation, NaN, CSV and worklist edge cases; fixed in 073cd34 with tests, exp25 rechecked on new seeds (V1-V3 still 100 %).

## exp11: fuzzy retune of the mill feed supervisor (2026-10-19)
- Closes the exp09 B5 miss. Diagnosis on the tuning half: silent moves sat at the centre of `normal`/`on_target`
  (power 3000 +- 27 kW, P80 150 +- 2 um) while the operator moved the feed 4.8 t/h on average; terms were too wide.
- `fuzzy/examples/mill_feed_supervisor_v2.json` (narrower terms, one rule added); 4 candidates scored on the tuning
  half of seeds 1-10 only, targets frozen (938b382), then run once on fresh seeds 11-20: C1-C5 all met, silent share
  38 % -> 8.5 %, sign agreement 0.77 -> 0.72. The original example file stays. Still a simulated operator.

## Loop monitoring and tuning screens: gap review and UX pass (2026-10-20)
- Review method: ran the app on simulated datasets (stiction, detuned, observational, step_test) and looked at the
  screens (Playwright screenshots, light/dark, 1440 and 390 px). Findings: (1) the overview ignored the worklist
  (`next_action`, `priority_rank`) and the `not_assessed` list, so loops that were only partly checked showed "OK, no
  problems"; (2) valve/stiction/quantisation numbers were not shown; (3) nothing in the UI or API let the user supply
  the per-loop knowledge (dead time, ultimate period, amplitude limit, process kind) that unlocks the withheld checks,
  so `configure_knowledge` was a dead end; (4) tuning screen: raw DCS key layout broken, slider labels misplaced, no
  "current vs proposed" comparison (design S5), chart axes in English whatever the language; (5) no responsive layout.
- Done: LoopSummary contract extended; worklist logic in `src/worklist.ts` (filter, search, sort, CSV); overview as a
  worklist (priority, next action, sortable headers with aria-sort, search, "partly assessed" badge, CSV export);
  detail with next action, shared-period links, valve and stiction numbers, not-assessed notice; `KnowledgeEditor` +
  `GET/PUT /datasets/{id}/loops/{loop}/knowledge` (`loops/project_edit.py`, writes only the dataset's project.json,
  atomic); tuning: current-vs-proposed comparison (kept in browser localStorage), slider and DCS layout fixed;
  locale-aware time axis; responsive CSS. en/pl/es strings; 232 frontend tests, loops + api tests green.
- Still open: a screen for the valve stroke test (plan generator and CSV analysis need API endpoints), step 1 of the
  tuning wizard lets the user pick only suggested windows (no free start/end), the model gain has no unit, the
  predicted-response chart mixes PV and OUT scales, the Fuzzy tab was not reviewed in this pass, no Playwright test
  in the repo yet, per-tag range editing (OUT/PV engineering range) is still done in tags.json by hand.

## UI remediation P0: truth fixes (2026-10-20)
- Plan: `docs/archive/ui-remediation-plan.md` (advisor review). Done: status `not_assessed` (backend `overview.status_level`,
  UI chip/filter/sort), `health_percent` null when the Harris index cannot be computed (no imputed 70 %), detail page says
  what was not checked instead of "no action needed", one locale-aware number formatter `frontend/src/format.ts` (DCS blocks
  keep the dot), fuzzy axis ticks fixed (2600 was printed as "26"), "assumed" badge translated, test setup pins `<html lang>`
  to en. Checked on the stiction dataset: no OK/70 % any more. Python loops+api and 260 vitest tests green.
- Next: P0.5 rest (fuzzy example rule base text in the PL UI, DOM scan test), then P1 (router, context bar, ErrorBoundary).

## UI remediation P1: app shell and context (2026-10-20)
- Hash router (`route.ts`, `useRoute.ts`): `#/d/{dataset}/{view}/{loop}/{sub}`; reload, bookmarks and the back button work.
  Dataset context bar (id, period, sample period, tags, analysis time), breadcrumb on loop pages, `ErrorBoundary` per route,
  API-offline banner with retry, 404 messages for an unknown dataset or loop, skip link and focus to the content after
  navigation. Checked in a browser with Playwright scripts (deep link, back, reload, 404, offline, skip link); 302 vitest.
- Not done from P1: S1 datasets list screen and skeleton rows (loading is a status sentence); both are low value next to P2-P4.

## UI remediation P2: tuning wizard (2026-10-20)
- Stepper (shape + word per state), free analysis window (zoom the PV/OUT trends and "use the visible range", or type minutes),
  gain with unit (PV unit per % of output), dead time / time constant with a plain-language controllability hint,
  predicted response in two panes (PV and OUT), a recommendation sentence (SIMC proposal, fit verdict, "enter by hand"),
  a full-width read-only banner. Browser check on the step_test dataset (free window 5-45 min applied).
- New guard `i18nKeys.test.ts`: every static t("key") in the source must exist in en.json. It found five raw keys used as
  `aria-label` in the fuzzy rule editor (fixed) and one wrong key in the new window picker.
- 333 vitest tests, tsc and build green.

## UI remediation P3: valve stroke test screen (2026-10-20)
- Library: `valve_test.procedure_steps` (codes + params; `procedure_text` renders the same steps for the CLI, unchanged output),
  `reason_code`. Contract layer `loops/valve_payload.py` (plan validation, JSON-safe result, window analysis, in-memory CSV
  parser with delimiter/decimal-comma/BOM/ISO-time handling, 5 MB cap). Routes `api/valve_routes.py`. Review by a second
  model found 4 real bugs before install; tests then found numpy bools in JSON and a wrong plan-too-long test.
- UI: `ValveTestPage` wizard (reducer `valveTest.ts`, Stepper, settings form, safety checklist gate, printable procedure,
  record step with WindowPicker or CSV, result view), route sub `valve`, entry button on loop detail and on the next-action card.
- 381 vitest, loops+api pytest, ruff, mypy, build green; browser end-to-end run with a synthetic record.
- Still open: component tests for the valve components (only the reducer/logic has unit tests), P4-P7 of the plan.

## UI remediation P4 (part 1) and valve component tests (2026-10-20)
- TrendPane: range buttons (1h/8h/24h/all, only those that fit) with undo, MODE band, role labels and last value in the legend
  (`trendData.fittingPresets`, `presetRange`, `modeSpans`; en/pl/es keys). 430 vitest, tsc and build green; five valve component test files added.
- Still open in P4: LoopDetail does not fetch the mode series, so the MODE band is inactive; the band shades values that differ from
  the most frequent one because the mode encoding is not documented; knowledge editor part (OUT/PV range overrides, help, diff). Then P5-P7.

## UI remediation P4 completed (2026-10-20)
- MODE band shades manual mode (MAN=0, AUTO=1, CAS=2 from sim/core.py); LoopDetail fetches the mode series separately and non-fatally.
- Per-loop OUT/PV engineering-range overrides (`pv_eng_min/max`, `out_eng_min/max`) in project.json; the loop entry wins over the tag row;
  served by the knowledge API with the tag-row defaults; min >= max is refused (422). Editor: range group, "how to measure" help, post-save diff.
- 438 vitest, loops+api pytest, ruff green. Not checked in a browser; pl/es wording is machine-written and needs a native read.
- Next: P5 Trends tab, P6 Fuzzy Studio, P7 quality (Playwright, axe).

## UI remediation P7: quality (2026-10-20)
- Added `frontend/e2e/smoke.spec.ts` (Playwright + axe, 11 views x 1440/390 px, PL), `playwright.config.ts`, `npm run e2e`,
  `npm run lint` (ESLint 9 flat config, 40 lines / 4 params as warnings on files touched on 2026-10-20), `manualChunks`
  (react, uplot; largest chunk 205 kB), print CSS for report pages, `frontend/README.md` (how to run e2e).
- Browser run found: status chip contrast 4.3:1 (ok and unused colours darkened), unlabeled term inputs and shape selects in the
  fuzzy variable editor (aria-labels, en/pl/es keys), horizontal page scroll at 390 px on fuzzy and benefit pages
  (main area scrolls instead). Still open: English text from the backend fuzzy example rule base in the PL UI.

## Module 2: advisory supervisor (2026-10-21)
- Steps S1-S13 of `docs/archive/module2-plan.md` done: ADR 010, schemas, `supervisor/` (config, gates, advise, audit, replay), API routes, Advisor UI,
  no-write guard tests, exp27. Tests: supervisor + api pytest green, 483 vitest, 29 e2e.
- Review decisions: gate states from module 1 rows (missing row or not_assessed with `unknown` blocks; oscillating only warns), blocked advice is logged as
  a hold record without magnitude, replay logs blocked records only on gate transitions, replay_to_log is idempotent on advice_id.
- exp27: harness by an Opus subagent (different from the Sonnet authors of the package); first harness run exposed that the loop needs `delay_s` and
  `ultimate_period_s` or module 1 returns not_assessed and every gate closes (recorded in the README). Test seeds run once: E1-E5 met.

## Night 2026-10-22/23: integrating loops, anomaly detection, soft sensor, write-path skeleton

- Built: exp28 round 2 change in module 1 (IPDT reads OUT as a zero-order hold; dead-time interval from the SSE profile
  with an effective sample size; tuning uses the upper bound; experimental label). Module 3 `anomaly/` (PCA T2 and SPE,
  dynamic lags, stuck rule, CI guard test), Anomalies view, `anomaly_routes.py`, schema and example. Module 4 `softsensor/`
  (PLS on lagged tags, CV with gap = longest lag, validity flags, bias tracker, CI guard test), Soft sensor view,
  `softsensor_routes.py`, schema and example. ADR 011 (proposed) and the `gateway/` skeleton (12 strict xfail scenarios).
- exp28 (frozen; test seeds run once): round 1 I2 and I4 met; I1 accuracy 0.815 and I3 3 of 270 unsafe missed. Round 2
  (30101-30788): J1 0 of 276 unsafe, J3 and J4 met; J2 dead-time coverage 0.866 vs 0.90 missed.
- exp29 (frozen; test seeds run once): round 1 (quiet 29201-29260, faults 29301-29399) A2 drift 20/20, A4 0.864, A5 met;
  A1 2.13 false alarms per 24 h and A3 freeze 2/20 missed. Round 2 (29701-29899) B2 drift 19/20, B3 freeze 19/20,
  B4-B6 met; B1 1.79 per 24 h (max 4.33) missed.
- exp30 (frozen; test seeds 29501-29600): S1 31/34 normal records beat the last lab value (RMSE 0.857 vs 1.384), S2 validity
  0.988 and 0.975, S4 no leakage met; S3 drift flag 5/33 vs 5/34 normal missed.
- Bugs found by development seeds, fixed before any test seed:
  - an unquoted heredoc dropped a backslash in a schema;
  - two test files with the same name in different packages clashed in CI;
  - exp28: linear interpolation of OUT made a held step look like a ramp, so dead time came out too long (ZOH fixed it);
  - exp29: the SPE limit degenerated with lagged columns (Jackson-Mudholkar h0 about 0.05), so the limit is taken empirically;
  - exp29: a held signal (ore_hardness_est, updated every 30 min) was flagged as stuck; the threshold is now per tag,
    learned from fault-free training runs;
  - exp29: lagged history bridged time gaps of about 1 h; lags now break at gaps above 1.5 sample periods;
  - exp30: the validity domain came from the ~83 labelled rows and flagged about 20 % of in-range rows; it now uses all
    valid lagged training rows; the drift threshold was scaled to the stationary spread of the EWMA (k = 3).
- Lessons: development seeds found real library bugs in every module, so they were used for bugs only; test seeds ran
  once against frozen criteria; the misses are recorded as misses (exp28 J2, exp29 A1, A3 and B1, exp30 S3) and the UI and
  READMEs say what is not validated. No threshold was moved after a test run.
- Seeds spent: 1-20, 27001-27120, 28001-28999, 29001-29060, 29201-29399, 29401-29600, 29601-29899, 30001-30788.

### Anomaly round 3

Diagnosis of the round 2 miss (B1, 1.79 false alarms per 24 h): the false alarms were slow moisture and hardness excursions, so the limits fitted on a short training record were too tight out of sample. Masking setpoint moves cut nothing. The change is config only: alpha 0.999 and min_consecutive 15 (defaults in Python unchanged), tested once on new seeds 33001-33060 (quiet) and 33101-33199 (fault). The harness author found a seed collision (plant seeds of the new quiet records matched round 2 fault records) and fixed it by Amendment 1 before the first seed was run. Result: B1-B6 met (drift 16/20, freeze 18/20, false alarms 0.36 per 24 h); spikes, bad-quality and dropout rows are still not detected; limits fitted on a short training record remain the weakness. Simulation only.

## Plant import: whole PI wide files with a tag dictionary (2026-10-23, step 1 of the real-data plan)
- New path next to the single-loop intake: `loops/plant_import*.py` (dictionary + loop detection, local-time to UTC with
  `utc` / IANA zone (DST by zoneinfo) / fixed offset, reading with pyarrow, preview, dataset writer), `api/plant_import_routes.py`
  (raw-body upload up to 300 MB, preview, import, delete), Import view tab "Whole PI file" (en/pl/es), design in
  `docs/design/plant-import.md` and `plant-import-gui.md`.
- Original timestamps are kept (no resampling; gaps between test windows stay gaps); numeric 1/0 `#state` modes; test windows from the
  `test` column in `test_windows.json`; tag ids made schema-safe (`#` becomes `_`) identically in data, tags.json and project.json
  (a regression found by importing the real file: the first version wrote unsafe ids to project.json and the Loops view showed no loops).
- Bugs found on the real file and fixed: pyarrow column types, empty-label runs merged into test windows, DST changes at 24:00 local
  missed by the per-date offset cache, name-based detection mixing `.mv` with `.out`.
- Verified on the owner's files (outside the repo): the October file (7203 rows, 714 columns) imports in about 5 s into 28 detected loops
  (26 complete) and opens in the Loops view; the June file (47521 x 447) imports in about 30 s. Tests: 50 core, 13 API, 34 vitest, 3 e2e
  (axe at 1440 and 390 px); synthetic fixtures use neutral tag names.
- Delegation note: the code was written by Foremankit (DeepSeek) in one-file calls; the lead fixed integration bugs by hand.

## Module 1 triage on the first real loops + noise-driven valve warning (2026-10-23, step 2)
- Exploration, no pass/fail. Both real records (June 17 loops, October 26 loops) imported with the new path; the import now assumes
  OUT 0-100 % for loops whose OUT never leaves 0-100 and says so in a note (valve KPIs and saturation need the OUT range).
- Finding: level loops move the valve 55-350 %/h with 37-190 reversals/h, flow loops 1-37 %/h. New finding `noise_driven`
  (travel >= 50 %/h and reversals >= 30/h and no regular cycle; raises the status to warning) and worklist action
  `review_noise_response` (before the retuning advice, after manual/flatline/saturation/stiction/cycle/resolution). The thresholds
  are exploratory, chosen on these records (so not a validation); constants `NOISE_TRAVEL_PER_H`, `NOISE_REVERSALS_PER_H` in overview.py.
- Open: two suspicious "oscillating" flags (a 13 h period over a 5.5 day record, an 18 min period inside a step test); the per-loop
  table with names is outside the repo (owner's Drive). Tests: 15 new, 1873 pytest, 650 vitest, 47 e2e twice.

## Step analyzer (2026-10-23, step 3)
- Design `docs/design/step-analyzer.md`. `loops/step_events.py` (OUT steps in manual by two-sided median difference, SP steps in auto,
  windows clipped by segments, gaps and neighbours), `step_fit.py` (FOPDT and IPDT by variable projection on the grid of dead time and
  time constant, numpy only; SE of gain/slope from the linear covariance inflated for residual autocorrelation, SE of tau/theta from
  profile-SSE intervals), `step_consistency.py` (a row whose gain differs from the loop median by > max(3 MAD, 25 %) is downgraded),
  `step_analyzer.py` (payload with verdicts, test-window label, logbook match, thinned samples), `api/step_analyzer_routes.py`
  (`POST /datasets/{id}/steps`, one loop per call), Steps view (en/pl/es).
- Bugs found by running it on the October record: the median-difference peak was shifted by the block length and read size 0; the SNR
  looked at an empty slice; test labels compared relative with absolute times; a placeholder in the fit left dead code and a nonsense
  edge flag. First numbers: closed-loop SP steps of the flow loops give a small SE but a gain that varies by up to a factor 8 between
  steps of one loop, hence the consistency check (SE alone is not honest for closed-loop fits). Level loops: the October SP steps are
  too small (3 cm against 3-9 cm noise): all weak. Not a validation; no pass/fail criteria were set.
- Tests: 18 fit, 16 event, 16 payload, 11 API, 19 vitest, 3 e2e (axe).

## Step analyzer (2026-10-23, step 3)
- New view "Steps": `loops/step_events.py` (OUT steps in manual by two-sided median difference, SP steps in auto), `step_fit.py`
  (FOPDT / IPDT by variable projection, numpy only, standard errors from the linear covariance with autocorrelation inflation and
  profile-SSE intervals for tau and theta), `step_consistency.py` (repeated steps must agree: `inconsistent_with_median`),
  `step_analyzer.py` (payload with test-window and logbook alignment), `POST /datasets/{id}/steps`, GUI + en/pl/es. Design: `docs/design/step-analyzer.md`.
- Bugs found by running it on the real records: median-difference plateau gave wrong event index and size; SNR window indexing
  returned 0; test labels compared relative with absolute time. Synthetic recovery: K 0.795 (true 0.8), tau 113 (120).
- Real finding (October, flow loops, closed-loop SP steps): SE alone is optimistic (gain 0.8 to 9 between steps of one loop), hence
  the consistency check and the `closed_loop` flag; level loops' SP steps are weak (SNR 2-5). Open-loop OUT steps exist only on
  one manual loop. Pump-speed steps are not loop records: they need step 4.
- Tests: 61 Python, 19+ vitest, 3 e2e (axe 1440/390). Whole suite 1934 pytest, 679 vitest, 50 e2e twice.

## Anomaly smoke test on four weeks of real normal operation (2026-10-23, step 5; exploration, no pass/fail)
- Data: the owner's A4 package (1 min, 11.09-09.10), 39 process tags, round-3 settings. Not a false-alarm estimate (no event log).
- 3 weeks of training then the 4th week: 0.29 events/24 h, 1.5 % of time flagged; 2 weeks then week 3: 1.0/24 h, 21 %;
  1 week then week 2: 94 % flagged (operating point moves between weeks). In-sample 0.7-0.9/24 h.
- Data trap: a tag linearly interpolated over a long archive gap (same variance in two weeks, mean falling 1514 -> 935) made the
  detector flag 93-100 % of weeks 3 and 4. Idea (open): mark a tag with a long exact linear ramp as unreliable in the anomaly and import views.
- Details with tag names are in the owner's Drive (SMOKE_anomalie_A4_2026-10-23.txt), not in the repo.

## Feed-disturbance identification (2026-10-23, step 4; analysis only)
- `tools/driver_response.py`: steps of one driver tag (a pump speed) found with step_events, outputs fitted with step_fit; generic, no tag names.
- On the 11 October pump steps (15 steps of 1-3 pp): feed flow gain 145 +- 12 m3/h per pp, dead time about 5 s (grid), time constant 15 +- 6 s;
  consistent in 11 of 15 steps. Sump level and level-loop OUTs respond through closed loops, so no process model comes out of them
  (they need an open-loop test or known controller tunings). Plant tag names stay in the owner's Drive report.
- The plant import tag cap was raised to 1200 because the first cap (file order) dropped the pump speed tag.

## Lab/Courier data, sentinel masking, possible-ramp warning (2026-10-23 evening, handoff items a and b)
- Owner package A4/A5/B1/B4 read in full (all files of the Drive folder `L1_step_tests_2026` were listed first; the weekly report PDF on the
  Drive root is context only). New library code: `softsensor/long_format.py` (long-format lab/analyser CSV loader, zero-order-hold resample,
  `LabResults` adapter), `anomaly/ramp_detect.py` (exact linear ramps), tools `tools/lab_extract.py` (one tag to the lab-upload CSV) and
  `tools/analyzer_vs_lab.py` (alignment scan + one-feature calibration with blocked CV). Tests for all of them.
- Data trap found: Courier tags write -9999 for "no result"; read as numbers it ruined window means (mean -180, sd 1300) and the A4 interpolation
  blended it into ramps. The plant import now reads exactly -9999 as missing (`HISTORIAN_SENTINEL`); blended values need a validity floor (tools: `--min-valid`).
- Findings (numbers only; detail in the owner's Drive report `SOFTSENSOR_lab_courier_2026-10-23.txt`): the lab composite stamp is the END of the
  6 h window plus up to about 1 h (best window end -0.5 to -1 h before the stamp, r 0.87-0.90, flat optimum); Courier vs lab calibration CV R2 0.76 (Cu conc.),
  0.78 (Mo conc.), 0.46-0.72 for tails; PLS on 808 process columns has NEGATIVE blocked-CV R2 at every alignment (110 samples, persistence also negative): no
  process-only soft sensor from four weeks; useful soft sensor needs the analyser as input. Exploration, no pass/fail criteria.
- Possible-ramp warning: detector run on A4 found 152 tags with a straight stretch of 2 h or more, 78 with 6 h or more; many are counters, timers, hour meters
  and slow PI-compressed signals, so precision against real archive gaps is unknown. The anomaly fit/scan responses carry `unreliable_tags` (ramp of 6 h or more,
  tags straight over 90 % of the window skipped as counters), the Anomalies scan shows a "possibly unreliable" warning (en/pl/es). Warning, not a verdict.
- CI had failed since the step-analyzer push: `test_static_limits_and_sha_are_bit_identical_to_before` compared floats to 1e-16 and a hash of float JSON,
  which differ by 1e-14 between platforms. Now a relative 1e-9 comparison (CI green again at f3a3be6).
- Native review of the Spanish and Polish UI strings (commit 42d00c4): delegated to foremankit (DeepSeek v4-pro) as a patch of changed
  keys, merged with a JSON key/placeholder guard; about 128 es and 39 pl real changes. Terminology unified (PV = wielkość regulowana /
  variable de proceso; OUT = sygnał sterujący / señal de control; tuning = strojenie / sintonización). The lead corrected one wrong term:
  self-regulating must be "samowyrównujący" (an object property), not "samopoziomująca" (self-leveling). ESLint size limits are 24 warnings
  (0 errors) and are deliberately warnings; the 23 max-lines refactors are deferred (low visible value, e2e regression risk).
- B4 raw events (LV-10201 A/B): command-to-position latency median 2-3 s (limited by the 3 s record resolution), position stops 0.4-0.7 % short of the command
  in the direction of motion on valve A; same order as the 0.4 % PI compression deviation, so it is not a backlash measurement.

## 2026-10-27: product reset, Phase 0 cleanup

- `docs/PRODUCT.md` (and `docs/PRODUCT.pl.md`) replaces `docs/PROJECT_DESIGN.md` as the product definition; the old design files carry a historical banner.
- ADR 012 (writes are a product capability, Write Gateway) added; ADR 010 and ADR 011 marked "superseded in part". Their safety design still applies.
- Guard tests reworded to "only the gateway writes" (logic unchanged); the README label is now "Writes only through the gateway".
- `experiments/README.md` added as an index with status per line; closed lines stay in place. exp31 is marked a validation case, not a product feature.
- One-off plans moved to `docs/archive/`; developer tools moved to `dev/`.
- Plant-derived tools are labelled for absorption into the product (Phase 4 and Phase 7).
- CLAUDE.md item 11: the anti-drift rule (every task names its module and phase in `docs/PRODUCT.md`; a new top-level element needs owner approval).
- Two pre-existing ruff E501 errors fixed (`plant_import.py`, `test_plant_import_settings.py`), no logic change.

## 2026-10-27: example site file for the generic concentrator

- Added `docs/examples/generic_concentrator/_site/site.json`: synthetic generic concentrator site file (primary crusher, screen, secondary crusher with recycle, ball mill, sump + pump, hydrocyclone with recycle, rougher flotation; 75 tags, 17 PID loops).
- Preliminary: written before `schemas/site.schema.json` (#36) exists; tags carry min/max fields not in the #36 plan, to be decided when the schema is written. Use as the example root for the #36 site loader tests and as the flowsheet reference for the RougherSim profile.
- Phase 1 (`docs/PHASE1_PLAN.md`), module: online foundation.
