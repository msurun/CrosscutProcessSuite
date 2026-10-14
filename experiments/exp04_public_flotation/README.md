# Experiment 4: loop monitoring on public plant data (first test outside the simulator)

Data: "Quality Prediction in a Mining Process" (E. M. Oliveira, Kaggle, licence CC0: Public Domain, checked on the
Kaggle API 2026-10-14), a flotation plant, March-September 2017. Not committed; download it yourself and pass the path:
`python experiments/exp04_public_flotation/run.py <MiningProcess_Flotation_Plant_Database.csv>`. Row sampling 20 s
(timestamps are only hourly in the file; the loader rebuilds the time inside each hour).

What the data CANNOT do: it has no setpoint, no controller output and no mode. So stiction detection (needs OUT),
manual/saturation findings and the tuning report are not applicable, and there is no ground truth for any verdict.
This run therefore makes no accuracy claim. It checks that the PV-only parts of the analysis run on real, messy data
and what they say.

## Method (frozen 2026-10-14, before the first run)

- Columns: 7 air flows, 7 column levels, ore pulp flow, pH, density (all 20 s). Lab columns (iron/silica, hourly values
  repeated on every row) are used only as a loader sanity check.
- Segments: runs without a gap longer than 60 s, at least 6 h (1080 samples).
- Error signal: PV minus the segment median (there is no setpoint; this is an assumption, stated in the report).
- Oscillation: `hagglund_oscillation`, amplitude limit 5 % of the segment's 5-95 % span, ultimate period 600 s.
  Not tuned afterwards. Flatline: `flatline_fraction`, runs of at least 30 samples (10 min).
- Expectation written down now: (1) the loader check passes: each lab column is flat on > 99 % of samples;
  (2) the analysis runs on every segment without error; (3) no claim is made about which loops are "bad".

## Result (run 2026-10-14, report: `results/report.md`)

- Data shape: 737,453 rows in 4,097 hours (180 rows per hour, except two hours with 174 and 179), 318 missing hours
  (including one gap of about 13 days), so two gap-free segments of at least 6 h.
- Expectation (1) was only half right. The feed lab columns are one value per hour in all 4,097 hours (flat 1.000), but
  in 310 hours the concentrate columns change linearly inside the hour (flat share 0.969 and 0.957): the file holds
  interpolated lab values there. The loader is right; the threshold stays as written and the check is reported as
  FAILED for the two concentrate columns, with this explanation. Do not treat those columns as repeated hourly values.
- Expectation (2) held: the analysis ran on every segment without error.
- Oscillation flag: 17 of 19 columns flagged oscillating in both segments, with periods from 160 s to 57,000 s. With no
  setpoint (median used instead) and an untuned 5 % amplitude limit the flag is nearly always on, so on this data it
  does not discriminate between loops. Two air flows (columns 04 and 05) have a flat share of 0.54 (stuck for half the
  record, or an instrument that holds its value): the one finding here that is worth a look in the data itself.
- Not shown, because the data cannot show it: stiction, saturation, manual mode, tuning, any accuracy figure.
  Conclusion: the PV-only checks run on real data, but need a setpoint (or a known amplitude limit per loop) before
  an "oscillating" finding means anything.
