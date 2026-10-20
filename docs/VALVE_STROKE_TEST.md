# Guided valve stroke test

A procedure and an analysis tool for measuring the **deadband** and **resolution** of a control valve
from a deliberate step test. For a control or process engineer who is about to run the first real test.

## Purpose

Passive stiction detection from normal operating data (the closed exp15/16 line) only gives a weak hint.
This test makes the valve move in small, known steps and reads the response, so deadband and resolution
can be bracketed with a stated uncertainty.

**Advisory only.** Nothing here writes to the control system. The operator performs every step by hand;
the tool prints the steps and later analyses the recorded CSV.

Definitions (wording after ANSI/ISA-75.25.01 and ISA-TR75.25.02 as recalled; the standards were not read):

- **Deadband (reversal):** the output travel after a direction reversal before the valve visibly moves.
- **Resolution:** the smallest same-direction output step that visibly moves the valve.

PV is used as a proxy for valve position (no positioner feedback assumed).

## Before you start

- [ ] Choose a loop whose process can take a **+8 % / -8 % output swing** (the default plan moves OP by
      about that much) without harm to product, safety or the environment.
- [ ] The loop will be in **MANUAL for the whole test**. No cascade, no APC, no auto moves.
- [ ] Know roughly **tau + theta** of the loop.
- [ ] Set the **dwell per step to about 4-6 x (tau + theta)**. The analysis uses only the last third of
      each dwell as the steady value, so a short dwell gives a bad estimate.
- [ ] Check how long the test lasts (the CLI prints the total; see below) and agree it with the
      shift supervisor. 49 dwells of 10 s are about 9 minutes; with a 60 s dwell the test takes 49 minutes.
- [ ] Decide an **abort band on PV** in engineering units and note it; pass it as `--pv-band`.

## Getting the plan

```
python -m crosscut_loops.valve_test_cli plan --op-start <current OP %> --dwell-s <seconds> \
    [--pv-band <units>] [--op-low 0] [--op-high 100]
```

- `--op-start` is the current output in % of span, required.
- `--dwell-s` is the dwell per step in seconds, required.
- `--op-low` / `--op-high` are the output limits in % of span (default 0 and 100). The plan is rejected if
  any step target leaves this range.
- `--pv-band` is the abort band in PV units (engineering units). Without it, the printed abort rule has no
  numeric PV limit.

The command prints:

- **Numbered operator steps** in plain English: put the loop in MANUAL, the abort rule, set OP to the start
  and wait one dwell, then each step ("Set the output to X% and wait N seconds"), then return to
  `op_start` and put the loop back in AUTO.
- **Total test time** in whole minutes (dwell times number of steps + 1, rounded up).

Plan structure (defaults, from the code):

- Step sizes **1 %** then **0.25 %** of span, each with its own block of legs.
- For each size, the legs are **up, down, up** (two reversals per size), starting from the OP reached by
  the previous size. First size: 4 steps per leg, second size: 12 steps per leg — **48 steps in total**.
- All steps share the same dwell.

## During the test

- Execute the steps **as printed**, one at a time. If your controller rate-limits the output, a step may
  come out as a ramp — that is fine, but **still hold the full dwell** before the next step.
- **Log time, OP and PV at a fixed period** to a CSV file. **1 s is recommended.**
- The CSV needs a **header row with `t_s,op,pv`** (or your own column names, see `--time-col` etc.
  below). Comma, semicolon or tab separated; UTF-8 with or without BOM is accepted.
- **No gaps and no NaN.** The analysis rejects non-finite values and an empty record. Write one row per
  period for the whole test.
- **Do not touch anything else on the loop** (setpoints, other loops in cascade, tuning) while the test
  runs.

## Analysing the record

```
python -m crosscut_loops.valve_test_cli analyze record.csv --op-start <same> --dwell-s <same> \
    [--pv-band <same>] [--op-low 0] [--op-high 100] \
    [--time-col t_s] [--op-col op] [--pv-col pv]
```

Use **the same plan options** as for `plan` (start OP, dwell, limits, band). The column flags only matter
if your CSV uses other names.

Each printed line:

| Line | Meaning |
| --- | --- |
| `Gain` | Process gain K = dPV/dOP, in PV units per % of span, from the 1 % steps that are not first after a reversal. `not identifiable` if fewer than two qualify. |
| `PV noise sigma` | Estimated PV noise (one sigma) in PV units, from the scatter within the steady part of each segment. |
| `Deadband` | A **bracket** `(low, high] % of span` on the deadband, taken from the finest step size that showed a move after a reversal. Or a **lower bound** `> X % (no move after a reversal)` when no leg showed a visible move. Or `not identifiable`. |
| `Resolution` | `<= s %` of span: the smallest step size that moved the valve in at least 75 % of qualifying same-direction steps. `not certified` if no size meets that. This is an upper bound, not a measured value. |
| `PV left the abort band` | `yes` if any PV during the test moved more than `--pv-band` from its starting value. |
| `Reason` | Present only when a result is incomplete. |
| (last line) | Reminder that the result is synthetic validation only (exp25); PV is a proxy. |

## How to read the result

These are **rules of thumb, not validated here**:

- A deadband **above about 1 % of span on a flow valve usually matters** at the operating point; below
  that it is often tolerable but worth tracking across tests.
- Compare the deadband to the **typical OP movement** the loop makes in automatic: if the deadband is a
  large fraction of that movement, the valve is likely to limit-cycle or sit still while the controller
  integrates.
- A resolution of `<= 0.25 %` (the finest planned step) is good; only `<= 1 %` means the valve cannot
  follow small moves, which usually shows up as a limit cycle.
- A lower bound `> X %` means the valve never moved after a reversal within the leg travel: the deadband
  is **at least** X %, possibly much more.

## Limits (be honest)

- **Validated only on simulated loops.** exp25 (synthetic, instantaneous valve, FOPDT process): deadband
  within 0.25 % of span in 100 % of runs without load disturbance; 87-91 % with a load step during the
  test or high measurement noise (0.2 % of the response to a 1 % step).
- **PV is a proxy for valve position.** Slow or integrating loops, interacting loops, and positioner
  dynamics are **not covered**.
- **A load disturbance during the test degrades the result.** If `PV left the abort band` is `yes`, or the
  curve looks disturbed, **repeat the test** under quieter conditions.
- **No real test record exists yet.** Please **keep the CSV** and report the result, so the next reader
  can judge whether the procedure and the analysis hold on a real valve.

## Troubleshooting

| Message / symptom | Cause | What to do |
| --- | --- | --- |
| `error: no OP changes detected in the record` | OP is flat or the record was not logged during the test. | Check the OP column, re-run the test. |
| `error: ... must be finite (no NaN or gaps in the record)` | Logger wrote NaN, gaps, or text in a number cell. | Export a clean CSV with one row per period, no blanks. |
| `error: missing column 'op' in CSV header` (or `t_s`, `pv`) | Column names differ from the defaults. | Pass `--time-col`, `--op-col`, `--pv-col` with the real names. |
| `error: cannot read CSV file ...` | Wrong path, encoding, or permissions. | Check the path; save as UTF-8 (BOM is fine). |
| `Gain: not identifiable` / `Reason: no gain: valve did not move` | The valve did not move enough to measure K (stuck, wrong loop, or too little travel). | Check the process, the valve and that the loop really is in MANUAL. The plan's largest step is 1 %, and the CLI has no option for larger steps yet; a valve with a deadband above 1 % may not move at all. |
| `Deadband: > X % (no move after a reversal)` | No visible move within any leg. | The deadband is **at least** X %; this plan cannot bracket it (fixed step sizes of 1 % and 0.25 %). Treat it as a maintenance finding. |
| `Resolution: not certified` | No step size met the 75 % move share. | Likely too noisy or the valve is too stuck; repeat under quieter conditions. |

## In the web UI (since 2026-10-20)
Loop detail -> "Valve stroke test" (also offered on the next-action card when the worklist recommends a valve test). Flow:
settings -> safety checklist (three boxes that must be ticked before the procedure is shown) -> operator procedure (printable)
-> record (a window of the loaded dataset, or a CSV file read in the browser and sent in the request body, never stored)
-> result (deadband with bracket, resolution, gain, noise, plain-language verdict, charts). API: `POST /valve-test/plan`,
`POST /datasets/{id}/loops/{loop}/valve-test/analyse`, `POST /valve-test/analyse-csv`; input mistakes return 422 with a stable
`code` (see `loops/valve_payload.py`). Checked end to end on a synthetic stick-slip record (true deadband 0.5 %, reported
bracket 0.5 to 0.75 %). A real loop record is still needed before any claim about real valves.
