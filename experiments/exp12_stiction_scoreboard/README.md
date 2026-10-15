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
