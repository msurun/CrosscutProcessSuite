# exp40 results: regime-aware anomaly engine and stuck exemptions on SKAB and 3W (issue #102)

Run once on 2026-11-18 in full mode, code and protocol frozen at main 5e55375 (merge of PR #138), engine from PR #136.
Command: `run_exp40.py --data <local anomaly_public folder>`; data outside the repo, aggregate numbers only.

| metric | target | SKAB B | SKAB A | 3W B | 3W A | met (B) |
|---|---|---|---|---|---|---|
| F1 false alarms per quiet day | <= 3 | 157.9 | 157.9 | 8.2 | 8.2 | no / no |
| F2 alarm share of quiet time | <= 0.02 | 0.95 | 0.95 | 1.00 | 1.00 | no / no |
| D1 detection rate | >= 0.70 | 0.06 (2/34) | 0.06 | 0.00 | 0.00 | no / no |
| D2 median delay | <= 60 s (SKAB) / 15 min (3W) | 190.5 s | 190.5 s | n/a | n/a | no / - |
| R1 possible-ramp precision | >= 0.50 | 0.31 | | | | no |

Verdict: every target missed. Arm B (new config) and arm A (old config) give identical numbers on both datasets.

Why, honestly:
- Neither dataset carries a usable regime key. SKAB has no setpoint or mode tag, and the 3W draw reduces to WELL-00005 with a
  single regime (the `--check` run already showed this before the run). So the regime feature (a) was not exercised here; this run
  says nothing for or against it.
- No stuck exemption fired (`stuck_exemptions` empty in both arms). On SKAB 36 of the 40 false events are PCA events, so the false
  alarms come from the PCA model itself (time-reversed fit on 2821 quiet rows does not transfer to the other files), not from the
  stuck rule.
- 3W: 2 quiet files, 2.9 h; one false event covering the whole quiet time. Too small to judge.

Conclusion: public SKAB and this 3W draw cannot validate issue #102. The regime feature is tested on PRONTO in exp41, which has
real setpoint changes. SKAB stays a negative result for a single global PCA model; no tuning after the run.
