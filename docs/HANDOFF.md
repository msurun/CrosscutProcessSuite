# Handoff (2026-10-23, night): modules 1-4 built, lab/Courier data analysed, sentinel + ramp traps handled

Written for the next session (Claude or the owner). Per-step details: `docs/IMPLEMENTATION_LOG.md` (last section), the
experiment READMEs `experiments/exp27..exp30` and the owner tasks in `docs/OWNER_TASKS.md`. Nothing in the repository
writes to a plant.

## State of the modules

| Module | What ships | Evidence | Claim limit |
| --- | --- | --- | --- |
| 1 Loop monitoring and tuning | KPI triage, ACF oscillation test, valve checks and stroke test, worklist, SIMC/AMIGO tuning, history tuning, integrating-loop tuning (experimental), step test intake (CLI `step_test_cli` and Import view), padded suggested windows for level loops | exp18-26, exp28 | simulation; first real level data was refused by the wizard (see Real data); worklist needs blind review |
| 2 Advisory supervisor | fuzzy gates from module 1, advice, hash-chained log, Advisor view | exp27 E1-E5 met | ADR 010 proposed; simulated operator; `who` not authenticated |
| 3 Anomaly detection | PCA T2 and SPE, lagged columns, stuck-sensor rule, Anomalies view | exp29 round 3: B1-B6 met (drift 16/20, freeze 18/20, 0.36 false alarms per 24 h) | simulation only; spikes and bad-quality rows not detected; false alarm rate not known on real data |
| 4 Soft sensor | PLS on lagged tags, validity flags, bias tracker, Soft sensor view | exp30: beats last lab value 31/34; validity 0.988; drift flag missed | simulation only; drift flag not reliable (5/33 vs 5/34) |
| ADR 011 write path | proposed design, `gateway/` skeleton with 12 strict-xfail scenarios and static no-write guards | design only | not accepted; nothing can write to a plant |

Web UI views: Trends, Loops, Fuzzy, Advisor, Anomalies, Soft sensor, Import. Tests: pytest (whole repo, ruff clean), vitest, and
`npm run e2e:all` in `frontend/` (builds its own data root and servers; 44 Playwright tests with axe, twice in a row).

## Experiments (frozen protocols, test seeds run once; misses are recorded, never retuned)

| Experiment | Round | Met | Missed |
| --- | --- | --- | --- |
| exp27 supervisor | 1 | E1-E5 | none |
| exp28 integrating step test | 1 | I2, I4 | I1 accuracy 0.815; I3 3 of 270 unsafe |
| exp28 | 2 | J1 (0 of 276 unsafe), J3, J4 | J2 dead-time interval coverage 0.866 (target 0.90) |
| exp29 anomaly | 1 | A2, A4, A5 | A1 2.13 false alarms per 24 h; A3 freeze 2/20 |
| exp29 | 2 | B2-B6 | B1 1.79 per 24 h |
| exp29 | 3 | B1-B6 (alpha 0.999, min_consecutive 15) | none |
| exp30 soft sensor | 1 | S1, S2, S4 | S3 drift flag |

Seeds spent: 1-20, 27001-27120, 28001-28999, 29001-29060, 29201-29399, 29401-29600, 29601-29899, 30001-30788, 33001-33060,
33101-33199 (plant seeds 33001-35199). Next unused: 35200 and up (exp29), 30801 and up (exp30). A new round needs a new frozen
protocol first.

## Real plant data (received 2026-10-23, confidential, never in the repo)

The owner supplied PI extracts of a flotation line at 10 s (stored in the owner's Google Drive folder `L1_step_tests_2026`, with a
README, tag dictionaries and `POTRZEBY_DANYCH_Crosscut.txt` listing what is still needed). The assistant memory has the detail
(tag names, loop numbers, times); this file keeps only what is safe to publish:

- Timestamps are LOCAL plant time without a zone (June UTC-4, October UTC-3), not UTC. Level signals are in cm. Mode flags are
  numeric 1/0 in the wide CSV (raw parquet had text only). Dictionaries give description, unit, signal type, loop, cell.
- Level (integrating) loops: every tuning window of the June record and of the October windows was refused by the wizard
  (PV clipped at its upper limit, OUT moves smaller than noise and valve dead band of about 3 %, many moves are closed-loop setpoint steps,
  no clean open-loop step, controller tunings are not in PI). Correct behaviour; no settings were produced. Needed: one open-loop
  OUT step test with a moving valve and PV below the clip, plus controller tunings from the DCS.
- Flow loops (air): closed-loop setpoint steps of 40 m3/h and more identify well with the repo closed-loop IV; steps of 20 are
  too small against noise. Feed pump speed steps give a clean feed-flow response and level disturbance; air steps gave no
  detectable effect on levels.
- Module 1 on these loops: level loops show hundreds of percent valve travel per hour and 76-170 valve reversals per hour (noise-driven
  control action) but no flag (status "not assessed"; needs delay and amplitude knowledge): candidate improvement.
- A logbook of the tests (9 and 11 October, local time) matches the data except two events (a different pair of cells at one
  time, one event 14 minutes later); 10 October (second session, air and level) has no logbook.

## Lab / Courier package (A4/A5/B4, analysed 2026-10-23 night; numbers only, detail in the owner's Drive report `SOFTSENSOR_lab_courier_2026-10-23.txt`)

- Data traps found and handled: Courier analyser tags write -9999 for "no result" and the 1-min A4 interpolation blended it into
  window means and ramps (read as numbers, one Courier column had mean -180, sd 1300). The plant import now reads exactly -9999 as
  missing; blended values need a floor (tools take `--min-valid`).
- Lab composite stamp is the END of the 6 h window plus up to about 1 h: the analyser-vs-lab window correlation peaks at -0.5 to -1 h
  (r 0.87-0.90, flat optimum). Courier vs lab one-feature calibration, 107 composites, blocked CV: R2 0.76 (Cu conc.), 0.78 (Mo conc.),
  0.46-0.72 for the low-grade tails; slopes near 1 for the Cu/Mo concentrate grades.
- PLS on 808 process columns has NEGATIVE blocked-CV R2 at every alignment (110 samples, 4 weeks): no process-only soft sensor; a useful
  soft sensor must feed the Courier analyser with lab bias correction. Exploration, no pass/fail criteria.
- "Long exact linear ramp" detector run on A4 found 152 tags with a straight stretch >= 2 h, 78 >= 6 h; many are counters, timers, hour
  meters and slow PI-compressed signals, so precision against real archive gaps is unknown. Shipped as a "possibly unreliable" warning in
  the Anomalies scan (ramp >= 6 h; tags straight over 90 % of the window are skipped as counters), not a verdict.
- B4 raw events (valve LV-10201 A/B): command-to-position latency median 2-3 s (capped by the 3 s record resolution); the position stops
  0.4-0.7 % short of the command in the direction of motion on valve A, the same order as the 0.4 % PI compression deviation, so it is
  not a backlash measurement. A real valve stroke test is still needed.

## Decisions

1. Integrating (level) loops: settings use the upper bound of the dead-time interval and carry the experimental label.
2. Misses ship visibly, thresholds are not moved: the anomaly view says false alarms are not validated; the soft sensor marks the
   drift flag as not validated.
3. ADR 011 is a design only. No write code and no connection to a control system until the owner accepts it.
4. Module 1 decisions stand: the ACF-variant line is closed; the idle index is not shipped; the valve stroke test is the stiction answer.
5. Real data stays outside the repository and is never sent to external services. Reports may quote numbers, not bulk data.

## Next steps (the owner approved: work without stops, push to main after each verified step, never force)

Done 2026-10-23 evening (details in `docs/IMPLEMENTATION_LOG.md`, last four sections):
1. Whole PI file import with the tag dictionary (Import view tab "Whole PI file", `docs/design/plant-import.md`).
2. Module 1 triage on the real loops and the `noise_driven` warning + worklist advice (thresholds exploratory, owner to judge).
3. Step analyzer view "Steps" (`docs/design/step-analyzer.md`): OUT steps in manual and SP steps in auto, FOPDT/IPDT with SEs, consistency check.
4. Feed-disturbance identification: `tools/driver_response.py`; pump speed to feed flow 145 +- 12 m3/h per pp, tau 15 s; level channels need an open-loop test.
5. Anomaly smoke test on four weeks of real normal operation: 3 weeks of training gives about 0.3 events/24 h; 1 week gives 94 % flagged; a tag
   linearly interpolated over an archive gap fooled the detector (not a false-alarm estimate).

Done 2026-10-23 night (details in `docs/IMPLEMENTATION_LOG.md`, last section; commit `87cabf0`):
6. Lab/Courier data: `softsensor/long_format.py` (long-format loader) + `tools/lab_extract.py` and `tools/analyzer_vs_lab.py`
   (alignment scan + one-feature blocked-CV calibration); `-9999` sentinel masked in the plant import. Findings above.
7. Possible-ramp warning: `anomaly/ramp_detect.py`, `unreliable_tags` in the anomaly fit/scan responses, warning in the Anomalies scan (en/pl/es).
8. Steps view: load the logbook from a CSV (the `dia,hora,...` transcription) and a driver/output tag-pair target (a stepped pump speed
   and the responding flow) in addition to a control loop.
9. CI fix: the PCA limits test compares to numerical precision (float JSON hash was not portable across platforms; CI green again).

Open, in suggested order:
a. Confirm the lab stamp meaning in STARLIMS (end of the composite plus up to 1 h?) and the Courier -9999 meaning; the analyser
   latency is still unmeasured (assumed 0).
b. Level loops in closed loop (setpoint steps) only after the controller tunings arrive (A2 in the owner's list).
c. Review of ADR 008, 010, 011 with the owner; native review of the machine-written pl/es strings (now also plant import and Steps); one real valve
   stroke test; the blind worklist review; UI cosmetics (ESLint size warnings, print CSS).
d. The possible-ramp warning is exploratory: precision against real archive gaps is unknown. Ask the owner for a list of tags with
   PI archive gaps in those weeks to measure it; counters/timers also draw straight lines.

Not possible yet (missing data): advisor on real operator behaviour, MPC identification of quality variables, any write path. A process-only
soft sensor of lab grades is not achievable from four weeks (110 samples); it needs the Courier analyser as input plus months of data.

## Owner to-do

The full list with what to bring back is in [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md) and, for the data collection, in the
owner's Drive file `POTRZEBY_DANYCH_Crosscut.txt` (priorities A, B, C). Short form: controller tunings from the DCS; an open-loop
level step test; answers about the level sensor range and clip, the valve behaviour in manual and the windup; four weeks of normal
operation with an event log; laboratory and online analyser data; the 10 October logbook; a real valve stroke test; the blind worklist
review; UaExpert check; ADR reviews.

## Working rules that held

- Every experiment: protocol frozen and committed before any run, generator written by a different model than the detector, one run on
  test seeds, amendments only before the first development seed and written down. Development seeds are for bugs only. A seed collision
  between derived plant seeds was found by the harness author once: check the derived seeds of earlier rounds.
- Delegation: Sonnet subagents write modules, Opus subagents write harnesses and plans; the lead reads every file and re-derives the math.
  A session rate limit can stop agents mid-task: resume them with SendMessage. Subagents sometimes claim the repo is not under git and run
  formatters over untouched files; say so in the prompt.
- Gates before every commit: `.venv\Scripts\python -m ruff check .`, `-m pytest` (whole repo collects: test file basenames must be unique),
  `npx vitest run`, `npx tsc --noEmit`, `npm run build`, `npm run e2e:all`.
- Files in `loops/` may use CRLF in the working tree; use the Edit tool, not shell replace. JSON written by shell heredocs loses backslashes:
  use the Write or Edit tool for schemas.
- Third-party data (SACAC, ISDB) and the owner's plant data: never committed; see `docs/PROVENANCE.md`.
