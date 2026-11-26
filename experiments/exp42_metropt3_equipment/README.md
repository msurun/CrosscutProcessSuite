# exp42: frozen MetroPT-3 per-equipment anomaly protocol (#160)

Status: frozen protocol only, 2026-11-26; no scoring run. Module: anomaly,
product phase 1 equipment monitoring. This follows exp40/exp41's predeclared
split, fixed engine defaults, explicit unscored denominator and no-tuning policy.
Those directories freeze configuration in README/script constants; this experiment
also supplies a machine-readable `frozen_config.json`.

Hypothesis: one compressor's lagged normal-operation PCA, learned on the first
month, can meet all three targets below on the remaining months without label-based
training exclusions, threshold changes or retraining. The freeze point is the
commit accepting this protocol, before any full scoring run. Any substantive change
after scoring creates exp42_v2; report definition-preserving bug fixes explicitly.

## Source and split

Davari, N., Veloso, B., Ribeiro, R. and Gama, J. (2021), MetroPT-3,
[UCI 791](https://archive.ics.uci.edu/dataset/791/metropt+3+dataset),
[DOI 10.24432/C5VW3R](https://doi.org/10.24432/C5VW3R), CC BY 4.0.
Attribution applies to the copied failure table below. The source files remain
outside the repository:

- `C:/Users/regiz/data/metropt3/MetroPT3(AirCompressor).csv`
- `C:/Users/regiz/data/metropt3/Data Description_Metro.pdf`

UCI recommends the first month for training and the rest for testing. Here this
means training [2020-02-01 00:00, 2020-03-01 00:00), scoring all supplied rows
on or after 2020-03-01 through the end of the February-August release. February
includes stopped, starting, unloaded and loaded operation: no failure, state,
maintenance or running exclusions, no calibration split, no incremental updates.
The engine intrinsically requires finite rows and uninterrupted stretches of at
least 30 samples; its lag construction and sample sufficiency checks still apply.
These are mechanical validity checks, not curated normal-label exclusions.

The supplied CSV has 10-second samples (UCI's variable description says 0.1 Hz).
The PDF describes the original 1 Hz logging; do not resample the released CSV.
Ignore the exported index column. Preserve input order and timestamps; reject
empty, duplicated, unsorted or invalid timestamps and missing/nonnumeric columns.
Keep NaN/infinity measurements unavailable, without imputation or row deletion.
Timestamps and failure labels use the same naive source clock; no timezone/DST
conversion is inferred. Runtime's UTC formatting is only an epoch encoding of
that clock, reversed before matching.

## Equipment and fixed model

Equipment is exactly the train compressor/APU, not one equipment per sensor.
`load_metropt3(path)` returns a naive DatetimeIndex of n timestamps, an n x 7
float matrix in config measurement order, and an aligned n x 8 state DataFrame.

| Signal(s), exact CSV names | Meaning and role |
|---|---|
| Motor_current | A; condition signal (off near 0, unloaded near 4, loaded near 7, starting near 9 per PDF) |
| TP2, TP3, H1 | bar; compressor, pneumatic panel and separator-discharge pressures |
| DV_pressure, Reservoirs | bar; dryer pressure drop and downstream reservoir pressure |
| Oil_temperature | degrees C; thermal condition/context |
| COMP, MPG | binary intake/unloaded and load-start command context |
| DV_eletric | binary outlet valve/load context; spelling preserved from CSV |
| Towers, Pressure_switch | binary dryer tower and discharge context |
| LPS | binary low-pressure indication below 7 bar; context, not a failure label |
| Oil_level, Caudal_impulses | digital oil-level and air-flow pulse context |

All 15 signals enter the existing equipment model: analogue condition/process
measurements plus digital state/regime keys as contextual variables. Digital
signals are never treated as stuck faults. The current equipment learner has no
per-regime dispatch interface: state keys enter joint lagged PCA, not separately
fitted regime models. Unknown states therefore are not automatically unscored.
This deliberately evaluates main's per-equipment implementation, not exp41's
separate anomaly engine. No invented control loops, OUT proxies, or running gate.
With no actual loop OUT tags, conditional current/temperature regressions and
residual EWMA are absent; the runner reports PCA-based alarms only.

Use public `learn_equipment` and `EquipmentScanJob.run` APIs. Defaults frozen:
one sample lag, variance fraction 0.90, alpha 0.99, constants allowed, at least
max(50, 10 * number of augmented variables) finite training rows. No stuck rule.
Runtime persistence 3 abnormal samples, clear after 5 normal samples; opening is
the third abnormal row's timestamp (no backdating). Abnormal means T2 or SPE
strictly above its fitted limit. No shelves. No model refitting on scoring rows.
Missing values reset lag/counters via runtime behavior; an existing alarm stays
open. Gaps > 15 seconds reset model lag/counters through public job state, while
restoring an existing event identity from runtime persistence. Warmup rows are
unscored. A model that cannot fit raises an explicit error, never a passing result.

## Failure table (copied from source)

Source: `Data Description_Metro.pdf`, final page, Failure Information; also UCI's
Failure Information. All are Air leak / High stress. Source numbering and report
text are preserved, including duplicate #1 and the apparently inconsistent April
maintenance date for the May event. Neither is silently corrected.

| Source Nr. | Start Time | End Time | Failure | Severity | Report |
|---|---|---|---|---|---|
| #1 | 4/18/2020 0:00 | 4/18/2020 23:59 | Air leak | High stress | |
| #1 | 5/29/2020 23:30 | 5/30/2020 6:00 | Air Leak | High stress | Maintenance on 30Apr at 12:00 |
| #3 | 6/5/2020 10:00 | 6/7/2020 14:30 | Air Leak | High stress | Maintenance on 8Jun at 16:00 |
| #4 | 7/15/2020 14:30 | 7/15/2020 19:00 | Air Leak | High stress | Maintenance on 16Jul at 00:00 |

## Metrics and targets (frozen from #160)

An alarm event is one runtime opening identity, deduplicated across persisted
revisions. Clearing and reopening creates a new event. An alarm already open
before a matching window is not credited unless it clears and opens again inside.

- Event detection >= 70%: detected failures / all four source failure events.
  A failure is detected iff at least one alarm opens in inclusive [start - 2 h, end].
  Multiple alarms in a window credit the failure once. Thus at least 3/4 must be
  detected. Unscored failure rows cannot remove a failure from the denominator.
- False alarms <= 3 per normal day: distinct openings outside the union of those
  inclusive warning windows / observed normal days. Normal means every scoring
  row outside those windows, including stopped operation; it does not assert
  that absence of a report proves health. Each observed normal row contributes
  10 seconds, so normal days = normal row count * 10 / 86400. Gaps contribute
  no exposure. Unscored normal rows remain in exposure. An unmatched opening
  counts once, regardless of alarm duration; an event extending into normal time
  is not a new false alarm. Repeated openings inside a warning window are not
  false alarms. Zero normal exposure is an error, not a zero rate.
- Scored-row coverage >= 80%: rows with both non-null PCA T2 and SPE / all
  supplied scoring rows. Missing, warmup, stopped and unavailable rows remain
  in the denominator. Scored does not mean normal. No hidden scored-only metrics.

All three targets must pass. Report each raw metric, detection flags and row
count, including failures. No tuning against this held-out period. Labels are used
only for evaluation, never model construction. Only synthetic tests are run in
this task. There is no `results.md` until an explicitly authorized future run:

```powershell
python experiments/exp42_metropt3_equipment/exp42.py --data 'C:/Users/regiz/data/metropt3/MetroPT3(AirCompressor).csv'
python -m pytest experiments/exp42_metropt3_equipment -q
```

The full runner writes aggregate `results.md`; its temporary model/event files
are cleaned up. No dataset rows, model payloads or event logs are committed.
