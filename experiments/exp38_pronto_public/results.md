# exp38 results (protocol exp38_v1, run once 2026-11-18, issue #87)

Aggregate numbers only; no PRONTO-derived data is committed (CC BY 4.0, used locally). Protocol and targets: README.md (frozen in
commit e65bae6). Run: `run_exp38.py --data <folder with the case-study tree>`.

## Outcome: every frozen target is missed

| ID | Target | PRONTO | Met |
|---|---|---|---|
| F1 false alarm events per quiet day | <= 3 | 199.8 (19 events in 2.28 quiet h, extrapolated) | no |
| F2 share of quiet samples inside an event | <= 0.02 | 0.96 | no |
| D1 detection rate over 44 fault blocks | >= 0.70 | 26 of 44 = 0.59 | no |
| D2 median delay of detected fault blocks | <= 120 s | 140.5 s | no |
| R1 ramp-warning precision | n/a | not evaluated (no NaN gaps) | - |

Without target: quiet at the fit set point (0.39 h) 6 events, alarm share 0.79; quiet at another set point (1.89 h) 13 events,
alarm share 1.00. Share of fault-block samples inside an event 0.995. Slugging blocks (regime, 4 blocks): 1 detected, delay 124 s.
Per day: 0907 40 events (32 stuck), 0911 80 (78 stuck), 0912 33 (30 stuck). Fit sizes 949 / 205 / 296 samples, 19 tags each.

## Reading the numbers (what the data supports, no more)

- Same picture as exp36: a model fitted on a few minutes at one set point treats almost all quiet data as anomalous. Air and water
  set points change between blocks (air 20-200 sm3/h, water 0.1-3.5 kg/s), so "normal" here is a family of operating points; the
  single-point fit does not cover them (other-set-point quiet alarm share 1.00), and even at the fit set point 79 % of quiet samples are
  inside events (fits of 3.4 to 16 min, 0911 only 205 samples).
- The detection rate of 0.59 and the inside share of 0.995 say that events are open nearly the whole day, so detection mostly
  reflects whether a new event happens to start inside a block, not fault sensitivity. D1/D2 are not evidence of fault detection.
- Most events are stuck-rule events (140 of 153): several tags are exactly constant over 30 s at 1 s resolution (valve positions,
  tank level); counts only, as in exp36.
- Fault blocks are 1-12 min and the operation log is hand-written and misaligned (valve-change times vs Labview start times, a few
  ambiguous stretches excluded); the 120 s delay target and the block edges are protocol choices, not facts of the dataset.
- Quiet days are extrapolated from 2.3 h.

## Departures and bugs (listed, definitions unchanged)

- The csv has duplicate column names; columns are read by position (19 measurement columns) instead of by name.
- Only 3 of the 4 process-data files used: 0626Testday5 (2018) has another tag layout and no operation log entry.
- Data taken from the Zenodo zip by HTTP range requests (process-data csv and operation log, about 21 MB); the full archive was not downloaded.
- No other changes after the first run.

## Next steps

- Same as exp36: diagnose the shift (per-set-point models or models fitted on several blocks, drop constant tags from the stuck rule,
  scale per record); a change makes exp38_v2.
