# Handoff (2026-10-19, after the night session): module 1 polished and closed for now

Written for the next session (Claude or the owner). Per-step details are in `docs/IMPLEMENTATION_LOG.md` (last
section) and in `experiments/exp21..exp26`. Everything is pushed to `main`; CI was green after 5e43ff1.

## State of module 1 (loop monitoring and tuning) in one table

| Area | What ships | Evidence | Claim limit |
| --- | --- | --- | --- |
| KPI triage | service factor, saturation, flatline, Harris (needs delay), valve travel / reversals / quantisation / sizing, "not assessed" when knowledge is missing | exp18, exp19 (real SACAC/ISDB, exploratory) | thresholds other than quantisation >= 1 and 15/85 % sizing not validated on real loops |
| Oscillation without limits | ACF regularity (Thornhill 2003) + our noise band and 7-crossing rule (detector A) | exp20-24 synthetic | misses records with < 8 cycles; up to 9 % false alarms on fast noise with 1000+ samples; the finding says so |
| Stiction | frozen weak hint (C4a) asking for a valve test | exp15/16 | never a diagnosis |
| Valve stroke test | plan, operator procedure, analysis of a recorded test, CLI | exp25 simulated: deadband within 0.25 % in 100 % (no load) | no real test record yet |
| Worklist | next action + priority rank per loop | rule only | needs the blind engineer review |
| Tuning | SIMC/AMIGO from bump tests, vendor forms (Siemens verified, ABB TI unit open), tuning from history | exp03-08, exp17, exp26 | history tuning rarely applies on real data (exp17); level loops: confident advice safe in simulation (exp26, 12/12), low confidence now gives no settings |
| Sluggish loops | nothing (idle index tried and stopped, exp22) | exp22 design exploration | |

## Decisions made tonight (and why)

1. **ACF-variant line closed.** Three frozen rounds; the best variant (I: biased ACF + peak gate 3 sigma) is better
   than the shipped A on false alarms (worst cell 5/400 vs 36/400) and on short records (S 79 % vs 50 %), but
   missed the long-record tolerance by 2 runs of 3600 in the last, announced-final round (exp24). Rule kept,
   nothing shipped. If the owner wants I anyway, that is an owner decision against a documented miss, not a
   result: the change would be `AcfConfig` defaults (min_crossings 5, max_lag_fraction 0.75, peak_z 3.0).
2. **Idle index not shipped** (exp22): it did not separate sluggish loops in simulation.
3. **Valve stroke test is the stiction answer**: a procedure for the operator, nothing writes to a DCS.

## Next steps, in the order I would take them

1. **One real valve stroke test** on a flow loop (owner): `python -m crosscut_loops.valve_test_cli plan
   --op-start <current OP> --dwell-s <4-6 x (tau + theta)>`, log t_s, op, pv to CSV, then `... analyze file.csv`
   with the same arguments. This is the first real evidence for anything stiction-related.
2. **Blind review of the worklist** by an independent control engineer on about 20 loops (Kendall tau >= 0.5, >= 80 %
   agreement on the next action). The owner is the domain expert but not independent (the rules' intent came from them).
3. **Frontend** (done 2026-10-20): worklist overview, valve/stiction numbers, not-assessed notice, loop-data editor and
   tuning comparison are in; see IMPLEMENTATION_LOG "Loop monitoring and tuning screens" for what is still open
   (valve stroke test screen, free tuning window, Playwright smoke test).
4. Sluggish-loop detection, if wanted: Hagglund's load-episode detection or Visioli's area index on setpoint steps
   (exp22 has a generator and harness ready).
5. Module 2 planning can start: module 1 has no open blocking item on the assistant side.

## Owner to-do (still open)

1. UaExpert check (`python opcua/examples/live_demo.py`, `docs/LIVE_DEMO.md`), one line in the log.
2. ADR 008 review (AGPL-3.0, `docs/adr/`).
3. ABB TI/TD unit: one real PidCC loop export (optional).
4. Install Node.js LTS (`winget install OpenJS.NodeJS.LTS`, then `npm ci` in `frontend/`). `gh` is installed now.
5. Whether to ask SACAC / ISDB providers about publishing derived tables.

## Working rules that held

- Every experiment: protocol frozen and committed before any run, generator written by a different model than the
  detector, one run, amendments only before the first dev/test seed and written down. Spent seed ranges are listed
  in each README; exp24 lists all ACF ones.
- Delegation: `delegate` output lands in `<Python Scripts>/.agent-out/`; `verify` runs the system Python without
  pytest, so install by hand and test in `.venv`. Generators went to Sonnet subagents (different family from the
  DeepSeek-written detectors). Every delegated file was read before commit; bugs found this way tonight: first-leg
  deadband bracket, resolution order, idle-index gain sign, exp26 judgement window, test helper iteration.
- Gates before every commit: `.venv\Scripts\python -m ruff check .`, `-m mypy sim loops/src api/src connectors/src`,
  `-m pytest`. Files in `loops/` use CRLF in the working tree; PowerShell `.Replace` with `\n` silently misses them,
  use the Edit tool.
- Third-party data (SACAC, ISDB): never committed; see `docs/PROVENANCE.md`.

## Issues found by the 2026-10-19 code review: all fixed

Found while cleaning the code, then fixed with a test that fails on the old code (except the renames).

| Where | Issue | Fix |
| --- | --- | --- |
| `api/downsample.py` | One NaN in a bucket gave NaN for min, max and mean of the whole bucket | NaN and infinite samples are skipped; only a bucket with no finite sample is a gap |
| `sim/pid.py` | In MAN `_d` was updated but `_prev_pv` not: a phantom derivative released as a jump (+33 output units in the test) on the second AUTO step | The measurement is remembered in both modes. All 12 simulator scenarios keep their dataset hashes, so recorded data is unaffected |
| `fuzzy/backtest.py` | A jump directly followed by a jump the other way was summed to one move of delta ~0 | Runs are split at sign changes |
| `sim/faults.py` | A second freeze of the same tag reused the first frozen value | Freeze memory is keyed by the fault |
| `opcua/server.py` | Unreachable Int64 branch in `_write` | Removed |
| `fuzzy/library.py`, `versions.py` | `$` accepted a trailing newline in system ids (file names) and version ids | `fullmatch` |
| `loops/monitor.py` | Oscillation sentence was built for every loop; ACF method without a period would raise TypeError for any class | Sentences are built lazily |
| `mill_circuit._init_paths` | Misleading names `gain_initial`, `variance` | `base_gain`, `hardness_slope` |
| `api/fuzzy_routes.BacktestRequest` | Repeated the `BacktestSettings` defaults | Defaults read from `BacktestSettings` |
| `csv_import`, `sim/run.py` | Broad `except Exception`; missing git executable not handled | Narrowed, with tests |

Not touched on purpose: `experiments/` (about 830 `codecheck` findings; frozen records of runs, hashes in the READMEs).
Tests were cleaned too (0 findings, no test or assertion removed, vacuous tests strengthened).
