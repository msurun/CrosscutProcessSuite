# exp25 results - guided valve stroke test

Seeds 100..119, OP start 50 %, tolerance 0.25 % of span.

## Frozen targets

| target | value | minimum | verdict |
|---|---|---|---|
| V1 deadband within tolerance | 1.00 | 0.90 | PASS |
| V2 healthy valve | 1.00 | 0.95 | PASS |
| V3 abort detected | 1.00 | 1.00 | PASS |

## Report-only tables

### share within tolerance by noise and load

| key | runs | share |
|---|---|---|
| noise 0.00 / load none | 1080 | 1.00 |
| noise 0.00 / load step | 1080 | 0.90 |
| noise 0.05 / load none | 1080 | 1.00 |
| noise 0.05 / load step | 1080 | 0.90 |
| noise 0.20 / load none | 1080 | 0.88 |
| noise 0.20 / load step | 1080 | 0.87 |

### share within tolerance by true deadband

| key | runs | share |
|---|---|---|
| 0.00 % | 720 | 0.67 |
| 0.30 % | 1440 | 0.98 |
| 0.80 % | 2160 | 0.98 |
| 2.00 % | 2160 | 0.92 |

### share within tolerance by tau

| key | runs | share |
|---|---|---|
| 20 s | 3240 | 0.93 |
| 3 s | 3240 | 0.92 |

### resolution_le available per true resolution

| key | runs | share |
|---|---|---|
| true 0.00 % | 2880 | 1.00 |
| true 0.10 % | 2160 | 1.00 |
| true 0.40 % | 1440 | 1.00 |

### reason counts

| key | runs | share |
|---|---|---|
| (complete) | 6480 | 1.00 |
