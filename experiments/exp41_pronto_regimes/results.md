# exp41 results: regime-aware anomaly engine on PRONTO (issue #102)

Run once on 2026-11-18 in full mode, code and protocol frozen at main 5e55375 (merge of PR #138), engine from PR #136.
Command: `run_exp41.py --data <local pronto folder>`; data outside the repo, aggregate numbers only. Regime key: the four flow
setpoints (FIC101/102/301/302 SP), quanta 10 sm3/h and 0.1 kg/s. Leave-one-day-out over the three days.

| metric | target | arm B (regimes) | arm A (one model) | met (B) |
|---|---|---|---|---|
| F1 false alarms per quiet day | <= 3 | 37.1 | 222.8 | no |
| F2 alarm share of quiet time | <= 0.02 | 0.30 | 0.84 | no |
| D1 fault-block detection rate | >= 0.70 | 0.45 (20/44) | 0.73 (32/44) | no |
| D2 median detection delay | <= 120 s | 117.5 s | 119 s | yes |

Verdict: one of four targets met. Regimes cut false alarms 6x and the alarm share from 0.84 to 0.30, but both stay far above
target, and detection falls below target.

Why, honestly:
- Coverage: 48 % of all rows and 70 % of quiet rows were not scored (unknown or under-trained regime). Day 0912 was not scored at
  all (its 2 regimes do not occur on the other days). Fitted regimes per left-out day: 11 / 12 / 2, under-trained 3 / 2 / 0.
  9 of 44 fault blocks started in an unscored regime; that alone explains most of the detection loss versus arm A.
- Where B does score quiet rows, it alarms on all of them (`alarm_share_quiet_scored_only` = 1.0): the per-regime models do not
  transfer between days even inside the same setpoint regime.
- Stuck exemptions worked as designed: 175 stuck events in A, 58 in B, exemptions 41 setpoint_like, 35 training_run,
  5 training_limit, 3 quantised_level.
- Slugging (4 blocks) was never scored.

Conclusion: the stuck exemptions are a clear improvement and should stay. The regime split helps alarm volume only by refusing to
score; the false alarm and detection targets are not met. Three days of PRONTO are too few to cover its regimes; a real site needs
weeks of normal operation per regime. No tuning after the run.
