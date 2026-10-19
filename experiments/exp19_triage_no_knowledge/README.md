# exp19: triage with no per-loop knowledge (protocol frozen 2026-10-18, BEFORE any run)

Question: when a loop arrives with no configuration (no OUT range, no dead time, no oscillation limits), which is
what a new customer's tags give, does the triage stop flagging everything (the exp18 failure), and does the
parameter-free ACF oscillation detector separate loops documented as oscillating from loops documented as calm?
Code under test: `crosscut_loops.monitor.analyze_loop` and `overview.status_level` as of commit 9cd236e. Nothing in
the package may be changed to improve this result; a miss is reported as it is.

**Status: exploratory, not a validation.** SACAC and ISDB were both seen in exp15-exp18 (ISDB for stiction selection,
both for the exp18 triage), and the exp18 diagnostic read is what motivated the not-assessed rule and the ACF detector.
The ACF detector's constants were chosen on synthetic signals only, never on these records. A pass here supports
"not contradicted by real data"; it does not support a performance claim.

## Data

- SACAC: loops of `experiments/exp12_stiction_scoreboard/labels.csv`, confidence `low` excluded. A loop with several
  runs counts once; a per-run outcome counts for the loop when it holds in more than half of the runs.
- ISDB: `experiments/exp16_stiction_generalise/isdb_labels.csv` (untracked, local), overlap `independent` only,
  confidence `low` excluded.
- Records as in exp18: whole file, t = k x dt (dt from the label table), mode = AUTO wherever SP, PV and OP are finite.

## Frozen settings (the OP-range rule)

`LoopSettings(delay_s=dt, ultimate_period_s=60*dt, amplitude_limit=1.0, process_kind="integrating" for kind L else
"self_regulating", known=frozenset())`. With `known` empty the placeholders are never used: the OUT range is never
assumed (saturation and valve travel/reversals/sizing withheld), Harris is withheld, oscillation is found by ACF
regularity and its amplitude is not judged. Rule: **an OP range is used only when it comes from configuration;
these records have none, so none is used.**

## Oscillation labels (derived from the provider comments; fixed here)

- **Oscillating (positive):** every high-confidence stiction loop (SACAC `stick` rows: 6; ISDB `stick` rows: 13) and
  SACAC `other-F-horch` ("oscillation from an external disturbance"). n = 20. Assumption, stated: a documented
  sticking valve in these archives shows a limit cycle in the record (they were collected as oscillation examples).
  A stiction loop without a cycle counts against the detector.
- **Calm (negative):** ISDB `buildings/loop1`, `loop2`, `loop8` ("no oscillation"); SACAC `other-F-horch-2` (normal
  operation, setpoint change), `other-L-horch` (normal operation), `tuning-F-chemical` (sluggish tuning),
  `other-F-chemicals` (non-periodic transient excursions). n = 7.
- **No oscillation label:** all other scored loops (tight tuning, quantisation, saturation, sensor fault, dead zone,
  "no stiction", disturbance). Counted and reported, no target.

## Definitions

- detected = `oscillation_period_s is not None` (method `acf`).
- flagged = `status_level` in {`warning`, `problem`} (stricter than exp18: findings alone do not flag).

## Targets (frozen)

- **O1 sensitivity:** detected among positives >= 80 % (16 of 20). Wilson 95 % interval reported; with n = 20 the
  lower bound will be well below 80 %, so even a pass is "not contradicted", not "shown".
- **O2 calm loops:** detected on at most 1 of the 7 negatives.
- **O3 triage breadth:** flagged on at most 2 of the 7 negatives (exp18: 4 of 5). Also report the flagged share over
  all scored loops and the status counts (ok / warning / problem / unused).
- **O4 rule check:** every scored loop lists `saturation`, `valve_kpis`, `harris`, `oscillation_amplitude` in
  `not_assessed`; zero `saturated` classifications; zero sizing hints. Any violation is a bug, not a miss.
- **Reported, no target:** detected share among unlabelled loops; detected periods (seconds and in samples) for the
  positives; `same_period_as` is not scored (records come from different plants and times); quantisation finding on
  the 3 quantisation-truth loops (exp18: 0 of 3; the quantisation code did not change).
- Thresholds, settings, labels and the flag rule above are not edited after the run. One run; the script refuses
  to overwrite an existing result file.

## RESULT (2026-10-18, one run of `run19.py` at commit dc63cdd; 44 loops scored, 19 excluded, 0 errors)

Per-loop rows are in `results19.md`, which is untracked (third-party derived, see `.gitignore`).

| Target | Result | Verdict |
| --- | --- | --- |
| O1 sensitivity | detected 9/20 (45 %, Wilson 26-66 %); SACAC 5/7, ISDB 4/13 | **MISS** |
| O2 calm loops | detected 0/7 | PASS |
| O3 triage breadth | flagged 2/7 negatives (exp18: 4/5); all loops 20/44 flagged (exp18: 41/44); ok 24, warning 14, problem 6 | PASS |
| O4 rule check | 0 violations | PASS |
| Reported | unlabelled loops detected 7/17; quantisation finding 0/3 on truth loops, 5 on others (unchanged from exp18) | - |

**Reading.** The not-assessed rule did what it was for: the triage no longer flags almost everything, and the
detector raised no oscillation on any calm loop. But it is too conservative: it missed 11 of 20 documented
oscillating loops, 9 of 13 on ISDB. The 2 flagged calm loops are `problem` from the flatline finding, not oscillation.

**Cause, from a diagnostic read after the run (not a re-score):** every missed ISDB loop ends with "too few ACF zero
crossings". The noise band was 0.18-0.66 on these records, so the ACF hardly leaves it. Two of my own additions to
Thornhill's method cause this on short records with few cycles (ISDB records here are 200-2700 samples):
(1) the Bartlett band sums r_j^2 up to the first zero crossing, which for a slow limit cycle is P/4 strongly
correlated lags, so the band widens exactly for the signals sought; (2) requiring 7 crossings within lags <= n/2
means at least about 7 cycles in the record. Synthetic check afterwards: square wave plus noise is detected 50/50
with 10 or more cycles in the record and 0/50 with 5-6 cycles. The synthetic suite that chose the constants had
records of 3000 samples with 50 cycles, so it never tested this regime. That is a gap in the suite, not in the data.

**Consequence.** The shipped ACF detector stays as it is (no false alarms seen, misses short records); the finding
"no oscillation detected" must not be read as "calm" when the record holds fewer than about 10 cycles. A changed
detector cannot be validated on SACAC/ISDB any more (seen twice now). Next: a synthetic suite with short records
(3-10 cycles, n 200-3000, square and sine cycles, coloured noise) frozen BEFORE changing the band rule, and a fresh
real data set for any claim.