# Soft sensor backup mode: validation protocol (stub)

Status: protocol only. No data has been downloaded and no experiment has been run (issue #82).

## Question

Does the virtual sensor, taking over while the reference measurement is invalid, keep the output
error acceptable, and does the hysteresis keep the number of switches low?

## Data

1. Public: the Kaggle flotation data set (CC0). Record the exact data set URL, version and download
   date in `docs/PROVENANCE.md` before use. The silica concentrate column plays the analyser, the
   process columns the model inputs. Do not commit the data.
2. Simulated: RougherSim analyser faults (frozen value, bad quality, out of range, analyser flag)
   injected into the simulated analyser tag.

## Outage simulation (public data)

Mask the analyser column with a seeded generator (seed written in the result file):

- outage lengths drawn from a fixed set (for example 0.5, 2, 8 and 24 h), start times uniform;
- four outage kinds: NaN (bad quality), frozen at the last value, constant out-of-range value,
  analyser flag set;
- keep the true analyser value as the reference for scoring only.

## Method

Fit the soft sensor on the first part of the record (no outage), run backup mode over the rest.
All backup settings (`frozen_s`, `range_lo`, `range_hi`, `return_hold_s`) are chosen before the
run from the training part alone and are written down; no tuning on the scored part.

## Metrics

- RMSE of the output against the true analyser value inside outages, compared with a hold-last-value
  baseline and with no substitution (output NaN).
- Detection delay: time from outage start to the switch to backup, per outage kind.
- Switches per outage and per day (chatter), and the time to return after the outage ends
  (should be close to `return_hold_s`).
- Share of outage rows with quality code 2 (unavailable).

## Acceptance (to be fixed before running)

Thresholds are set in the experiment note before the first run and are not changed afterwards.
