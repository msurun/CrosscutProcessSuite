# Experiment 12: stiction scoreboard on real loops, and the iteration rules

Owner's instruction (2026-10-15): iterate on the stiction detector until it works well on the real data we have. Protocol
agreed with an Opus advisor. `labels.csv` is the frozen label set (19 SACAC loops: 6 sticking, 13 not; repeated runs of one
loop count once; file stems separated by `;`). Confidence `low` loops are reported but not counted in the targets.
Data: SACAC, local use only (see docs/PROVENANCE.md). The scoreboard runs the SHIPPED entry point `detect_stiction(pv, out,
dt)` on the whole record; a loop's verdict is the majority over its files (a tie is "inconclusive"). Usage:
`python scoreboard.py <unzipped SACAC folder>`.

## Split and its honesty
Dev = Pisa stiction loops + tuning-F-chemical. Held-out = everything else. Constants of any new method are derived on synthetic
data (exp01/exp11) only; dev loops are for debugging; the held-out set is scored once per round. Caveat: results of the shipped
detector on most of these loops were already seen in exp10, so the held-out set is not untouched; the next honest step after the
last round is new data (own plant records).

## Targets, frozen 2026-10-15 BEFORE the baseline run (counted: confidence high or medium, 6 positives + 11 negatives)
- **T1 detection:** at least 4 of the 6 sticking loops get "stiction", and at least 2 of the 3 held-out ones.
- **T2 false alarms:** at most 1 of the 11 counted negatives gets "stiction", and at most 1 held-out. "Inconclusive" is not a flag.
- **T3 coverage:** at least 11 of the 17 counted loops get a verdict other than "inconclusive".
- **T4 no regression:** `experiments/exp01_stiction_validation/acceptance.py` still meets its own frozen targets.
- Wilson 95 % bounds are printed with every rate; 12-20 loops can show gross failure or plausibility, not an accuracy figure.

## Rules for the rounds
At most 2 candidate changes per round, at most 5 rounds. Each round: write its candidates and any new target here with the date
BEFORE running. Stop when T1-T4 hold on held-out, or after 2 consecutive rounds that fail on held-out; then ship the detector
with its documented limit. Candidates in order: (a) band-pass around the autocorrelation period + noise-aware index;
(b) route by process type (OP for self-regulating, filtered PV for level, type from the loop settings, never guessed);
(c) OP-PV cross-correlation as a second voter (stiction only when both agree). Later: bicoherence as a gate, magnitude.

## Round log

### Round 0 (baseline, 2026-10-15, shipped detector, floor 30)
T1 1/6 detected (held-out 0/3; Wilson [3 %, 56 %]) MISSED; T2 0/11 false alarms met; T3 answered 1/17 MISSED. Only Pisa chemical
pressure is flagged; the other 16 are "inconclusive". T4 holds (nothing changed).

### Round 1 (candidates frozen 2026-10-15 BEFORE any code or run): candidate A only
A = (1) detrend OP; (2) fundamental period from the autocorrelation; (3) white-noise variance v from the median spectrum power
above 8 fundamentals; (4) keep harmonics 1-7, drop the rest, and upsample by zero-padding the spectrum so every half-cycle has
at least 64 samples (this also removes the discretisation artefact that makes short sine half-cycles look non-sinusoidal);
(5) segment the filtered signal into half-cycles; (6) SI' = (a - c) / (a + b - 2c) per half-cycle with a, b the sine and
triangle fit errors and c the noise variance left after filtering, clipped to [0, 1]; median over half-cycles; same cycle-count
and regularity rules as today, but NO fixed samples-per-half-cycle floor (the filtering and upsampling replace it).
Gate 1 (synthetic, before touching real data): the exp11 design (same generator, seeds, 200 trials) with candidate A. Required,
for L in {10, 12, 15, 20, 30, 60} and noise sd 0.05 and 0.15: detection >= 80 % and false alarm <= 5 %. Report 0.30 and
L = 6, 8. If Gate 1 fails, candidate A is dropped or changed in a new round; the real data is not looked at to repair it.
Gate 2: the scoreboard above with candidate A as detector `candidate_a`; T1-T3 as frozen. T4 only if the package is changed.

### Round 1 result (2026-10-15): Gate 1 FAILED as frozen (real data not touched)
Candidate A on the exp11 synthetic grid. Failing required cells: L=10 (s=0.05: false alarm 17 %; s=0.15: detection 50 %),
L=12 and L=15 at s=0.15 (detection 62 % and 78 %). Passing: every L >= 20 at s=0.05 and 0.15 (detection 84-100 %, false alarm 0 %)
and L=12, 15 at s=0.05. For comparison the shipped index had detection 4 % at L=30, s=0.15. At s=0.30 nothing is found below
L=60 (39 %). So the band-limiting + noise correction works, but the information in 10-15 noisy samples per half-cycle is not enough.

### Round 2 (frozen 2026-10-15 BEFORE the run): candidate A with a floor of 20 samples per half-cycle
Change: candidate A answers "inconclusive" when the period is under 40 samples (fewer than 20 per half-cycle). The 20 comes from the
synthetic results above only (the smallest grid L where both required noises pass); it is a validity envelope, stated as a
limit, not a pass of the original Gate 1 for L < 20. Gate 1b = the same grid, required cells L in {20, 30, 60} x s in {0.05, 0.15}
(unchanged thresholds: detection >= 80 %, false alarm <= 5 %). Gate 2 = the scoreboard with detector `candidate_a`, T1-T3 as
frozen in this file (so loops with under 20 samples per half-cycle, e.g. Pisa oil&gas, Horch flow, tuning-Q, are inconclusive
by construction and count against T1/T3).

### Round 2 result (2026-10-15): Gate 1b FAILED; the scoreboard run is informational only
- Gate 1b (L = 20, 30, 60): L = 20, s = 0.15 detection 74 % (< 80 %) FAILED; L = 30 and 60 pass (97-100 %, false alarm 0 %). L = 20
  also refuses 10-12 % of trials because the period estimate is not exact and the floor sits exactly on the grid value.
- PROTOCOL BREACH: I ran the scoreboard concurrently with Gate 1b instead of after it, and the first scoreboard run exposed an
  implementation deviation from the frozen candidate A: `cf._irregularity` still applied the shipped 30-sample floor to the
  upsampled lengths (the frozen text says no such floor). Fixed (own `irregularity()` without it) and the scoreboard re-run.
  Synthetic numbers did not change in kind (their half-cycles are always >= 64 upsampled samples).
- Scoreboard, informational (not a pass): before the fix T1 2/6 and T3 3/17; after the fix T1 3/6 (held-out 1/3, flagged: Horch level,
  Pisa power, Pisa chemical), T2 0/11, T3 4/17. Eastman LC2 reads "no_stiction" (index 0.3) = a WRONG answer on a known sticking
  integrating level loop; Horch flow, Pisa oil&gas and most negatives stay inconclusive (no periodicity, under 20 samples per
  half-cycle, or fewer than 6 cycles).
- Also noted: T3 as frozen counts "inconclusive" on non-oscillating negatives as a miss, although "no oscillation, so no stiction
  question" is the right answer for them. From round 4 on a second figure T3' (coverage among loops that oscillate at all:
  autocorrelation period found and >= 6 cycles) is reported next to T3; T3 itself is not redefined and stays MISSED until met.

### Round 3 (frozen 2026-10-15 BEFORE the run): re-derive two constants of candidate A on synthetic data only
Constants: harmonics kept H in {3, 5, 7} and the period floor. Procedure (unchanged gate thresholds: detection >= 80 %, false alarm
<= 5 %, s in {0.05, 0.15}, 200 trials, floor disabled): for each H over the grid L in {10, 12, 15, 20, 25, 30, 40, 60}, find
L_pass = the smallest L such that all grid values >= L pass. Choose the H with the smallest L_pass (tie: the larger H). The floor
is then 0.9 * L_pass applied to period/2 (10 % slack for the period estimate, fixed a priori). Gate 1c: the grid at the chosen
(H, floor) must pass for every L >= L_pass (true by construction unless the floor itself breaks it). Only after Gate 1c the
scoreboard is run, once, as Gate 2 (T1-T3 as frozen, T3' reported). Stop rule: two consecutive failed rounds end the work on
candidate A as a pure OP method and the product ships with the documented limit.

### Round 3 result (2026-10-15): Gate 1c PASSED, Gate 2 FAILED
Derivation (synthetic only): L_pass was 30 for H = 3, 25 for H = 5, 20 for H = 7; chosen H = 7, floor 18 samples per half-cycle
(0.9 * 20). Gate 1c: L = 20 detection 100 % / 84 % (s = 0.05 / 0.15), L = 30 100 % / 97 %, L = 60 100 % / 100 %, false alarm 0 %
everywhere; at s = 0.30 only L = 60 detects (39 %).
Gate 2 (scoreboard, once): T1 3/6 (held-out 1/3) MISSED; T2 0/11 met; T3 4/17 MISSED. Flagged: Horch level, Pisa power, Pisa
chemical (indices 1.0, 0.68, 0.89). Per-loop reasons for the rest: Pisa oil&gas has 8 samples per half-cycle (12 s sampling:
below the information limit shown in exp11, nothing to fix in the method); Horch flow has half-cycle lengths varying too much;
Eastman LC2 reads 0.30 on OP = WRONG verdict (integrating level loop); negatives are inconclusive because they do not oscillate
(no periodicity, fewer than 6 cycles) or have under 18 samples per half-cycle (other-F-horch, tuning-Q, sensor-F, saturation-T).
Rounds 2 and 3 both missed T1 on the scoreboard, so by the stop rule candidate A stops being refined as a pure OP method.

### Round 4 (frozen 2026-10-15 BEFORE any code): candidate B = route by process type, level loops on PV
B = candidate A (unchanged constants H = 7, floor 18) applied to OP for loops of kind F, P, Q, T and to PV for kind L (integrating
processes, He et al. 2007, abstract-level reading; the kind comes from `labels.csv`, i.e. from the loop settings in the product,
never guessed from data). No other change. Gate 1 for B is the same as Gate 1c, because the PV of an integrating loop under
stiction is a triangle and under a tuning/disturbance oscillation a sine, the same synthetic class (the argument is stated, not
tested; a PV noise level above OP noise is the open risk). Gate 2: the scoreboard once with detector `candidate_b`, T1-T3 as
frozen; additionally T3' = share of loops that oscillate (period found and >= 6 cycles on the used signal) that get a verdict
other than inconclusive, reported, not a target. One round, one change. If T1 is still missed after round 4 the detector ships as
"works on clean OP/PV with >= 18 samples per half-cycle; abstains otherwise" and the remaining misses are listed as data limits.

### Round 4 result (2026-10-15): Gate 2 for candidate B, once
| detector | T1 detected (held-out) | T2 false alarms | T3 answered | T3' (information) |
|---|---|---|---|---|
| shipped | 1/6 (0/3) | 0/11 | 1/17 | 1/10 |
| candidate A (OP) | 3/6 (1/3) | 0/11 | 4/17 | 4/10 |
| candidate B (level loops on PV) | 3/6 (2/3) | 0/11 | 3/17 | 3/10 |
T1 MISSED by one loop (needs 4 of 6), T3 MISSED, T2 met. B fixes the known wrong verdict: Eastman LC2 on PV reads 0.77 "stiction" (A read
0.30 on OP = wrong); Horch level 0.98. Pisa power level is now inconclusive (PV index 0.58; on OP it was 0.68): on level loops the
two signals disagree around the 0.6 threshold. Remaining misses: Pisa oil&gas (8 samples per half-cycle, a data limit), Horch flow
(irregular half-cycles), Pisa power (borderline). All negatives stay inconclusive because most do not oscillate (T3' counts only
those that do: 3 of 10 answered for B).
Rounds 3 and 4 both missed T1 on the scoreboard, so by the stop rule no further round is run without the owner's decision.
Status: candidate B is better than the shipped detector on every figure that matters here (detected 3 vs 1 of 6, held-out 2 vs 0
of 3, wrong verdicts 0 vs 0, false alarms 0 vs 0), but it is NOT in the package: putting it there needs the loop kind in the
settings and the exp01 acceptance run (T4) with the new method. 12-19 loops cannot support an accuracy figure.
