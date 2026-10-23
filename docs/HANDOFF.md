# Handoff (2026-10-23): state after the night of 2026-10-22/23

Written for the next session (Claude or the owner). Per-step details: `docs/IMPLEMENTATION_LOG.md` (last section), the
experiment READMEs `experiments/exp27..exp30` and the owner tasks in `docs/OWNER_TASKS.md`. Nothing in the repository
writes to a plant.

## State of the modules

| Module | What ships | Evidence | Claim limit |
| --- | --- | --- | --- |
| 1 Loop monitoring and tuning | KPI triage, ACF oscillation test, valve checks and stroke test, worklist, SIMC/AMIGO tuning, history tuning, integrating-loop tuning (experimental) | exp18-26, exp28 | simulation; thresholds not validated on real loops; worklist needs blind review; integrating tuning simulated only |
| 2 Advisory supervisor | fuzzy gates from module 1, advice, hash-chained log, Advisor view | exp27 E1-E5 met | ADR 010 proposed; simulated operator; no plant data; `who` not authenticated |
| 3 Anomaly detection | PCA T2 and SPE, lagged columns, stuck-sensor rule, Anomalies view | exp29 round 2: drift 19/20, freeze 19/20, false alarms 1.79 per 24 h (missed) | simulation only; spikes and bad-quality rows not detected; not validated on real data |
| 4 Soft sensor | PLS on lagged tags, validity flags, bias tracker, Soft sensor view | exp30: beats last lab value 31/34; validity 0.988; drift flag missed | simulation only; drift flag not reliable (5/33 vs 5/34); not validated on a real plant |
| ADR 011 write path | proposed design, `gateway/` skeleton with 12 strict-xfail scenarios | design only | not accepted; nothing can write to a plant; owner review pending |

## Experiments of the night (frozen protocols, test seeds run once)

| Experiment | Round | Met | Missed |
| --- | --- | --- | --- |
| exp28 integrating step test | 1 | I2 blocking, I4 looks_integrating | I1 accuracy 0.815 among accepted; I3 3 of 270 unsafe |
| exp28 | 2 | J1 0 of 276 unsafe, J3, J4 | J2 dead-time interval covers 0.866 (target 0.90) |
| exp29 anomaly detection | 1 | A2 drift 20/20, A4 tag in top 2 0.864, A5 no imputation | A1 2.13 false alarms per 24 h; A3 freeze 2/20 |
| exp29 | 2 | B2 drift 19/20, B3 freeze 19/20, B4, B5, B6 | B1 1.79 false alarms per 24 h (max 4.33) |
| exp30 soft sensor | 1 | S1 31/34 beat last lab value, S2 validity, S4 no leakage | S3 drift flag 5/33 vs 5/34 normal |

Seeds spent: 1-20, 27001-27120, 28001-28999, 29001-29060, 29201-29399, 29401-29600, 29601-29899, 30001-30788.
Next unused: 29900 and up (exp29), 30801 and up (exp30). A new round needs a new frozen protocol first.

## Decisions

1. Integrating (level) loops: the settings use the upper bound of the dead-time interval and carry the experimental label.
   In simulation 0 of 276 accepted fits were unsafe in round 2. Not validated on a real loop.
2. Misses ship visibly, thresholds are not moved: the anomaly view says false alarms are not validated; the soft sensor
   marks the drift flag as not validated.
3. ADR 011 is a design only. No write code and no connection to a control system until the owner accepts it.
4. Module 1 decisions still stand: the ACF-variant line is closed (the rule is kept; the better variant would be an owner
   decision against a documented miss, see `AcfConfig` defaults in the log); the idle index is not shipped; the valve
   stroke test is the stiction answer.

## Next steps, in the order I would take them

1. Review ADR 011 with the owner before any implementation; its open points are listed in the ADR.
2. If the owner supplies the flotation cell level step test (`docs/OWNER_TASKS.md`), run it through the tuning wizard as
   exploration. No pass/fail.
3. Candidate follow-ups, each only with a new frozen protocol and new seeds: anomaly round 3 (smoothing the statistics,
   excluding setpoint-move windows); soft sensor drift detector round (CUSUM on lab residuals, longer horizon); UI polish.
4. Native review of the machine-written pl/es strings, including the new views.
5. Module 1 items still open: one real valve stroke test and the blind worklist review (owner); sluggish-loop detection
   if wanted (exp22 harness ready). UI cosmetics: the PL page shows English text from the backend example rule base;
   fuzzy terms are raw ids; 26 ESLint size warnings; print CSS not checked visually; per-tag range editing UI.

## Owner to-do

The full list, with what to bring back for each item, is in [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md). Still open from the
earlier list:

1. UaExpert check (`python opcua/examples/live_demo.py`, `docs/LIVE_DEMO.md`), one line in the log.
2. ADR 008 review (AGPL-3.0) and ADR 010 and 011 reviews (`docs/adr/`).
3. ABB TI/TD unit: one real PidCC loop export (optional).
4. Whether to ask SACAC / ISDB providers about publishing derived tables.

## Working rules that held

- Every experiment: protocol frozen and committed before any run, generator written by a different model than the
  detector, one run on test seeds, amendments only before the first development seed and written down. Development
  seeds are for bugs only; the misses are recorded as misses.
- Delegation: `delegate` output lands in `<Python Scripts>/.agent-out/`; `verify` runs the system Python without
  pytest, so install by hand and test in `.venv`. Every delegated file was read before commit.
- Gates before every commit: `.venv\Scripts\python -m ruff check .`, `-m mypy sim loops/src api/src connectors/src`,
  `-m pytest`. Files in `loops/` use CRLF in the working tree; PowerShell `.Replace` with `\n` silently misses them, use the Edit tool.
- Third-party data (SACAC, ISDB): never committed; see `docs/PROVENANCE.md`.
