# exp40: regime-aware anomaly engine and stuck exemptions on SKAB and Petrobras 3W - issue #102

Status: run once 2026-11-18, every target missed (`results.md`). Module: anomaly. Predecessor: exp36 (`experiments/exp36_anomaly_public/`, issue #87), whose run
missed every target (one PCA model per record, alarm share 0.86 to 1.00, stuck events on signals constant by nature). This is a
validation case for two new engine features (issue #102), not a feature:

- (a) operating-regime aware PCA: config block `regimes` builds a regime key from setpoint/mode tags, fits one PCA per regime with
  at least `min_rows` training rows; a row of an unknown or under-trained regime is not scored (never an alarm); output field
  `rows_unscored`.
- (b) stuck rule with exemptions for signals constant by nature: run length seen in training, value at the training min/max, value
  within one quantisation step of a long-held training level, setpoint-like tags (`setpoint_like` list or zero-diff share > 0.9);
  exempt counts are reported per reason.

Owner decision 2026-11-17 applies: public data only, no plant data.

## Data (outside the repo, never committed)

Same provenance as exp36, same local folder layout (`skab/data`, `w3/dataset`):

- SKAB (Skoltech, github.com/waico/SKAB, commit b2c0d46c2971dcbfe71e26087b6d231998bb91c2, GPL-3.0): local only, nothing derived is
  committed (this folder holds code, this protocol and aggregate numbers in results.md). 1 s sampling, 8 tags.
- Petrobras 3W Dataset 2.0.0 (github.com/petrobras/3W, commit c86cc7c70063646910be7292de8a54a6fb2a8399; data CC BY 4.0, code
  Apache-2.0). Real wells only (`WELL-*`), 1 s sampling binned to 10 s block means as in exp36.
- Reading with pyarrow, data is read only, nothing from it is executed.

## New splits (chosen now by rule; they differ from exp36)

SKAB (time-reversed fit; exp36 fitted on the first 70 % of `anomaly-free.csv`):

- `anomaly-free.csv` by rows: [0 %, 30 %) quiet test, [30 %, 50 %) calibration, [50 %, 100 %) train.
- Calibration is scanned and reported (F1/F2 on it, reported only). It is not used to set any threshold; no value is tuned on it.
- Event test = the same 34 other SKAB files; quiet test = samples before the first `anomaly == 1`, onset = first `anomaly == 1`.
  SKAB has no other files, so the event files overlap exp36 by necessity; independence is limited to the fit data and the changed
  detector.
- SKAB has no setpoint or mode tag: the `regimes` block is NOT used on SKAB (one regime). SKAB therefore tests feature (b) and the
  new split only. This is a protocol limit, not a result.

3W (new seeded draw; exp36 used `default_rng(87)`):

- Pool = sorted real-well files per class that are NOT in the exp36 subset (list in exp36 results.md). Draw with
  `numpy.random.default_rng(102)` (a fresh generator per class), without replacement: class 0 normal 24 files, class 4 flow instability 10, class 7
  scaling in PCK 6, class 3 severe slugging 6; if a class has fewer files left, take all of them and report it. The draw list goes
  into results.md.
- Per well with at least 3 drawn class 0 files (sorted by name): train = all class 0 files except the last two; calibration = the
  second-last class 0 file (reported only, like SKAB); quiet test = the last class 0 file plus the `class == 0` stretch of event
  files of that well. Wells with fewer than 3 class 0 files are skipped and listed (not fitted, not scored).
- Training rows: `class == 0` and (if the `state` column exists) `state == 2`. Factual correction found when writing the runner: in every real-well file of the drawn pool `state` holds only 0 or NaN, never 2, so the literal rule would leave no training rows; the state filter is therefore applied only to a file in which `state == 2` occurs, otherwise class 0 alone is used (as in exp36). Rows with `state != 2` are neither training nor
  quiet. Event test = drawn class 3, 4, 7 files of fitted wells; onset = first row with class in {event, 100 + event}, as in exp36.
  NaN-class lead-in rows are scanned but are neither quiet nor event.
- Tags per well = columns finite in >= 99 % of the bins of every file of the well and not constant in the training rows; the
  regime tag and `state`, `class`, `timestamp` are not PCA tags; at least 3 PCA tags, else the well is skipped.

## Engine configuration (fixed now, no tuning)

Base as exp36: variance_fraction 0.90, alpha 0.99, min_consecutive 5, close_after 10, stuck_samples 30, no dynamic lags; 3W
`sample_period_s` 10, SKAB 1. All other settings are the engine defaults at the commit of the run. Field names follow the engine
schema; the run script maps the words below to them and is committed before the run.

| Dataset | regimes | min_rows | setpoint_like | other |
|---|---|---|---|---|
| 3W | key = `ABER-CKP` (production choke opening), quantum 10 (percent points, native tag unit) | 360 bins (1 h) | `ABER-CKGL` (gas-lift choke opening), `ABER-CKP` | stuck exemption (b) on |
| SKAB | none | not applicable | empty list (only the zero-diff share > 0.9 rule) | stuck exemption (b) on |

The quantisation step used by the stuck exemption is the engine default estimate from training data (no value set by hand).
Two arms are run on the same splits: arm B = new engine as above (targets are evaluated on arm B); arm A = exp36 configuration
(no regimes, no exemptions) on the new splits, reported only, to separate split effect from feature effect.
Ramp warning (3W only): same `unreliable_tags` rule and parameters as exp36 (90 bins, counter_like_share 0.9).

## Metrics and frozen targets (copied from exp36, same IDs and thresholds)

| ID | Metric | Target |
|---|---|---|
| F1 | False alarm events per quiet day (PCA and stuck events starting on quiet samples), pooled per dataset | <= 3 per day on 3W and on SKAB |
| F2 | Share of quiet samples inside an event | <= 0.02 |
| D1 | Detection rate: events starting at or after onset (first such event counts) | >= 0.70 per dataset |
| D2 | Median detection delay of detected files | <= 15 min (3W), <= 60 s (SKAB) |
| R1 | Ramp-warning precision on all drawn 3W files | >= 0.50 (undefined if nothing is flagged) |

Handling of unscored rows (fixed now): quiet samples that are unscored stay in the F2 denominator and in the quiet-hours base of
F1; an event file whose onset lies in unscored rows cannot be detected there and counts as a miss in D1. This makes the targets
stricter than a "scored only" reading, not looser. F2 over scored quiet samples only is reported besides.

### Targets argued to change

None. No target, threshold, tag set or binning is changed from exp36.

## Extra metrics (reported only, no target)

- `rows_unscored` share: of all rows, of quiet rows, of event-file rows; per dataset and per well (3W).
- Number of regimes fitted and under-trained per well (3W).
- Stuck-rule events kept and exempted, with the exempt counts per reason: run length seen in training, value at training min/max,
  within one quantisation step of a long-held training level, setpoint-like (list), setpoint-like (zero-diff share > 0.9).
- Calibration-slice F1/F2, arm A vs arm B, quiet days extrapolated from hours (labelled as such). Ramp recall without target.

## Honesty rules

Run once, report all numbers whatever they are. A missed target stays missed. No tuning on exp36 results or on exp40 test data: no
threshold, tag, quantum, min_rows, split or draw change after the first run (a change makes `exp40_v2`). Bug fixes that do not
change a definition are listed in results.md. Hypotheses about causes are marked as such.

Run: `python experiments/exp40_anomaly_regimes_public/run_exp40.py --data <scratch data folder with skab/ and w3/>`; without the
data it prints a SKIP message and exits 0.

## Frozen on 2026-11-18: protocol and runner merged to main by PR "exp40/exp41 frozen protocols" before any full run (the merge commit is the freeze point; results.md names it)
