# exp42 results

```json
{
  "false_alarms": 9883,
  "normal_days": 146.9175925925926,
  "false_alarms_per_normal_day": 67.26900315747679,
  "events_detected": [
    true,
    true,
    true,
    false
  ],
  "event_detection": 0.75,
  "coverage": 0.9997480988374147,
  "scoring_rows": 1302098,
  "targets_passed": {
    "false_alarms": false,
    "event_detection": true,
    "coverage": true
  }
}
```

## Verdict (single run of the frozen protocol, 2026-11-26)

- Event detection 3/4 = 0.75 (target >= 0.70): **met**. Missed: source failure #4 (2020-07-15 14:30-19:00).
- Scored-row coverage 0.9997 (target >= 0.80): **met**.
- False alarms 9883 openings over 146.9 normal days = **67.3 per day** (target <= 3): **not met**.

The #160 acceptance gate is **not passed**. As frozen, no threshold, persistence or training change is made on this run; any change is a new experiment line (exp42_v2) with its own freeze. The joint lagged PCA over all 15 signals, including digital state keys without per-regime models, is the leading suspect for the alarm rate (load/unload cycling of the compressor is a regime change the model treats as abnormal); see #160.
