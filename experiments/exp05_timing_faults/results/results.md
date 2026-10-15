# Experiment 05: Timing Faults and Mode Flips Results

Evaluation of timestamp jitter and manual mode flips on mill circuit feed loop.

## Metrics Tables

### Baseline (Nominal)

| Seed | Classification | Harris Index | Service Factor | Mode Changes | Non-OK Count | Non-OK Check Names |
|---|---|---|---|---|---|---|
| 1 | ok | 0.7427 | 1.0000 | 0 | 1 | duration |
| 2 | ok | 0.7865 | 1.0000 | 0 | 1 | duration |
| 3 | ok | 0.7510 | 1.0000 | 0 | 1 | duration |
| 4 | ok | 0.7891 | 1.0000 | 0 | 1 | duration |
| 5 | ok | 0.7541 | 1.0000 | 0 | 1 | duration |

### Jitter Sigma = 0.2 s

| Seed | Classification | Harris Index | Service Factor | Mode Changes | Non-OK Count | Non-OK Check Names |
|---|---|---|---|---|---|---|
| 1 | ok | 0.7427 | 1.0000 | 0 | 2 | duration, time_regularity |
| 2 | ok | 0.7865 | 1.0000 | 0 | 2 | duration, time_regularity |
| 3 | ok | 0.7510 | 1.0000 | 0 | 2 | duration, time_regularity |
| 4 | ok | 0.7891 | 1.0000 | 0 | 2 | duration, time_regularity |
| 5 | ok | 0.7541 | 1.0000 | 0 | 2 | duration, time_regularity |

### Jitter Sigma = 1.0 s

| Seed | Classification | Harris Index | Service Factor | Mode Changes | Non-OK Count | Non-OK Check Names |
|---|---|---|---|---|---|---|
| 1 | ok | 0.7427 | 1.0000 | 0 | 2 | duration, time_regularity |
| 2 | ok | 0.7865 | 1.0000 | 0 | 2 | duration, time_regularity |
| 3 | ok | 0.7510 | 1.0000 | 0 | 2 | duration, time_regularity |
| 4 | ok | 0.7891 | 1.0000 | 0 | 2 | duration, time_regularity |
| 5 | ok | 0.7541 | 1.0000 | 0 | 2 | duration, time_regularity |

### Jitter Sigma = 3.0 s

| Seed | Classification | Harris Index | Service Factor | Mode Changes | Non-OK Count | Non-OK Check Names |
|---|---|---|---|---|---|---|
| 1 | ok | 0.7427 | 1.0000 | 0 | 2 | duration, time_regularity |
| 2 | ok | 0.7865 | 1.0000 | 0 | 2 | duration, time_regularity |
| 3 | ok | 0.7510 | 1.0000 | 0 | 2 | duration, time_regularity |
| 4 | ok | 0.7891 | 1.0000 | 0 | 2 | duration, time_regularity |
| 5 | ok | 0.7541 | 1.0000 | 0 | 2 | duration, time_regularity |

### Mode Flips n = 1 (10 min each)

| Seed | Classification | Harris Index | Service Factor | Mode Changes | Non-OK Count | Non-OK Check Names |
|---|---|---|---|---|---|---|
| 1 | ok | 0.7716 | 0.9722 | 2 | 1 | duration |
| 2 | ok | 0.7743 | 0.9722 | 2 | 1 | duration |
| 3 | ok | 0.7791 | 0.9722 | 2 | 1 | duration |
| 4 | ok | 0.7743 | 0.9722 | 2 | 1 | duration |
| 5 | ok | 0.8072 | 0.9722 | 2 | 1 | duration |

### Mode Flips n = 3 (10 min each)

| Seed | Classification | Harris Index | Service Factor | Mode Changes | Non-OK Count | Non-OK Check Names |
|---|---|---|---|---|---|---|
| 1 | ok | 0.7370 | 0.9167 | 6 | 1 | duration |
| 2 | ok | 0.7132 | 0.9167 | 6 | 1 | duration |
| 3 | ok | 0.7653 | 0.9167 | 6 | 1 | duration |
| 4 | ok | 0.7992 | 0.9167 | 6 | 1 | duration |
| 5 | ok | 0.8756 | 0.9167 | 6 | 1 | duration |

### Mode Flips n = 6 (10 min each)

| Seed | Classification | Harris Index | Service Factor | Mode Changes | Non-OK Count | Non-OK Check Names |
|---|---|---|---|---|---|---|
| 1 | ok | 0.7066 | 0.8333 | 12 | 1 | duration |
| 2 | ok | 0.6697 | 0.8333 | 12 | 1 | duration |
| 3 | ok | 0.8012 | 0.8333 | 12 | 1 | duration |
| 4 | ok | 0.7346 | 0.8333 | 12 | 1 | duration |
| 5 | ok | 0.8666 | 0.8333 | 12 | 1 | duration |

## Targets

- **J1 (small jitter, sigma 0.2 s)**: **PASS** (5/5 seeds matched baseline classification and Harris index within 20%)
- **J2 (readiness)**: **PASS** (5/5 seeds raised sampling regularity warnings at sigma 1.0 s and 3.0 s)
- **J3 (large jitter, sigma 3 s)**: **INFO** (No crashes; 0/5 seeds differed in classification from baseline)
- **M1 (mode flips)**: **PASS** (5/5 seeds satisfied mode change counts, service drop within 0.02, finite Harris, and classification)
