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

## RESULT (2026-10-18, one run of `run18.py` at commit 3310b7c settings; 44 loops scored, 19 excluded, 0 errors)

| Target | Result | Verdict |
| --- | --- | --- |
| T1 sensitivity | 36/38 flagged (94.7 %, Wilson 82.7-98.5 %); SACAC 14/15, ISDB 22/23 | PASS on paper, **vacuous** (see below) |
| T2 negatives | 4/5 flagged (SACAC 2/2, ISDB 2/3) | no discrimination |
| T3 quantisation | `quantisation:` finding on 0/3 truth loops; 5 findings on other loops | MISS |
| T3 saturation | `saturated` on 0/1 truth loop (the second was excluded as low confidence); 18 non-truth loops "saturated" | MISS |
| T4 sizing | oversized 23, undersized 0, none 21 | artefact (below) |

**Reading: the triage flags almost every loop, so the T1 pass says nothing.** 41 of 44 loops are flagged, including 4 of 5
explicit negatives. A flag that fires on everything cannot rank loops; the sensitivity target was too weak to catch this
(known limit of the label set, stated in the protocol, but the result is worse than "limited": it shows the status
rule `warning` is too broad on real data).

**Cause found by a diagnostic read (not a re-score): the package assumes OP in 0-100 %.** On real records the output is
often a deviation variable or another scale (SACAC OP p50 about 0 for 6 of 19 loops, 1.9 or 10 for others; ISDB OP up to
150). With `out_low = 0, out_high = 100` that produces false `saturated` classifications (18 non-truth loops) and
`oversized` hints (23 of 44, median OP below 15 %), and the quantisation ratio miss is plausibly the same scale
problem. The frozen settings were my choice, so this is a defect of the protocol AND a product finding: the loop
analysis must take the OP range from tag configuration (the overview already has eng_min/eng_max for PV) or refuse
the saturation and sizing findings when the range is unknown.

Not done, and not allowed as a validation: re-running with another OP range. That would be tuning on data already seen.
Next step is a new protocol (exp19) with an explicit, frozen OP-range rule, a stricter flag definition (`problem`
only, or a ranked priority) and a negative set larger than 5; ISDB and SACAC cannot serve as a fresh test set for it,
so the numbers there stay exploratory. `results18.md` was not written (the script writes it only with `--write`).
