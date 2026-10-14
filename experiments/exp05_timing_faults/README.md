# exp05: do the loop checks cope with timestamp jitter and mode flips?

Question (V1 fault layer): when the historian stamps samples late or early, or the operator takes a loop to
manual for a while, do `monitor.analyze_loop` and `readiness.check_readiness` still give the right answer?

Setup: mill circuit loop `mill_feed`, nominal scenario, 6 h, 1 s samples, seeds 1-5, operator off.
Jitter: `timing_faults.jitter_timestamps`, sigma 0.2 / 1 / 3 s (stamps are used as the time axis, values keep
their nominal order). Mode flips: 1, 3 and 6 flips of 10 min to MAN (`timing_faults.mode_flip_events`).

## Acceptance targets (frozen before the first run, 2026-10-14)

- **J1 (small jitter, sigma 0.2 s):** classification equals the baseline in at least 4 of 5 seeds and the Harris
  index changes by at most 20 % (relative) in at least 4 of 5 seeds.
- **J2 (readiness):** for sigma 1 s and 3 s the readiness check reports a warning or failure about sampling
  regularity in at least 4 of 5 seeds; for sigma 0.2 s it may stay quiet.
- **J3 (large jitter, sigma 3 s):** no crash; if the classification differs from the baseline this is reported,
  not counted as failure (it documents a limit).
- **M1 (mode flips):** `mode_changes` equals 2 x flips in every seed; the service factor drops by
  flips x 10 min / 6 h within 0.02; the classification equals the baseline in at least 4 of 5 seeds for 1 and 3 flips;
  the Harris index is finite whenever an AUTO stretch of at least `min_segment_samples` exists.

If a target is missed the finding is logged as it is; the thresholds are not changed afterwards.

## Result (run 2026-10-14, `python exp05.py`, table in `results/results.md`)

All frozen targets PASS: J1 5/5, J2 5/5, M1 5/5; J3 informational: no crash and no classification change at sigma 3 s.

What the numbers say, and what they do not:
- **Jitter biases the Harris index upwards.** Mean over 5 seeds: baseline 0.765, sigma 0.2 s 0.765, sigma 1 s 0.816 (+7 %),
  sigma 3 s 0.848 (+11 %). The values are unchanged, only the stamps are; the cause is `monitor.analyze_loop`, which takes
  `dt_s` as the median of the stamp differences and turns the dead time into samples with `round(delay_s / dt_s)`. A jittered
  median step is not exactly 1 s, so the benchmark delay changes. The loop looks healthier than it is; the class stays "ok"
  here, but a loop near a threshold could flip. Candidate fix (not applied, needs a decision): take the nominal period from
  the readiness check or use `(t_end - t_start) / (n - 1)` when the record has no large gaps.
- The readiness check also warns at sigma 0.2 s (`time_regularity`), so it is more sensitive than the targets required.
- Mode flips are counted exactly (2 per flip), the service factor drops by exactly flips x 10 min / 6 h, the Harris index stays
  finite on the longest AUTO stretch. Its value moves by up to about 15 % with 6 flips because the longest AUTO stretch
  becomes shorter (seeds 2 and 5), so it is a noisier estimate, not a biased one.
- Limits: one plant, one loop, synthetic data, delay model of a historian only (Gaussian, independent per sample); real
  historians also stamp in bursts after a network gap, which this does not model. The `duration` warning in every row is the
  6 h record being shorter than the readiness minimum, not a fault.
