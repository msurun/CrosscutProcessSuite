# exp41: regime-aware anomaly engine and stuck exemptions on PRONTO multiphase flow data - issue #102

Status: run once 2026-11-18, one of four targets met (`results.md`). Module: anomaly. Predecessor: exp38 (`experiments/exp38_pronto_public/`, issue #87): one model per
day fitted on minutes at one set point, quiet alarm share 0.96, 140 of 153 events stuck-rule events. This is a validation case
for the two engine features of issue #102 (not a feature); both are described in the exp40 README:

- (a) regime-aware PCA (`regimes` block, one PCA per regime with >= `min_rows`, unknown or under-trained regime -> row unscored,
  never an alarm, output `rows_unscored`);
- (b) stuck rule exempting signals constant by nature, with exempt counts per reason.

Owner decision 2026-11-17 applies: public data only.

## Data (outside the repo, never committed)

Same as exp38: PRONTO heterogeneous benchmark dataset, Zenodo record 1341583, licence CC BY 4.0 (Stief, Tan, Cao, Ottewill,
Thornhill, Baranowski, J. Process Control 79 (2019) 41-55, doi:10.1016/j.jprocont.2019.04.009). Only the DeltaV process-data csv
(1 s) and the operation log from the zip by HTTP range requests (about 21 MB), scratch folder outside the repo. Files: 0907Testday2,
0911Testday3, 0912Testday4 (0626Testday5 excluded as in exp38). Time axis, block transcription (`BLOCKS`, kinds N / F / S, first
120 s of every N block not quiet) and read code are reused unchanged from `run_exp38.py`.

## New split (chosen now by rule; exp38 fitted one model per day on 70 % of its first N block)

Leave-one-day-out over the three days, regime models trained on the N blocks of the other two days:

- Test day D in {0907, 0911, 0912}, each in turn. Test quiet = all N blocks of D (after the first 120 s). Fault test = all F blocks
  of D, slugging test = all S blocks of D (reported separately, no target), scored as in exp38 (an event starting inside the block
  counts, delay = start minus block start; events open at block start are not credited).
- Train = N blocks of the other two days (after the first 120 s), except the last N block of each of those days by time, which is
  the calibration block (scanned and reported, F1/F2 reported only; no value tuned on it).
- Consequence, stated now: 0912 uses set points (20-200 sm3/h air, 0.1-3.5 kg/s water) that mostly do not occur on 0907/0911
  (120/0.1 and 150/0.5), and the reverse. Many test rows will be unscored; this is the intended behaviour of the feature and is
  reported through `rows_unscored`, not hidden. 0912 has no F blocks, so D1/D2 come from 0907 and 0911 only.
- PCA tags = the 19 measurement columns minus columns constant in the training rows; at least 3 tags, else the day is skipped.

## Engine configuration (fixed now, no tuning)

Base as exp38: variance_fraction 0.90, alpha 0.99, min_consecutive 5, close_after 10, stuck_samples 30, native 1 s, no dynamic
lags, other settings the engine defaults at the commit of the run.

| Item | Fixed value |
|---|---|
| regimes key | the four controller set point columns among the 12 columns after the 19 measurements of the csv (csv column index, 0 = TIMESTAMP): `FIC302/PID1/SP.CV` (21) and `FIC301/PID1/SP.CV` (24) for air, `FIC102/PID1/SP.CV` (27) and `FIC101/PID1/SP.CV` (30) for water; named `sp_air_fic302`, `sp_air_fic301`, `sp_water_fic102`, `sp_water_fic101` in `run_exp41.py`. Fixed from the header names and from the median SP of the N blocks (not scored data). One column per quantity does not exist: which of the two air loops (302 for 20-150, 301 for 200 sm3/h) and which of the two water loops (101 for 0.1-0.5, 102 for 1-3.5 kg/s) carries the set point changes with the block, the idle loop sits at a constant (100.001 / 0), so the key is the tuple of all four |
| quantum | the two air set point columns 10 sm3/h, the two water set point columns 0.1 kg/s (the logged set points 20/50/100/120/150/200 and 0.1/0.5/1/2/3.5 are multiples) |
| min_rows | 120 rows (2 min) per regime |
| setpoint_like | the four set point columns (not PCA tags of the 19 measurements; the engine needs them in `tags`, it zeroes them for fitting); no other tag is named, the zero-diff share > 0.9 rule covers the rest |
| stuck exemption (b) | on; quantisation step = engine default estimate from training rows |

Two arms on the same split: arm B = new engine (targets evaluated on B); arm A = exp38 engine configuration (no regimes, no
exemptions), trained on the pooled training rows as one model, reported only, to separate split effect from feature effect.
Ramp warning: not evaluated (no NaN gaps), R1 not applicable.

## Metrics and frozen targets (copied from exp38, same IDs and thresholds)

| ID | Metric | Target |
|---|---|---|
| F1 | False alarm events per quiet day (events starting on quiet samples), extrapolated from quiet hours, pooled over test days | <= 3 per day |
| F2 | Share of quiet samples inside an event | <= 0.02 |
| D1 | Detection rate over `F` blocks | >= 0.70 |
| D2 | Median detection delay of detected `F` blocks | <= 120 s |
| R1 | Ramp-warning precision | not applicable |

Unscored rows (fixed now): unscored quiet samples stay in the F2 denominator and the F1 quiet-hours base; an `F` block whose
start rows are unscored cannot be detected there and counts as a miss in D1 unless an event starts later inside the block. This is
stricter, not looser, than a "scored only" reading; F2 over scored quiet samples is reported besides.

### Targets argued to change

None. No target or threshold is changed from exp38.

## Extra metrics (reported only, no target)

- `rows_unscored` share per day: all rows, quiet rows, fault rows, slugging rows; regimes fitted and under-trained per test day.
- Stuck-rule events kept and exempted with exempt counts per reason (run length in training, value at training min/max, within one
  quantisation step of a long-held training level, setpoint-like list, zero-diff share > 0.9).
- Quiet metrics split into regimes seen in training and unseen ones; share of `F` samples inside an event; calibration-block F1/F2;
  arm A vs arm B; slugging blocks as in exp38. Quiet days are extrapolated from hours and labelled so.

## Honesty rules

Run once, report all numbers whatever they are. A missed target stays missed. No tuning on exp38 results or on exp41 test data: no
change of threshold, tag, quantum, min_rows, block, day split or window after the first run (a change makes `exp41_v2`). Bug fixes
that do not change a definition are listed in results.md.

Run: `python experiments/exp41_pronto_regimes/run_exp41.py --data <scratch folder with the case-study tree>`; without the data it
prints SKIP and exits 0.

## Frozen on 2026-11-18: protocol and runner merged to main by PR "exp40/exp41 frozen protocols" before any full run (the merge commit is the freeze point; results.md names it)
