# exp21 test report (synthetic short records): candidate G vs A

Seeds: test 3000..3099

- F (false alarms, G): PASS (worst cell neg white n=1000 3.0%, pooled 0.5%)
- S (sensitivity): G 82.5%, A 50.1%
- L (long records): G 80.6%, A 84.9%
- Ship: no
- S goal 90 % not met
- L goal 98 % not met

## Reason counts (positives)

- G: too few ACF zero crossings: 10735, weak ACF peak: 2663, regular: 21922, irregular: 2480
- A: too few ACF zero crossings: 26060, regular: 11206, irregular: 534

## Reason counts (negatives)

- G: weak ACF peak: 97, irregular: 452, too few ACF zero crossings: 1541, regular: 10
- A: too few ACF zero crossings: 1856, irregular: 216, regular: 28

## Per-cell detection share, negatives (percent)

| cell | G | A |
| --- | --- | --- |
| neg white n=300 | 1 | 0 |
| neg white n=1000 | 3 | 7 |
| neg white n=3000 | 1 | 7 |
| neg ar050 n=300 | 0 | 0 |
| neg ar050 n=1000 | 1 | 1 |
| neg ar050 n=3000 | 2 | 12 |
| neg ar090 n=300 | 0 | 0 |
| neg ar090 n=1000 | 0 | 0 |
| neg ar090 n=3000 | 1 | 1 |
| neg ar097 n=300 | 0 | 0 |
| neg ar097 n=1000 | 1 | 0 |
| neg ar097 n=3000 | 0 | 0 |
| neg ar099 n=300 | 0 | 0 |
| neg ar099 n=1000 | 0 | 0 |
| neg ar099 n=3000 | 0 | 0 |
| neg random_walk n=300 | 0 | 0 |
| neg random_walk n=1000 | 0 | 0 |
| neg random_walk n=3000 | 0 | 0 |
| neg sp_steps n=300 | 0 | 0 |
| neg sp_steps n=1000 | 0 | 0 |
| neg sp_steps n=3000 | 0 | 0 |

## Per-cell detection share, positives (percent)

| cell | G | A |
| --- | --- | --- |
| pos sine n=300 c=3 snr=2.0 white | 0 | 0 |
| pos sine n=300 c=3 snr=1.0 white | 2 | 0 |
| pos sine n=300 c=3 snr=0.5 white | 4 | 0 |
| pos sine n=300 c=4 snr=2.0 white | 95 | 0 |
| pos sine n=300 c=4 snr=1.0 white | 81 | 0 |
| pos sine n=300 c=4 snr=0.5 white | 29 | 0 |
| pos sine n=300 c=5 snr=2.0 white | 100 | 0 |
| pos sine n=300 c=5 snr=1.0 white | 96 | 0 |
| pos sine n=300 c=5 snr=0.5 white | 23 | 0 |
| pos sine n=300 c=6 snr=2.0 white | 100 | 1 |
| pos sine n=300 c=6 snr=1.0 white | 98 | 1 |
| pos sine n=300 c=6 snr=0.5 white | 29 | 0 |
| pos sine n=300 c=8 snr=2.0 white | 100 | 99 |
| pos sine n=300 c=8 snr=1.0 white | 98 | 91 |
| pos sine n=300 c=8 snr=0.5 white | 22 | 21 |
| pos sine n=300 c=10 snr=2.0 white | 100 | 100 |
| pos sine n=300 c=10 snr=1.0 white | 98 | 92 |
| pos sine n=300 c=10 snr=0.5 white | 22 | 23 |
| pos sine n=300 c=20 snr=2.0 white | 89 | 98 |
| pos sine n=300 c=20 snr=1.0 white | 74 | 88 |
| pos sine n=300 c=20 snr=0.5 white | 3 | 11 |
| pos sine n=1000 c=3 snr=2.0 white | 0 | 0 |
| pos sine n=1000 c=3 snr=1.0 white | 0 | 0 |
| pos sine n=1000 c=3 snr=0.5 white | 5 | 0 |
| pos sine n=1000 c=4 snr=2.0 white | 100 | 0 |
| pos sine n=1000 c=4 snr=1.0 white | 100 | 0 |
| pos sine n=1000 c=4 snr=0.5 white | 95 | 0 |
| pos sine n=1000 c=5 snr=2.0 white | 100 | 0 |
| pos sine n=1000 c=5 snr=1.0 white | 100 | 0 |
| pos sine n=1000 c=5 snr=0.5 white | 97 | 0 |
| pos sine n=1000 c=6 snr=2.0 white | 100 | 0 |
| pos sine n=1000 c=6 snr=1.0 white | 100 | 0 |
| pos sine n=1000 c=6 snr=0.5 white | 97 | 0 |
| pos sine n=1000 c=8 snr=2.0 white | 100 | 100 |
| pos sine n=1000 c=8 snr=1.0 white | 100 | 100 |
| pos sine n=1000 c=8 snr=0.5 white | 97 | 96 |
| pos sine n=1000 c=10 snr=2.0 white | 100 | 100 |
| pos sine n=1000 c=10 snr=1.0 white | 100 | 100 |
| pos sine n=1000 c=10 snr=0.5 white | 99 | 99 |
| pos sine n=1000 c=20 snr=2.0 white | 100 | 100 |
| pos sine n=1000 c=20 snr=1.0 white | 100 | 100 |
| pos sine n=1000 c=20 snr=0.5 white | 92 | 86 |
| pos sine n=3000 c=3 snr=2.0 white | 0 | 0 |
| pos sine n=3000 c=3 snr=1.0 white | 0 | 0 |
| pos sine n=3000 c=3 snr=0.5 white | 2 | 0 |
| pos sine n=3000 c=4 snr=2.0 white | 100 | 0 |
| pos sine n=3000 c=4 snr=1.0 white | 100 | 0 |
| pos sine n=3000 c=4 snr=0.5 white | 100 | 0 |
| pos sine n=3000 c=5 snr=2.0 white | 100 | 0 |
| pos sine n=3000 c=5 snr=1.0 white | 100 | 0 |
| pos sine n=3000 c=5 snr=0.5 white | 100 | 0 |
| pos sine n=3000 c=6 snr=2.0 white | 100 | 0 |
| pos sine n=3000 c=6 snr=1.0 white | 100 | 0 |
| pos sine n=3000 c=6 snr=0.5 white | 100 | 0 |
| pos sine n=3000 c=8 snr=2.0 white | 100 | 100 |
| pos sine n=3000 c=8 snr=1.0 white | 100 | 100 |
| pos sine n=3000 c=8 snr=0.5 white | 100 | 100 |
| pos sine n=3000 c=10 snr=2.0 white | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 white | 100 | 100 |
| pos sine n=3000 c=10 snr=0.5 white | 100 | 100 |
| pos sine n=3000 c=20 snr=2.0 white | 100 | 100 |
| pos sine n=3000 c=20 snr=1.0 white | 100 | 100 |
| pos sine n=3000 c=20 snr=0.5 white | 100 | 100 |
| pos sine n=300 c=3 snr=2.0 ar09 | 0 | 0 |
| pos sine n=300 c=3 snr=1.0 ar09 | 0 | 0 |
| pos sine n=300 c=3 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=4 snr=2.0 ar09 | 3 | 0 |
| pos sine n=300 c=4 snr=1.0 ar09 | 0 | 0 |
| pos sine n=300 c=4 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=5 snr=2.0 ar09 | 33 | 0 |
| pos sine n=300 c=5 snr=1.0 ar09 | 3 | 0 |
| pos sine n=300 c=5 snr=0.5 ar09 | 2 | 0 |
| pos sine n=300 c=6 snr=2.0 ar09 | 55 | 0 |
| pos sine n=300 c=6 snr=1.0 ar09 | 4 | 0 |
| pos sine n=300 c=6 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=8 snr=2.0 ar09 | 71 | 57 |
| pos sine n=300 c=8 snr=1.0 ar09 | 1 | 1 |
| pos sine n=300 c=8 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=10 snr=2.0 ar09 | 75 | 77 |
| pos sine n=300 c=10 snr=1.0 ar09 | 1 | 2 |
| pos sine n=300 c=10 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=20 snr=2.0 ar09 | 67 | 91 |
| pos sine n=300 c=20 snr=1.0 ar09 | 1 | 1 |
| pos sine n=300 c=20 snr=0.5 ar09 | 0 | 0 |
| pos sine n=1000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos sine n=1000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos sine n=1000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos sine n=1000 c=4 snr=2.0 ar09 | 42 | 0 |
| pos sine n=1000 c=4 snr=1.0 ar09 | 5 | 0 |
| pos sine n=1000 c=4 snr=0.5 ar09 | 1 | 0 |
| pos sine n=1000 c=5 snr=2.0 ar09 | 79 | 0 |
| pos sine n=1000 c=5 snr=1.0 ar09 | 11 | 0 |
| pos sine n=1000 c=5 snr=0.5 ar09 | 1 | 0 |
| pos sine n=1000 c=6 snr=2.0 ar09 | 97 | 0 |
| pos sine n=1000 c=6 snr=1.0 ar09 | 22 | 0 |
| pos sine n=1000 c=6 snr=0.5 ar09 | 4 | 0 |
| pos sine n=1000 c=8 snr=2.0 ar09 | 99 | 93 |
| pos sine n=1000 c=8 snr=1.0 ar09 | 16 | 24 |
| pos sine n=1000 c=8 snr=0.5 ar09 | 3 | 0 |
| pos sine n=1000 c=10 snr=2.0 ar09 | 99 | 97 |
| pos sine n=1000 c=10 snr=1.0 ar09 | 23 | 27 |
| pos sine n=1000 c=10 snr=0.5 ar09 | 0 | 1 |
| pos sine n=1000 c=20 snr=2.0 ar09 | 94 | 96 |
| pos sine n=1000 c=20 snr=1.0 ar09 | 17 | 22 |
| pos sine n=1000 c=20 snr=0.5 ar09 | 0 | 1 |
| pos sine n=3000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos sine n=3000 c=3 snr=1.0 ar09 | 1 | 0 |
| pos sine n=3000 c=3 snr=0.5 ar09 | 3 | 0 |
| pos sine n=3000 c=4 snr=2.0 ar09 | 94 | 0 |
| pos sine n=3000 c=4 snr=1.0 ar09 | 50 | 0 |
| pos sine n=3000 c=4 snr=0.5 ar09 | 14 | 0 |
| pos sine n=3000 c=5 snr=2.0 ar09 | 100 | 0 |
| pos sine n=3000 c=5 snr=1.0 ar09 | 86 | 0 |
| pos sine n=3000 c=5 snr=0.5 ar09 | 19 | 0 |
| pos sine n=3000 c=6 snr=2.0 ar09 | 100 | 0 |
| pos sine n=3000 c=6 snr=1.0 ar09 | 82 | 0 |
| pos sine n=3000 c=6 snr=0.5 ar09 | 16 | 0 |
| pos sine n=3000 c=8 snr=2.0 ar09 | 100 | 100 |
| pos sine n=3000 c=8 snr=1.0 ar09 | 92 | 88 |
| pos sine n=3000 c=8 snr=0.5 ar09 | 13 | 12 |
| pos sine n=3000 c=10 snr=2.0 ar09 | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 ar09 | 95 | 92 |
| pos sine n=3000 c=10 snr=0.5 ar09 | 11 | 17 |
| pos sine n=3000 c=20 snr=2.0 ar09 | 100 | 100 |
| pos sine n=3000 c=20 snr=1.0 ar09 | 94 | 89 |
| pos sine n=3000 c=20 snr=0.5 ar09 | 3 | 17 |
| pos square n=300 c=3 snr=2.0 white | 3 | 0 |
| pos square n=300 c=3 snr=1.0 white | 3 | 0 |
| pos square n=300 c=3 snr=0.5 white | 5 | 0 |
| pos square n=300 c=4 snr=2.0 white | 99 | 0 |
| pos square n=300 c=4 snr=1.0 white | 98 | 0 |
| pos square n=300 c=4 snr=0.5 white | 44 | 0 |
| pos square n=300 c=5 snr=2.0 white | 100 | 0 |
| pos square n=300 c=5 snr=1.0 white | 100 | 0 |
| pos square n=300 c=5 snr=0.5 white | 68 | 0 |
| pos square n=300 c=6 snr=2.0 white | 100 | 1 |
| pos square n=300 c=6 snr=1.0 white | 100 | 1 |
| pos square n=300 c=6 snr=0.5 white | 62 | 0 |
| pos square n=300 c=8 snr=2.0 white | 100 | 99 |
| pos square n=300 c=8 snr=1.0 white | 100 | 96 |
| pos square n=300 c=8 snr=0.5 white | 53 | 49 |
| pos square n=300 c=10 snr=2.0 white | 100 | 100 |
| pos square n=300 c=10 snr=1.0 white | 100 | 99 |
| pos square n=300 c=10 snr=0.5 white | 45 | 45 |
| pos square n=300 c=20 snr=2.0 white | 88 | 98 |
| pos square n=300 c=20 snr=1.0 white | 84 | 96 |
| pos square n=300 c=20 snr=0.5 white | 22 | 27 |
| pos square n=1000 c=3 snr=2.0 white | 0 | 0 |
| pos square n=1000 c=3 snr=1.0 white | 0 | 0 |
| pos square n=1000 c=3 snr=0.5 white | 0 | 0 |
| pos square n=1000 c=4 snr=2.0 white | 100 | 0 |
| pos square n=1000 c=4 snr=1.0 white | 100 | 0 |
| pos square n=1000 c=4 snr=0.5 white | 100 | 0 |
| pos square n=1000 c=5 snr=2.0 white | 100 | 0 |
| pos square n=1000 c=5 snr=1.0 white | 100 | 0 |
| pos square n=1000 c=5 snr=0.5 white | 100 | 0 |
| pos square n=1000 c=6 snr=2.0 white | 100 | 0 |
| pos square n=1000 c=6 snr=1.0 white | 100 | 0 |
| pos square n=1000 c=6 snr=0.5 white | 100 | 0 |
| pos square n=1000 c=8 snr=2.0 white | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 white | 100 | 100 |
| pos square n=1000 c=8 snr=0.5 white | 100 | 99 |
| pos square n=1000 c=10 snr=2.0 white | 100 | 100 |
| pos square n=1000 c=10 snr=1.0 white | 100 | 100 |
| pos square n=1000 c=10 snr=0.5 white | 100 | 100 |
| pos square n=1000 c=20 snr=2.0 white | 100 | 100 |
| pos square n=1000 c=20 snr=1.0 white | 100 | 100 |
| pos square n=1000 c=20 snr=0.5 white | 98 | 96 |
| pos square n=3000 c=3 snr=2.0 white | 0 | 0 |
| pos square n=3000 c=3 snr=1.0 white | 0 | 0 |
| pos square n=3000 c=3 snr=0.5 white | 0 | 0 |
| pos square n=3000 c=4 snr=2.0 white | 100 | 0 |
| pos square n=3000 c=4 snr=1.0 white | 100 | 0 |
| pos square n=3000 c=4 snr=0.5 white | 100 | 0 |
| pos square n=3000 c=5 snr=2.0 white | 100 | 0 |
| pos square n=3000 c=5 snr=1.0 white | 100 | 0 |
| pos square n=3000 c=5 snr=0.5 white | 100 | 0 |
| pos square n=3000 c=6 snr=2.0 white | 100 | 0 |
| pos square n=3000 c=6 snr=1.0 white | 100 | 0 |
| pos square n=3000 c=6 snr=0.5 white | 100 | 0 |
| pos square n=3000 c=8 snr=2.0 white | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 white | 100 | 100 |
| pos square n=3000 c=8 snr=0.5 white | 100 | 100 |
| pos square n=3000 c=10 snr=2.0 white | 100 | 100 |
| pos square n=3000 c=10 snr=1.0 white | 100 | 100 |
| pos square n=3000 c=10 snr=0.5 white | 100 | 100 |
| pos square n=3000 c=20 snr=2.0 white | 100 | 100 |
| pos square n=3000 c=20 snr=1.0 white | 100 | 100 |
| pos square n=3000 c=20 snr=0.5 white | 100 | 100 |
| pos square n=300 c=3 snr=2.0 ar09 | 1 | 0 |
| pos square n=300 c=3 snr=1.0 ar09 | 0 | 0 |
| pos square n=300 c=3 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=4 snr=2.0 ar09 | 53 | 0 |
| pos square n=300 c=4 snr=1.0 ar09 | 1 | 0 |
| pos square n=300 c=4 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=5 snr=2.0 ar09 | 95 | 0 |
| pos square n=300 c=5 snr=1.0 ar09 | 7 | 0 |
| pos square n=300 c=5 snr=0.5 ar09 | 3 | 0 |
| pos square n=300 c=6 snr=2.0 ar09 | 97 | 0 |
| pos square n=300 c=6 snr=1.0 ar09 | 10 | 0 |
| pos square n=300 c=6 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=8 snr=2.0 ar09 | 98 | 78 |
| pos square n=300 c=8 snr=1.0 ar09 | 12 | 7 |
| pos square n=300 c=8 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=10 snr=2.0 ar09 | 96 | 90 |
| pos square n=300 c=10 snr=1.0 ar09 | 16 | 14 |
| pos square n=300 c=10 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=20 snr=2.0 ar09 | 81 | 97 |
| pos square n=300 c=20 snr=1.0 ar09 | 16 | 27 |
| pos square n=300 c=20 snr=0.5 ar09 | 0 | 0 |
| pos square n=1000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos square n=1000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos square n=1000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos square n=1000 c=4 snr=2.0 ar09 | 95 | 0 |
| pos square n=1000 c=4 snr=1.0 ar09 | 27 | 0 |
| pos square n=1000 c=4 snr=0.5 ar09 | 2 | 0 |
| pos square n=1000 c=5 snr=2.0 ar09 | 100 | 0 |
| pos square n=1000 c=5 snr=1.0 ar09 | 45 | 0 |
| pos square n=1000 c=5 snr=0.5 ar09 | 2 | 0 |
| pos square n=1000 c=6 snr=2.0 ar09 | 100 | 0 |
| pos square n=1000 c=6 snr=1.0 ar09 | 57 | 0 |
| pos square n=1000 c=6 snr=0.5 ar09 | 7 | 0 |
| pos square n=1000 c=8 snr=2.0 ar09 | 100 | 99 |
| pos square n=1000 c=8 snr=1.0 ar09 | 57 | 54 |
| pos square n=1000 c=8 snr=0.5 ar09 | 4 | 3 |
| pos square n=1000 c=10 snr=2.0 ar09 | 100 | 99 |
| pos square n=1000 c=10 snr=1.0 ar09 | 74 | 63 |
| pos square n=1000 c=10 snr=0.5 ar09 | 2 | 1 |
| pos square n=1000 c=20 snr=2.0 ar09 | 97 | 99 |
| pos square n=1000 c=20 snr=1.0 ar09 | 66 | 68 |
| pos square n=1000 c=20 snr=0.5 ar09 | 1 | 3 |
| pos square n=3000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos square n=3000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos square n=3000 c=3 snr=0.5 ar09 | 2 | 0 |
| pos square n=3000 c=4 snr=2.0 ar09 | 100 | 0 |
| pos square n=3000 c=4 snr=1.0 ar09 | 94 | 0 |
| pos square n=3000 c=4 snr=0.5 ar09 | 32 | 0 |
| pos square n=3000 c=5 snr=2.0 ar09 | 100 | 0 |
| pos square n=3000 c=5 snr=1.0 ar09 | 99 | 0 |
| pos square n=3000 c=5 snr=0.5 ar09 | 44 | 0 |
| pos square n=3000 c=6 snr=2.0 ar09 | 100 | 0 |
| pos square n=3000 c=6 snr=1.0 ar09 | 100 | 0 |
| pos square n=3000 c=6 snr=0.5 ar09 | 41 | 0 |
| pos square n=3000 c=8 snr=2.0 ar09 | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 ar09 | 100 | 100 |
| pos square n=3000 c=8 snr=0.5 ar09 | 36 | 45 |
| pos square n=3000 c=10 snr=2.0 ar09 | 100 | 100 |
| pos square n=3000 c=10 snr=1.0 ar09 | 100 | 99 |
| pos square n=3000 c=10 snr=0.5 ar09 | 39 | 43 |
| pos square n=3000 c=20 snr=2.0 ar09 | 100 | 100 |
| pos square n=3000 c=20 snr=1.0 ar09 | 99 | 98 |
| pos square n=3000 c=20 snr=0.5 ar09 | 23 | 32 |
| pos lagged_square n=300 c=3 snr=2.0 white | 1 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 white | 0 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 white | 6 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 white | 84 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 white | 79 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 white | 30 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 white | 100 | 0 |
| pos lagged_square n=300 c=5 snr=1.0 white | 98 | 0 |
| pos lagged_square n=300 c=5 snr=0.5 white | 25 | 0 |
| pos lagged_square n=300 c=6 snr=2.0 white | 100 | 1 |
| pos lagged_square n=300 c=6 snr=1.0 white | 99 | 1 |
| pos lagged_square n=300 c=6 snr=0.5 white | 30 | 0 |
| pos lagged_square n=300 c=8 snr=2.0 white | 100 | 99 |
| pos lagged_square n=300 c=8 snr=1.0 white | 97 | 89 |
| pos lagged_square n=300 c=8 snr=0.5 white | 17 | 10 |
| pos lagged_square n=300 c=10 snr=2.0 white | 100 | 100 |
| pos lagged_square n=300 c=10 snr=1.0 white | 99 | 93 |
| pos lagged_square n=300 c=10 snr=0.5 white | 13 | 20 |
| pos lagged_square n=300 c=20 snr=2.0 white | 84 | 98 |
| pos lagged_square n=300 c=20 snr=1.0 white | 78 | 86 |
| pos lagged_square n=300 c=20 snr=0.5 white | 4 | 13 |
| pos lagged_square n=1000 c=3 snr=2.0 white | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 white | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 white | 11 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 white | 99 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 white | 100 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 white | 96 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 white | 100 | 0 |
| pos lagged_square n=1000 c=5 snr=1.0 white | 100 | 0 |
| pos lagged_square n=1000 c=5 snr=0.5 white | 97 | 0 |
| pos lagged_square n=1000 c=6 snr=2.0 white | 100 | 0 |
| pos lagged_square n=1000 c=6 snr=1.0 white | 100 | 0 |
| pos lagged_square n=1000 c=6 snr=0.5 white | 97 | 0 |
| pos lagged_square n=1000 c=8 snr=2.0 white | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=1.0 white | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=0.5 white | 98 | 98 |
| pos lagged_square n=1000 c=10 snr=2.0 white | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=1.0 white | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=0.5 white | 98 | 97 |
| pos lagged_square n=1000 c=20 snr=2.0 white | 100 | 100 |
| pos lagged_square n=1000 c=20 snr=1.0 white | 100 | 100 |
| pos lagged_square n=1000 c=20 snr=0.5 white | 92 | 90 |
| pos lagged_square n=3000 c=3 snr=2.0 white | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 white | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 white | 2 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 white | 99 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 white | 100 | 0 |
| pos lagged_square n=3000 c=4 snr=0.5 white | 100 | 0 |
| pos lagged_square n=3000 c=5 snr=2.0 white | 100 | 0 |
| pos lagged_square n=3000 c=5 snr=1.0 white | 100 | 0 |
| pos lagged_square n=3000 c=5 snr=0.5 white | 100 | 0 |
| pos lagged_square n=3000 c=6 snr=2.0 white | 100 | 0 |
| pos lagged_square n=3000 c=6 snr=1.0 white | 100 | 0 |
| pos lagged_square n=3000 c=6 snr=0.5 white | 100 | 0 |
| pos lagged_square n=3000 c=8 snr=2.0 white | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 white | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=0.5 white | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=2.0 white | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 white | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=0.5 white | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=2.0 white | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=1.0 white | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=0.5 white | 100 | 100 |
| pos lagged_square n=300 c=3 snr=2.0 ar09 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 ar09 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 ar09 | 1 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 ar09 | 7 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 ar09 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 ar09 | 34 | 0 |
| pos lagged_square n=300 c=5 snr=1.0 ar09 | 4 | 0 |
| pos lagged_square n=300 c=5 snr=0.5 ar09 | 1 | 0 |
| pos lagged_square n=300 c=6 snr=2.0 ar09 | 53 | 0 |
| pos lagged_square n=300 c=6 snr=1.0 ar09 | 2 | 0 |
| pos lagged_square n=300 c=6 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=8 snr=2.0 ar09 | 76 | 54 |
| pos lagged_square n=300 c=8 snr=1.0 ar09 | 0 | 0 |
| pos lagged_square n=300 c=8 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=10 snr=2.0 ar09 | 76 | 68 |
| pos lagged_square n=300 c=10 snr=1.0 ar09 | 3 | 1 |
| pos lagged_square n=300 c=10 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=20 snr=2.0 ar09 | 69 | 90 |
| pos lagged_square n=300 c=20 snr=1.0 ar09 | 4 | 2 |
| pos lagged_square n=300 c=20 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 ar09 | 50 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 ar09 | 7 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 ar09 | 1 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 ar09 | 86 | 0 |
| pos lagged_square n=1000 c=5 snr=1.0 ar09 | 9 | 0 |
| pos lagged_square n=1000 c=5 snr=0.5 ar09 | 1 | 0 |
| pos lagged_square n=1000 c=6 snr=2.0 ar09 | 94 | 0 |
| pos lagged_square n=1000 c=6 snr=1.0 ar09 | 26 | 0 |
| pos lagged_square n=1000 c=6 snr=0.5 ar09 | 3 | 0 |
| pos lagged_square n=1000 c=8 snr=2.0 ar09 | 99 | 93 |
| pos lagged_square n=1000 c=8 snr=1.0 ar09 | 22 | 17 |
| pos lagged_square n=1000 c=8 snr=0.5 ar09 | 1 | 1 |
| pos lagged_square n=1000 c=10 snr=2.0 ar09 | 99 | 94 |
| pos lagged_square n=1000 c=10 snr=1.0 ar09 | 28 | 27 |
| pos lagged_square n=1000 c=10 snr=0.5 ar09 | 1 | 0 |
| pos lagged_square n=1000 c=20 snr=2.0 ar09 | 93 | 97 |
| pos lagged_square n=1000 c=20 snr=1.0 ar09 | 17 | 28 |
| pos lagged_square n=1000 c=20 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 ar09 | 1 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 ar09 | 88 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 ar09 | 53 | 0 |
| pos lagged_square n=3000 c=4 snr=0.5 ar09 | 15 | 0 |
| pos lagged_square n=3000 c=5 snr=2.0 ar09 | 100 | 0 |
| pos lagged_square n=3000 c=5 snr=1.0 ar09 | 87 | 0 |
| pos lagged_square n=3000 c=5 snr=0.5 ar09 | 21 | 0 |
| pos lagged_square n=3000 c=6 snr=2.0 ar09 | 100 | 0 |
| pos lagged_square n=3000 c=6 snr=1.0 ar09 | 87 | 0 |
| pos lagged_square n=3000 c=6 snr=0.5 ar09 | 13 | 0 |
| pos lagged_square n=3000 c=8 snr=2.0 ar09 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 ar09 | 91 | 90 |
| pos lagged_square n=3000 c=8 snr=0.5 ar09 | 10 | 13 |
| pos lagged_square n=3000 c=10 snr=2.0 ar09 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 ar09 | 91 | 90 |
| pos lagged_square n=3000 c=10 snr=0.5 ar09 | 14 | 15 |
| pos lagged_square n=3000 c=20 snr=2.0 ar09 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=1.0 ar09 | 90 | 86 |
| pos lagged_square n=3000 c=20 snr=0.5 ar09 | 9 | 9 |
