# Recording a level step test (practical guide)

For the control engineer who records the test on the plant. Goal: one clean record of a
level loop (an integrating process) that the Tuning view can analyse. About 1 to 1.5 hours.

**Safety.** Do the test only under the plant's own procedures and permits (change
request, operator agreement, limits on the level, the valve and the downstream). This
software only reads files: it never writes to the plant.

## Before

1. Pick a period with stable load: feed, pumps and neighbouring cells steady, no planned
   grade or reagent changes. Agree with the operator that nobody else touches this loop.
2. Note the loop (for example LIC1), the cell, the valve, units, and the normal level.
3. Put the loop in **MANUAL** at the normal OUT. Closed-loop (automatic) records are not
   supported yet: the check refuses them.

## During

1. **Quiet first.** Record at least 20 % of the whole record with OUT and the level
   unchanged before the first move (for a 60 minute record: 15 min quiet). The check
   tells you the exact figure.
2. **Move OUT by one step** large enough that PV moves about 10 % of its range, which is
   usually 5 to 10 % of OUT. Stay inside safe level limits.
3. **Doublet preferred:** step up, hold, then step back down by the same amount, so the
   level returns near where it started.
4. **Hold long enough after the last move:** at least 5 minutes, and more than five
   dead times (when in doubt, 10 minutes).
5. No other operator actions, setpoint changes or mode changes during the record.
6. Export PV, OUT, SP and MODE with timestamps at 1 to 10 s (a fixed period, UTC or note
   the time zone). MODE: 0 = manual (otherwise use `--manual-value`; text MAN also works).

## What to bring back

The CSV (any historian layout: wide with a header, or long timestamp, tag, value
[, quality]) and the notes: loop, cell, valve, units, step sizes and times, anything
unusual (disturbances, operator actions).

## After: check, then build the dataset

```
python -m crosscut_loops.step_test_cli check test.csv --time-col timestamp --pv-col LIC1.PV --out-col LIC1.OUT --mode-col LIC1.MODE
```

Long layout: `--tag-pv LIC1.PV --tag-out LIC1.OUT [--tag-mode ...]`. Options:
`--decimal comma|dot`, `--delimiter ';'`, `--time-format iso|seconds`, `--json`.
The report ends with VERDICT `ready`, `usable_with_warnings` or `not_usable`, each finding
says what to do, and the *wizard dry run* shows what the Tuning view will say. If it is
`not_usable`, fix the cause and record again.

```
python -m crosscut_loops.step_test_cli make-dataset test.csv --time-col ... --pv-col ... --out-col ... --out <data root>/step_test_lic1 --loop-name LIC1 --process-kind integrating --pv-unit % --out-unit %
```

It prints what it assumed (UTC, units, the resampling step) and refuses to overwrite an
existing dataset. Open the app with that data root and go to the **Tuning** view.

## What the wizard will show

- The identified **slope** (PV per second per % OUT) and the **dead time with its range**.
- The tuning settings use the **upper bound** of the dead time (the cautious value).
- A notice that integrating-loop tuning is **experimental**: review the result before use.
- If the record fails a check (quiet lead under 20 %, under 5 minutes or five dead times
  after the last move, poor fit), the wizard says so instead of giving settings.
