# exp31: Courier analyser as soft-sensor input with lab bias correction, on real plant data

Protocol FROZEN 2026-10-24 BEFORE the harness exists and before any number of this experiment is computed. A miss is logged,
thresholds are not moved. The test composites are scored once.

## Question
On the owner's four weeks of flotation line L1 (confidential, outside the repository), does the online Courier analyser, calibrated
once on the first part of the record, estimate the 6 h laboratory composite better than what the operator has today (the last lab
value carried forward), and does an exponentially weighted lab bias correction on top of it help or hurt?

## Honest limit of this test (read first)
The 107 composites were already used in exploration (`tools/analyzer_vs_lab.py`: alignment scan and a one-feature blocked
cross-validation, R2 0.76 for Cu, 0.78 for Mo; see the owner's Drive report). This is therefore NOT a blind test: the sign and the rough
size of the result are known, and the alignment shift (-0.5 h) was chosen from the same data. What the protocol fixes is the
procedure (chronological split, rules, thresholds) so nothing is tuned after the numbers. A blind test needs weeks the assistant has
not looked at: the owner is asked to keep the next delivery of A4/A5 untouched for that.

## Data
- A4: wide 1-min CSVs (the Cu and Mo analyser columns of the rougher concentrate). Values below `MIN_VALID = 0` (sentinel -9999 and
  the interpolation blend towards it) are treated as missing.
- A5: long-format lab composites (6 h) of the same sample point: Cu for target T1 and Mo for target T2. Tag names are NOT written in
  the repository (plant data is confidential); the harness takes them from the command line and fails if a tag is not found.
- Plant stamps are local time without a zone; the same offset is applied to both files, so the difference is unaffected.
- Reported, no target: the same procedure for Fe concentrate, and Cu, Mo and Fe of the tail.

## Procedure (fixed)
1. Feature of a composite with lab stamp `t`: mean of the valid Courier minutes in the window `[t - 6.5 h, t - 0.5 h]` (window 6 h,
   shift -0.5 h). The composite is `unusable` when fewer than 50 % of the window minutes are valid.
2. Composites sorted by stamp; the first 60 % of the usable composites (rounded down) are TRAIN, the rest TEST. The split index is
   fixed by this rule only.
3. Methods, evaluated on TEST composites one after the other in time order (a lab result becomes known at its own stamp):
   - M0 carry-forward: the most recent lab value known before the composite window ends.
   - M1 raw Courier: the feature itself.
   - M2 calibrated: `a + b * feature`, `a`, `b` by least squares on TRAIN only, frozen.
   - M3 corrected: M2 plus `bias`, where `bias` is the EWMA (weight 0.3, start 0) of `lab - M2` over the labs already known; it is updated
     after each lab becomes known, so a TEST composite is predicted with the labs of earlier composites only.
4. Score: RMSE against the lab value of each TEST composite (the lab value contains its own measurement noise; there is no true value).

## Pass criteria (T1 Cu concentrate and T2 Mo concentrate, each must hold)
| id | criterion |
|----|-----------|
| R1 | RMSE of M2 is at most 0.75 times the RMSE of M0 |
| R2 | RMSE of M3 is at most 1.05 times the RMSE of M2 (the bias correction does not hurt) |
| R3 | at most 10 % of all composites (train and test) are unusable for Courier coverage |
| R4 | no leakage, checked by the harness: (a) a refit of `a`, `b` with all TEST labs removed gives identical values; (b) every feature window ends at or before `t - 0.5 h` |
| R5 | RMSE of M2 on TEST is at most 1.25 times the 5-fold blocked cross-validated RMSE of M2 on TRAIN (the TEST period is not much harder than the training period) |

Reported, no target: RMSE, MAE and R2 of M0, M1, M2, M3 on TEST; the TRAIN calibration (`a`, `b`, number of composites); number of TEST
composites; the same table for the secondary targets; M3 against M2 per composite (how often the correction moves the estimate towards
the lab value).

## Decision rule
R1 miss for a target: the module is labelled "Courier calibration not better than the last lab value on this record" for that target.
R2 miss: the bias correction is not shipped as default for that target. R3 miss: the validity flag is shown and the share is reported.
R4 miss is a defect: fix and re-run (only possible because no test number has been used to decide anything). R5 miss: the estimate
is reported with the warning that the test period differed. Never tune the window, shift, split fraction or EWMA weight after the
numbers; any change is a new protocol and a new data delivery.

## What this does not show
Four weeks and about 43 test composites with a flat alignment optimum. The lab stamp semantics (end of period plus up to 1 h) and the
analyser latency (assumed 0) are not confirmed by the plant. The lab is itself a noisy reference. A drift of the analyser or the lab
method over months is not covered. Nothing here writes to or advises on a plant.

## Authorship
Harness: written by a delegated model (foremankit) that did not write the soft-sensor module; the lead reads it and re-derives the
metrics by hand on a few composites. The harness reads the data from paths given on the command line and prints only aggregate
numbers; no data is stored in the repository.

## Result (first and only run, 2026-10-24; tables in results/test.md, aggregate numbers only)
The harness was read by the lead before the run and two deviations from this protocol were fixed before any number existed (M3 bias must keep
updating through TEST; M0 and M3 must see the labs of unusable composites too). 67 train and 45 test composites per primary target.

| id | T1 Cu concentrate | T2 Mo concentrate |
|----|-------------------|-------------------|
| R1 M2/M0 RMSE <= 0.75 | PASS 0.508 | PASS 0.426 |
| R2 M3/M2 RMSE <= 1.05 | **MISS 1.074** | PASS 0.886 |
| R3 unusable share <= 10 % | **MISS 0.222** | **MISS 0.222** |
| R4 no leakage | PASS | PASS |
| R5 TEST/CV <= 1.25 | PASS 0.829 | PASS 0.310 |

TEST RMSE (R2 in brackets): Cu M0 1.274, M1 0.661, M2 0.648, M3 0.696 (0.65); Mo M0 0.0306, M1 0.0120, M2 0.0130, M3 0.0116.
Reading: the Courier estimate halves the error of the last lab value on both concentrate grades. Calibration on TRAIN adds nothing over the raw
Courier (slopes 1.06 and 0.95, offsets near 0): M1 is as good as M2. The EWMA lab correction hurts Cu (7 %) and helps Mo (11 %), so it is not
a default for Cu (decision rule). R3 is missed: 22 % of the composites have fewer than half valid Courier minutes in the window (cause not
analysed here; the sentinel and its interpolation blend are removed with MIN_VALID = 0), so the validity flag is mandatory.
Secondary, no criteria: Fe concentrate behaves like Cu (M2/M0 0.53). For the tails the calibrated M2 is worse than raw M1 on all three
(Cu 0.0149 vs 0.0108, Fe 0.453 vs 0.359, Mo 0.0009 vs 0.0005) and the tail M2/M0 ratios are 0.80, 0.94 and 1.28: with low grades the
train-fitted line does not transfer; do not use the calibrated tail estimate.
Not a blind result (see the limit above). A true test needs the next delivery of weeks the assistant has not looked at.
