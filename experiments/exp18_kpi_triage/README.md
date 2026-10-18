# exp18: does the loop triage flag real problem loops? (protocol frozen 2026-10-18, BEFORE any run)

Question: on real loops with a documented fault, how often does `analyze_loop` + `status_level` + the KPI findings
flag the loop, and do the new KPI findings (quantisation, saturation) agree with the documented cause?
Code under test: `crosscut_loops.monitor.analyze_loop`, `overview.status_level`, as shipped at commit 6ecb791.
Nothing in the package may be changed to improve this result; a miss is reported as it is.

## Data and what the labels can and cannot say

- SACAC: the 19 loops of `experiments/exp12_stiction_scoreboard/labels.csv` (repository category + comment).
- ISDB: `experiments/exp16_stiction_generalise/isdb_labels.csv`, rows with overlap = `independent` only (44; the
  `sacac-twin` and `overlap` rows are dropped). ISDB was already seen in exp15/exp16 for STICTION selection; this
  experiment scores other quantities, but ISDB is not a fresh test set in general.
- Neither source labels "oscillating or not". They label the CAUSE of a fault, so almost every loop is a problem loop.
  The test is therefore mostly a SENSITIVITY test and says almost nothing about false alarms.
- Loops with label confidence `low` are excluded and listed. A loop with several runs (SACAC DB-1..n) counts once;
  it is "flagged" when more than half of its runs are flagged.

## Frozen settings (the same rule for every loop; none tuned on these data)

`LoopSettings`: delay_s = 5 x dt, ultimate_period_s = 60 x dt, amplitude_limit = 5 % of the PV span (p1..p99),
out_low = 0, out_high = 100, process_kind = "integrating" for kind L else "self_regulating", everything else default.
Mode = AUTO for all samples, quality = none, t = k x dt (dt from the label table). Record length: the whole file.
(delay and period are guesses carried over from the 2026-10-15 exploratory look; they were not fitted.)

## Definitions

- flagged = `status_level` is `warning` or `problem`, OR a finding starts with `quantisation:` or `valve `.
- Positive loop = documented fault: every labelled loop except the negatives below and the excluded ones.
- Negative loop (explicit "normal / no oscillation" in the provider comment): SACAC `other-F-horch-2`, `other-L-horch`;
  ISDB `buildings/loop1`, `buildings/loop2`, `buildings/loop8`. ISDB "no stiction" loops (pulpPapers/loop6, loop9) say
  nothing about oscillation and are excluded from both groups.
- Quantisation truth: SACAC `quantisation-*` (2) and ISDB `chemicals/loop3` ("with quantisation"); saturation truth:
  SACAC `saturation-*` (2, confidence medium/low).

## Targets (frozen)

- **T1 sensitivity:** flagged share among positive loops >= 80 %. Report the Wilson 95 % interval; the claim is limited
  to what the interval supports (a point estimate of 80 % with a lower bound near 60 % is "not shown", not "validated").
- **T2 false alarms:** flagged count among the 5 negatives. No numeric target (n = 5); reported as anecdote.
- **T3 cause agreement:** the `quantisation:` finding fires on at least 2 of the 3 quantisation-truth loops, and
  classification `saturated` on at least 1 of the 2 saturation-truth loops. Also report how many loops WITHOUT that
  truth got the finding (precision side), no target.
- **T4 valve sizing:** no ground truth; counts of oversized / undersized / none only.
- Missing a target is reported as a miss; thresholds, settings and the flag rule above are not edited afterwards.

## Not covered by this experiment (each needs its own frozen target before it is built or claimed)

Idle index, ACF-based oscillation detector, period grouping and trend in the overview, priority score.
