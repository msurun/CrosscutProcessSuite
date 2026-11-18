# exp37 results: sealed worklist benchmark (#85)

Run once on 2026-11-18, package code at origin/main 54c1ea3, default `LoopTags`/`LoopSettings` (no per-loop knowledge,
OP assumed 0-100, mode always AUTO), path `overview._analyse_one_loop` -> `_add_shared_periods` -> `worklist.add_worklist`.
Data stayed in a scratch folder outside the repo; no data or per-sample values are committed, only loop ids.

## What the sealed part turned out to be

- ISDB: 59 loops not in `isdb_labels.csv` and not synthetic test series; all have an OP column. 
  The 6 `testdata/*` series were excluded by rule.
- SACAC: the 6 `unknown-*` files (the 3 `plantwide-*` files are multi-tag plant tables without a SP/PV/OP loop
  structure and were not run). Total 65 loops ranked together, 0 failures.
- **Labels (frozen rule applied to the providers' `Comments` text): only 3 loops carry a problem statement.**
  `chemicals/loop7` "has valve stiction problem" (stiction); `metals/loop1` and `metals/loop3` "has external
  disturbance" (external). No sealed loop is labelled tuning, and none is labelled healthy. The other 62 are
  unlabelled and not scored. Frozen rule: fewer than 10 scored loops means **descriptive only, no pass/fail**.

## Metric A: rank of the true problem loops (65 loops in the worklist)

| loop | true class | rank | status | action |
|---|---|---|---|---|
| chemicals/loop7 | stiction | 32 | not_assessed | check_output_resolution |
| metals/loop1 | external | 26 | warning | valve_test |
| metals/loop3 | external | 62 | not_assessed | configure_knowledge |

Ranks 26, 32, 62; median 32. Top third (rank <= 21): 0 of 3, against 1 of 3 expected by chance. With n = 3 the
interval covers everything (Wilson 95 % for 0/3: 0-56 %), so this shows no ranking skill but does not prove its absence.

## Metric B: confusion matrix (action mapped to class as frozen)

| true \ worklist says | stiction | tuning | external | other |
|---|---|---|---|---|
| stiction (1) | 0 | 0 | 0 | 1 |
| external (2) | 1 | 0 | 0 | 1 |

Diagonal 0 of 3 (Wilson 95 % 0-56 %). The wrong `valve_test` for the external-disturbance loop is the one
concrete finding: a thickness loop with an external disturbance was sent to a valve test.

## Reading, without overreach

- The two `not_assessed` problem loops (rank 32 and 62) are not an error of the ranking rule: with no configured
  delay/period/amplitude the package withholds conclusions, and 35 of the 65 loops ended as `configure_knowledge`
  or `check_output_resolution` at the bottom. A real-use configuration would change this, and this run tested only the
  no-knowledge default, which is what a first-time user sees.
- Default OP range 0-100 does not match ISDB data scales (also noted in exp18); saturation findings on these loops
  are partly artefacts of that.
- The 62 unlabelled loops give a distribution only: 3 `problem`, 26 `warning`, 36 `not_assessed` by status. That is
  coverage evidence, not accuracy.
- Not met / not testable: the frozen scoring needed at least 10 labelled loops (3 exist), no tuning class exists in
  the sealed part, and no healthy negatives exist. A usable blind benchmark needs labels the sealed public data do not
  have; the blind review by a control engineer (issue #28 route) is still the only way to check the ranking.
