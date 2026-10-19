# exp23 test report (synthetic short records): candidate J vs A

Seeds: test 6000..6099

- F (false alarms, J): MISS (worst cell neg ar050 n=1000 6.0%, pooled 0.8%)
- S (sensitivity): J 81.9%, A 50.4%
- L (long records): J 84.1%, A 85.5%
- Ship: no
- S goal 90 % not met
- L goal 98 % not met

## Reason counts (positives)

- J: too few ACF zero crossings: 17240, regular: 18973, weak ACF peak: 456, irregular: 1131
- A: too few ACF zero crossings: 25998, irregular: 473, regular: 11329

## Reason counts (negatives)

- J: too few ACF zero crossings: 1768, irregular: 282, regular: 17, weak ACF peak: 33
- A: too few ACF zero crossings: 1854, irregular: 226, regular: 20

## Per-cell detection share, negatives (percent)

| cell | J | A |
| --- | --- | --- |
| neg white n=300 | 1 | 0 |
| neg white n=1000 | 3 | 8 |
| neg white n=3000 | 1 | 3 |
| neg ar050 n=300 | 0 | 0 |
| neg ar050 n=1000 | 6 | 0 |
| neg ar050 n=3000 | 3 | 9 |
| neg ar090 n=300 | 0 | 0 |
| neg ar090 n=1000 | 0 | 0 |
| neg ar090 n=3000 | 3 | 0 |
| neg ar097 n=300 | 0 | 0 |
| neg ar097 n=1000 | 0 | 0 |
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

| cell | J | A |
| --- | --- | --- |
| pos sine n=300 c=3 snr=2.0 white | 0 | 0 |
| pos sine n=300 c=3 snr=1.0 white | 0 | 0 |
| pos sine n=300 c=3 snr=0.5 white | 0 | 0 |
| pos sine n=300 c=4 snr=2.0 white | 1 | 0 |
| pos sine n=300 c=4 snr=1.0 white | 6 | 0 |
| pos sine n=300 c=4 snr=0.5 white | 3 | 0 |
| pos sine n=300 c=5 snr=2.0 white | 86 | 0 |
| pos sine n=300 c=5 snr=1.0 white | 85 | 0 |
| pos sine n=300 c=5 snr=0.5 white | 12 | 0 |
| pos sine n=300 c=6 snr=2.0 white | 100 | 0 |
| pos sine n=300 c=6 snr=1.0 white | 99 | 0 |
| pos sine n=300 c=6 snr=0.5 white | 31 | 0 |
| pos sine n=300 c=8 snr=2.0 white | 100 | 99 |
| pos sine n=300 c=8 snr=1.0 white | 97 | 95 |
| pos sine n=300 c=8 snr=0.5 white | 25 | 11 |
| pos sine n=300 c=10 snr=2.0 white | 100 | 100 |
| pos sine n=300 c=10 snr=1.0 white | 93 | 98 |
| pos sine n=300 c=10 snr=0.5 white | 24 | 22 |
| pos sine n=300 c=20 snr=2.0 white | 98 | 100 |
| pos sine n=300 c=20 snr=1.0 white | 83 | 88 |
| pos sine n=300 c=20 snr=0.5 white | 14 | 11 |
| pos sine n=1000 c=3 snr=2.0 white | 0 | 0 |
| pos sine n=1000 c=3 snr=1.0 white | 0 | 0 |
| pos sine n=1000 c=3 snr=0.5 white | 0 | 0 |
| pos sine n=1000 c=4 snr=2.0 white | 0 | 0 |
| pos sine n=1000 c=4 snr=1.0 white | 6 | 0 |
| pos sine n=1000 c=4 snr=0.5 white | 29 | 0 |
| pos sine n=1000 c=5 snr=2.0 white | 99 | 0 |
| pos sine n=1000 c=5 snr=1.0 white | 99 | 0 |
| pos sine n=1000 c=5 snr=0.5 white | 97 | 0 |
| pos sine n=1000 c=6 snr=2.0 white | 100 | 0 |
| pos sine n=1000 c=6 snr=1.0 white | 100 | 0 |
| pos sine n=1000 c=6 snr=0.5 white | 99 | 0 |
| pos sine n=1000 c=8 snr=2.0 white | 100 | 100 |
| pos sine n=1000 c=8 snr=1.0 white | 100 | 100 |
| pos sine n=1000 c=8 snr=0.5 white | 99 | 99 |
| pos sine n=1000 c=10 snr=2.0 white | 100 | 100 |
| pos sine n=1000 c=10 snr=1.0 white | 100 | 100 |
| pos sine n=1000 c=10 snr=0.5 white | 95 | 98 |
| pos sine n=1000 c=20 snr=2.0 white | 99 | 100 |
| pos sine n=1000 c=20 snr=1.0 white | 100 | 100 |
| pos sine n=1000 c=20 snr=0.5 white | 92 | 93 |
| pos sine n=3000 c=3 snr=2.0 white | 0 | 0 |
| pos sine n=3000 c=3 snr=1.0 white | 0 | 0 |
| pos sine n=3000 c=3 snr=0.5 white | 0 | 0 |
| pos sine n=3000 c=4 snr=2.0 white | 0 | 0 |
| pos sine n=3000 c=4 snr=1.0 white | 0 | 0 |
| pos sine n=3000 c=4 snr=0.5 white | 57 | 0 |
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
| pos sine n=300 c=4 snr=2.0 ar09 | 0 | 0 |
| pos sine n=300 c=4 snr=1.0 ar09 | 0 | 0 |
| pos sine n=300 c=4 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=5 snr=2.0 ar09 | 13 | 0 |
| pos sine n=300 c=5 snr=1.0 ar09 | 0 | 0 |
| pos sine n=300 c=5 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=6 snr=2.0 ar09 | 47 | 0 |
| pos sine n=300 c=6 snr=1.0 ar09 | 1 | 0 |
| pos sine n=300 c=6 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=8 snr=2.0 ar09 | 84 | 52 |
| pos sine n=300 c=8 snr=1.0 ar09 | 5 | 1 |
| pos sine n=300 c=8 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=10 snr=2.0 ar09 | 88 | 79 |
| pos sine n=300 c=10 snr=1.0 ar09 | 2 | 3 |
| pos sine n=300 c=10 snr=0.5 ar09 | 0 | 0 |
| pos sine n=300 c=20 snr=2.0 ar09 | 87 | 92 |
| pos sine n=300 c=20 snr=1.0 ar09 | 3 | 2 |
| pos sine n=300 c=20 snr=0.5 ar09 | 0 | 0 |
| pos sine n=1000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos sine n=1000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos sine n=1000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos sine n=1000 c=4 snr=2.0 ar09 | 0 | 0 |
| pos sine n=1000 c=4 snr=1.0 ar09 | 0 | 0 |
| pos sine n=1000 c=4 snr=0.5 ar09 | 0 | 0 |
| pos sine n=1000 c=5 snr=2.0 ar09 | 52 | 0 |
| pos sine n=1000 c=5 snr=1.0 ar09 | 5 | 0 |
| pos sine n=1000 c=5 snr=0.5 ar09 | 0 | 0 |
| pos sine n=1000 c=6 snr=2.0 ar09 | 96 | 0 |
| pos sine n=1000 c=6 snr=1.0 ar09 | 19 | 0 |
| pos sine n=1000 c=6 snr=0.5 ar09 | 0 | 0 |
| pos sine n=1000 c=8 snr=2.0 ar09 | 97 | 94 |
| pos sine n=1000 c=8 snr=1.0 ar09 | 34 | 17 |
| pos sine n=1000 c=8 snr=0.5 ar09 | 3 | 2 |
| pos sine n=1000 c=10 snr=2.0 ar09 | 95 | 96 |
| pos sine n=1000 c=10 snr=1.0 ar09 | 27 | 26 |
| pos sine n=1000 c=10 snr=0.5 ar09 | 1 | 1 |
| pos sine n=1000 c=20 snr=2.0 ar09 | 95 | 97 |
| pos sine n=1000 c=20 snr=1.0 ar09 | 29 | 31 |
| pos sine n=1000 c=20 snr=0.5 ar09 | 0 | 3 |
| pos sine n=3000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos sine n=3000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos sine n=3000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos sine n=3000 c=4 snr=2.0 ar09 | 0 | 0 |
| pos sine n=3000 c=4 snr=1.0 ar09 | 0 | 0 |
| pos sine n=3000 c=4 snr=0.5 ar09 | 0 | 0 |
| pos sine n=3000 c=5 snr=2.0 ar09 | 99 | 0 |
| pos sine n=3000 c=5 snr=1.0 ar09 | 69 | 0 |
| pos sine n=3000 c=5 snr=0.5 ar09 | 14 | 0 |
| pos sine n=3000 c=6 snr=2.0 ar09 | 100 | 0 |
| pos sine n=3000 c=6 snr=1.0 ar09 | 88 | 0 |
| pos sine n=3000 c=6 snr=0.5 ar09 | 17 | 0 |
| pos sine n=3000 c=8 snr=2.0 ar09 | 100 | 100 |
| pos sine n=3000 c=8 snr=1.0 ar09 | 88 | 86 |
| pos sine n=3000 c=8 snr=0.5 ar09 | 21 | 11 |
| pos sine n=3000 c=10 snr=2.0 ar09 | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 ar09 | 86 | 94 |
| pos sine n=3000 c=10 snr=0.5 ar09 | 15 | 14 |
| pos sine n=3000 c=20 snr=2.0 ar09 | 99 | 99 |
| pos sine n=3000 c=20 snr=1.0 ar09 | 83 | 87 |
| pos sine n=3000 c=20 snr=0.5 ar09 | 18 | 15 |
| pos square n=300 c=3 snr=2.0 white | 0 | 0 |
| pos square n=300 c=3 snr=1.0 white | 0 | 0 |
| pos square n=300 c=3 snr=0.5 white | 0 | 0 |
| pos square n=300 c=4 snr=2.0 white | 7 | 0 |
| pos square n=300 c=4 snr=1.0 white | 11 | 0 |
| pos square n=300 c=4 snr=0.5 white | 4 | 0 |
| pos square n=300 c=5 snr=2.0 white | 93 | 0 |
| pos square n=300 c=5 snr=1.0 white | 94 | 0 |
| pos square n=300 c=5 snr=0.5 white | 36 | 0 |
| pos square n=300 c=6 snr=2.0 white | 100 | 0 |
| pos square n=300 c=6 snr=1.0 white | 100 | 0 |
| pos square n=300 c=6 snr=0.5 white | 68 | 0 |
| pos square n=300 c=8 snr=2.0 white | 100 | 99 |
| pos square n=300 c=8 snr=1.0 white | 98 | 98 |
| pos square n=300 c=8 snr=0.5 white | 69 | 52 |
| pos square n=300 c=10 snr=2.0 white | 100 | 100 |
| pos square n=300 c=10 snr=1.0 white | 97 | 99 |
| pos square n=300 c=10 snr=0.5 white | 57 | 55 |
| pos square n=300 c=20 snr=2.0 white | 98 | 100 |
| pos square n=300 c=20 snr=1.0 white | 94 | 96 |
| pos square n=300 c=20 snr=0.5 white | 38 | 39 |
| pos square n=1000 c=3 snr=2.0 white | 0 | 0 |
| pos square n=1000 c=3 snr=1.0 white | 0 | 0 |
| pos square n=1000 c=3 snr=0.5 white | 0 | 0 |
| pos square n=1000 c=4 snr=2.0 white | 7 | 0 |
| pos square n=1000 c=4 snr=1.0 white | 17 | 0 |
| pos square n=1000 c=4 snr=0.5 white | 41 | 0 |
| pos square n=1000 c=5 snr=2.0 white | 100 | 0 |
| pos square n=1000 c=5 snr=1.0 white | 100 | 0 |
| pos square n=1000 c=5 snr=0.5 white | 100 | 0 |
| pos square n=1000 c=6 snr=2.0 white | 100 | 0 |
| pos square n=1000 c=6 snr=1.0 white | 100 | 0 |
| pos square n=1000 c=6 snr=0.5 white | 100 | 0 |
| pos square n=1000 c=8 snr=2.0 white | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 white | 100 | 100 |
| pos square n=1000 c=8 snr=0.5 white | 100 | 100 |
| pos square n=1000 c=10 snr=2.0 white | 100 | 100 |
| pos square n=1000 c=10 snr=1.0 white | 100 | 100 |
| pos square n=1000 c=10 snr=0.5 white | 98 | 100 |
| pos square n=1000 c=20 snr=2.0 white | 99 | 100 |
| pos square n=1000 c=20 snr=1.0 white | 99 | 100 |
| pos square n=1000 c=20 snr=0.5 white | 99 | 99 |
| pos square n=3000 c=3 snr=2.0 white | 0 | 0 |
| pos square n=3000 c=3 snr=1.0 white | 0 | 0 |
| pos square n=3000 c=3 snr=0.5 white | 0 | 0 |
| pos square n=3000 c=4 snr=2.0 white | 0 | 0 |
| pos square n=3000 c=4 snr=1.0 white | 9 | 0 |
| pos square n=3000 c=4 snr=0.5 white | 68 | 0 |
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
| pos square n=300 c=3 snr=2.0 ar09 | 0 | 0 |
| pos square n=300 c=3 snr=1.0 ar09 | 0 | 0 |
| pos square n=300 c=3 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=4 snr=2.0 ar09 | 2 | 0 |
| pos square n=300 c=4 snr=1.0 ar09 | 0 | 0 |
| pos square n=300 c=4 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=5 snr=2.0 ar09 | 54 | 0 |
| pos square n=300 c=5 snr=1.0 ar09 | 3 | 0 |
| pos square n=300 c=5 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=6 snr=2.0 ar09 | 92 | 0 |
| pos square n=300 c=6 snr=1.0 ar09 | 8 | 0 |
| pos square n=300 c=6 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=8 snr=2.0 ar09 | 96 | 87 |
| pos square n=300 c=8 snr=1.0 ar09 | 24 | 9 |
| pos square n=300 c=8 snr=0.5 ar09 | 0 | 0 |
| pos square n=300 c=10 snr=2.0 ar09 | 97 | 95 |
| pos square n=300 c=10 snr=1.0 ar09 | 19 | 14 |
| pos square n=300 c=10 snr=0.5 ar09 | 2 | 1 |
| pos square n=300 c=20 snr=2.0 ar09 | 92 | 97 |
| pos square n=300 c=20 snr=1.0 ar09 | 36 | 28 |
| pos square n=300 c=20 snr=0.5 ar09 | 0 | 0 |
| pos square n=1000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos square n=1000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos square n=1000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos square n=1000 c=4 snr=2.0 ar09 | 6 | 0 |
| pos square n=1000 c=4 snr=1.0 ar09 | 1 | 0 |
| pos square n=1000 c=4 snr=0.5 ar09 | 0 | 0 |
| pos square n=1000 c=5 snr=2.0 ar09 | 94 | 0 |
| pos square n=1000 c=5 snr=1.0 ar09 | 21 | 0 |
| pos square n=1000 c=5 snr=0.5 ar09 | 0 | 0 |
| pos square n=1000 c=6 snr=2.0 ar09 | 100 | 0 |
| pos square n=1000 c=6 snr=1.0 ar09 | 61 | 0 |
| pos square n=1000 c=6 snr=0.5 ar09 | 1 | 0 |
| pos square n=1000 c=8 snr=2.0 ar09 | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 ar09 | 76 | 55 |
| pos square n=1000 c=8 snr=0.5 ar09 | 6 | 5 |
| pos square n=1000 c=10 snr=2.0 ar09 | 100 | 100 |
| pos square n=1000 c=10 snr=1.0 ar09 | 65 | 64 |
| pos square n=1000 c=10 snr=0.5 ar09 | 8 | 5 |
| pos square n=1000 c=20 snr=2.0 ar09 | 97 | 100 |
| pos square n=1000 c=20 snr=1.0 ar09 | 66 | 68 |
| pos square n=1000 c=20 snr=0.5 ar09 | 5 | 7 |
| pos square n=3000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos square n=3000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos square n=3000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos square n=3000 c=4 snr=2.0 ar09 | 4 | 0 |
| pos square n=3000 c=4 snr=1.0 ar09 | 8 | 0 |
| pos square n=3000 c=4 snr=0.5 ar09 | 2 | 0 |
| pos square n=3000 c=5 snr=2.0 ar09 | 100 | 0 |
| pos square n=3000 c=5 snr=1.0 ar09 | 96 | 0 |
| pos square n=3000 c=5 snr=0.5 ar09 | 26 | 0 |
| pos square n=3000 c=6 snr=2.0 ar09 | 100 | 0 |
| pos square n=3000 c=6 snr=1.0 ar09 | 99 | 0 |
| pos square n=3000 c=6 snr=0.5 ar09 | 39 | 0 |
| pos square n=3000 c=8 snr=2.0 ar09 | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 ar09 | 98 | 99 |
| pos square n=3000 c=8 snr=0.5 ar09 | 46 | 35 |
| pos square n=3000 c=10 snr=2.0 ar09 | 99 | 100 |
| pos square n=3000 c=10 snr=1.0 ar09 | 99 | 99 |
| pos square n=3000 c=10 snr=0.5 ar09 | 38 | 40 |
| pos square n=3000 c=20 snr=2.0 ar09 | 99 | 100 |
| pos square n=3000 c=20 snr=1.0 ar09 | 98 | 98 |
| pos square n=3000 c=20 snr=0.5 ar09 | 28 | 35 |
| pos lagged_square n=300 c=3 snr=2.0 white | 0 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 white | 0 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 white | 0 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 white | 0 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 white | 10 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 white | 3 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 white | 86 | 0 |
| pos lagged_square n=300 c=5 snr=1.0 white | 82 | 0 |
| pos lagged_square n=300 c=5 snr=0.5 white | 16 | 0 |
| pos lagged_square n=300 c=6 snr=2.0 white | 100 | 0 |
| pos lagged_square n=300 c=6 snr=1.0 white | 98 | 0 |
| pos lagged_square n=300 c=6 snr=0.5 white | 28 | 0 |
| pos lagged_square n=300 c=8 snr=2.0 white | 100 | 99 |
| pos lagged_square n=300 c=8 snr=1.0 white | 97 | 94 |
| pos lagged_square n=300 c=8 snr=0.5 white | 32 | 17 |
| pos lagged_square n=300 c=10 snr=2.0 white | 100 | 99 |
| pos lagged_square n=300 c=10 snr=1.0 white | 93 | 97 |
| pos lagged_square n=300 c=10 snr=0.5 white | 22 | 25 |
| pos lagged_square n=300 c=20 snr=2.0 white | 98 | 100 |
| pos lagged_square n=300 c=20 snr=1.0 white | 80 | 85 |
| pos lagged_square n=300 c=20 snr=0.5 white | 12 | 13 |
| pos lagged_square n=1000 c=3 snr=2.0 white | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 white | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 white | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 white | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 white | 11 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 white | 28 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 white | 99 | 0 |
| pos lagged_square n=1000 c=5 snr=1.0 white | 98 | 0 |
| pos lagged_square n=1000 c=5 snr=0.5 white | 96 | 0 |
| pos lagged_square n=1000 c=6 snr=2.0 white | 100 | 0 |
| pos lagged_square n=1000 c=6 snr=1.0 white | 100 | 0 |
| pos lagged_square n=1000 c=6 snr=0.5 white | 100 | 0 |
| pos lagged_square n=1000 c=8 snr=2.0 white | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=1.0 white | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=0.5 white | 98 | 100 |
| pos lagged_square n=1000 c=10 snr=2.0 white | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=1.0 white | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=0.5 white | 97 | 98 |
| pos lagged_square n=1000 c=20 snr=2.0 white | 99 | 100 |
| pos lagged_square n=1000 c=20 snr=1.0 white | 100 | 100 |
| pos lagged_square n=1000 c=20 snr=0.5 white | 91 | 92 |
| pos lagged_square n=3000 c=3 snr=2.0 white | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 white | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 white | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 white | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 white | 1 | 0 |
| pos lagged_square n=3000 c=4 snr=0.5 white | 60 | 0 |
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
| pos lagged_square n=300 c=3 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 ar09 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 ar09 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 ar09 | 12 | 0 |
| pos lagged_square n=300 c=5 snr=1.0 ar09 | 1 | 0 |
| pos lagged_square n=300 c=5 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=6 snr=2.0 ar09 | 56 | 0 |
| pos lagged_square n=300 c=6 snr=1.0 ar09 | 1 | 0 |
| pos lagged_square n=300 c=6 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=8 snr=2.0 ar09 | 83 | 54 |
| pos lagged_square n=300 c=8 snr=1.0 ar09 | 6 | 2 |
| pos lagged_square n=300 c=8 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=300 c=10 snr=2.0 ar09 | 90 | 79 |
| pos lagged_square n=300 c=10 snr=1.0 ar09 | 3 | 2 |
| pos lagged_square n=300 c=10 snr=0.5 ar09 | 1 | 1 |
| pos lagged_square n=300 c=20 snr=2.0 ar09 | 86 | 90 |
| pos lagged_square n=300 c=20 snr=1.0 ar09 | 4 | 1 |
| pos lagged_square n=300 c=20 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 ar09 | 54 | 0 |
| pos lagged_square n=1000 c=5 snr=1.0 ar09 | 3 | 0 |
| pos lagged_square n=1000 c=5 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=6 snr=2.0 ar09 | 97 | 0 |
| pos lagged_square n=1000 c=6 snr=1.0 ar09 | 22 | 0 |
| pos lagged_square n=1000 c=6 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=1000 c=8 snr=2.0 ar09 | 100 | 98 |
| pos lagged_square n=1000 c=8 snr=1.0 ar09 | 36 | 15 |
| pos lagged_square n=1000 c=8 snr=0.5 ar09 | 3 | 1 |
| pos lagged_square n=1000 c=10 snr=2.0 ar09 | 99 | 98 |
| pos lagged_square n=1000 c=10 snr=1.0 ar09 | 37 | 32 |
| pos lagged_square n=1000 c=10 snr=0.5 ar09 | 1 | 1 |
| pos lagged_square n=1000 c=20 snr=2.0 ar09 | 94 | 97 |
| pos lagged_square n=1000 c=20 snr=1.0 ar09 | 27 | 33 |
| pos lagged_square n=1000 c=20 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=2.0 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 ar09 | 3 | 0 |
| pos lagged_square n=3000 c=4 snr=0.5 ar09 | 0 | 0 |
| pos lagged_square n=3000 c=5 snr=2.0 ar09 | 98 | 0 |
| pos lagged_square n=3000 c=5 snr=1.0 ar09 | 69 | 0 |
| pos lagged_square n=3000 c=5 snr=0.5 ar09 | 11 | 0 |
| pos lagged_square n=3000 c=6 snr=2.0 ar09 | 100 | 0 |
| pos lagged_square n=3000 c=6 snr=1.0 ar09 | 85 | 0 |
| pos lagged_square n=3000 c=6 snr=0.5 ar09 | 21 | 0 |
| pos lagged_square n=3000 c=8 snr=2.0 ar09 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 ar09 | 89 | 87 |
| pos lagged_square n=3000 c=8 snr=0.5 ar09 | 24 | 14 |
| pos lagged_square n=3000 c=10 snr=2.0 ar09 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 ar09 | 88 | 89 |
| pos lagged_square n=3000 c=10 snr=0.5 ar09 | 15 | 18 |
| pos lagged_square n=3000 c=20 snr=2.0 ar09 | 99 | 99 |
| pos lagged_square n=3000 c=20 snr=1.0 ar09 | 87 | 89 |
| pos lagged_square n=3000 c=20 snr=0.5 ar09 | 13 | 16 |
