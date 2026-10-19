# exp23 dev report (synthetic short records)

Seeds: dev 4000..4099

## Summary

| candidate | F pass | worst negative cell | pooled neg | S pool | L share | c3-4 share | snr0.5 share | chosen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | no | neg ar050 n=3000 (12.0%) | 1.4% | 50.2% | 85.6% | 0.0% | 17.3% |  |
| I | yes | neg white n=300 (1.0%) | 0.2% | 78.7% | 83.9% | 1.3% | 28.6% |  |
| J | yes | neg white n=1000 (5.0%) | 0.8% | 81.5% | 84.4% | 1.6% | 32.1% | yes |
| M | yes | neg white n=300 (1.0%) | 0.2% | 77.2% | 85.7% | 0.0% | 26.0% |  |

Winner: **J**

## Reason counts (positives)

- A: too few ACF zero crossings: 26080, regular: 11223, irregular: 497
- I: too few ACF zero crossings: 17339, regular: 17859, weak ACF peak: 1418, irregular: 1184
- J: too few ACF zero crossings: 17339, regular: 18827, weak ACF peak: 450, irregular: 1184
- M: too few ACF zero crossings: 18507, regular: 17175, weak ACF peak: 1308, irregular: 810

## Reason counts (negatives)

- A: too few ACF zero crossings: 1851, irregular: 219, regular: 30
- I: too few ACF zero crossings: 1775, irregular: 270, weak ACF peak: 51, regular: 4
- J: too few ACF zero crossings: 1775, irregular: 270, weak ACF peak: 38, regular: 17
- M: too few ACF zero crossings: 1779, irregular: 265, weak ACF peak: 52, regular: 4

## Per-cell detection share, negatives (percent)

| cell | A | I | J | M |
| --- | --- | --- | --- | --- |
| neg white n=300 | 0 | 1 | 1 | 1 |
| neg white n=1000 | 10 | 1 | 5 | 1 |
| neg white n=3000 | 4 | 0 | 1 | 0 |
| neg ar050 n=300 | 0 | 0 | 0 | 0 |
| neg ar050 n=1000 | 3 | 1 | 5 | 1 |
| neg ar050 n=3000 | 12 | 1 | 5 | 1 |
| neg ar090 n=300 | 0 | 0 | 0 | 0 |
| neg ar090 n=1000 | 0 | 0 | 0 | 0 |
| neg ar090 n=3000 | 1 | 0 | 0 | 0 |
| neg ar097 n=300 | 0 | 0 | 0 | 0 |
| neg ar097 n=1000 | 0 | 0 | 0 | 0 |
| neg ar097 n=3000 | 0 | 0 | 0 | 0 |
| neg ar099 n=300 | 0 | 0 | 0 | 0 |
| neg ar099 n=1000 | 0 | 0 | 0 | 0 |
| neg ar099 n=3000 | 0 | 0 | 0 | 0 |
| neg random_walk n=300 | 0 | 0 | 0 | 0 |
| neg random_walk n=1000 | 0 | 0 | 0 | 0 |
| neg random_walk n=3000 | 0 | 0 | 0 | 0 |
| neg sp_steps n=300 | 0 | 0 | 0 | 0 |
| neg sp_steps n=1000 | 0 | 0 | 0 | 0 |
| neg sp_steps n=3000 | 0 | 0 | 0 | 0 |

## Per-cell detection share, positives (percent)

| cell | A | I | J | M |
| --- | --- | --- | --- | --- |
| pos sine n=300 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos sine n=300 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos sine n=300 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos sine n=300 c=4 snr=2.0 white | 0 | 1 | 1 | 0 |
| pos sine n=300 c=4 snr=1.0 white | 0 | 2 | 7 | 0 |
| pos sine n=300 c=4 snr=0.5 white | 0 | 0 | 2 | 0 |
| pos sine n=300 c=5 snr=2.0 white | 0 | 84 | 84 | 57 |
| pos sine n=300 c=5 snr=1.0 white | 0 | 65 | 75 | 43 |
| pos sine n=300 c=5 snr=0.5 white | 0 | 6 | 15 | 1 |
| pos sine n=300 c=6 snr=2.0 white | 1 | 100 | 100 | 100 |
| pos sine n=300 c=6 snr=1.0 white | 0 | 91 | 96 | 91 |
| pos sine n=300 c=6 snr=0.5 white | 0 | 16 | 29 | 16 |
| pos sine n=300 c=8 snr=2.0 white | 99 | 100 | 100 | 100 |
| pos sine n=300 c=8 snr=1.0 white | 90 | 96 | 97 | 99 |
| pos sine n=300 c=8 snr=0.5 white | 13 | 13 | 27 | 15 |
| pos sine n=300 c=10 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos sine n=300 c=10 snr=1.0 white | 95 | 95 | 95 | 98 |
| pos sine n=300 c=10 snr=0.5 white | 23 | 11 | 26 | 11 |
| pos sine n=300 c=20 snr=2.0 white | 100 | 99 | 99 | 100 |
| pos sine n=300 c=20 snr=1.0 white | 88 | 86 | 86 | 88 |
| pos sine n=300 c=20 snr=0.5 white | 15 | 14 | 22 | 14 |
| pos sine n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=4 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=4 snr=1.0 white | 0 | 4 | 4 | 0 |
| pos sine n=1000 c=4 snr=0.5 white | 0 | 30 | 39 | 0 |
| pos sine n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 85 |
| pos sine n=1000 c=5 snr=1.0 white | 0 | 100 | 100 | 85 |
| pos sine n=1000 c=5 snr=0.5 white | 0 | 82 | 94 | 61 |
| pos sine n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 |
| pos sine n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 |
| pos sine n=1000 c=6 snr=0.5 white | 0 | 94 | 100 | 94 |
| pos sine n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=8 snr=0.5 white | 98 | 96 | 98 | 98 |
| pos sine n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=10 snr=0.5 white | 97 | 89 | 92 | 93 |
| pos sine n=1000 c=20 snr=2.0 white | 100 | 98 | 98 | 100 |
| pos sine n=1000 c=20 snr=1.0 white | 99 | 98 | 98 | 99 |
| pos sine n=1000 c=20 snr=0.5 white | 85 | 81 | 81 | 85 |
| pos sine n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=4 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=4 snr=1.0 white | 0 | 1 | 1 | 0 |
| pos sine n=3000 c=4 snr=0.5 white | 0 | 61 | 61 | 0 |
| pos sine n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 92 |
| pos sine n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 97 |
| pos sine n=3000 c=5 snr=0.5 white | 0 | 100 | 100 | 99 |
| pos sine n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 |
| pos sine n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 |
| pos sine n=3000 c=6 snr=0.5 white | 0 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos sine n=300 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=4 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=5 snr=2.0 ar09 | 0 | 6 | 11 | 6 |
| pos sine n=300 c=5 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=5 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=6 snr=2.0 ar09 | 0 | 32 | 47 | 32 |
| pos sine n=300 c=6 snr=1.0 ar09 | 0 | 0 | 4 | 0 |
| pos sine n=300 c=6 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=8 snr=2.0 ar09 | 48 | 60 | 78 | 63 |
| pos sine n=300 c=8 snr=1.0 ar09 | 2 | 1 | 4 | 1 |
| pos sine n=300 c=8 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=10 snr=2.0 ar09 | 73 | 72 | 79 | 83 |
| pos sine n=300 c=10 snr=1.0 ar09 | 2 | 3 | 4 | 3 |
| pos sine n=300 c=10 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=20 snr=2.0 ar09 | 91 | 88 | 88 | 91 |
| pos sine n=300 c=20 snr=1.0 ar09 | 2 | 0 | 1 | 0 |
| pos sine n=300 c=20 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=4 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=5 snr=2.0 ar09 | 0 | 41 | 52 | 34 |
| pos sine n=1000 c=5 snr=1.0 ar09 | 0 | 0 | 5 | 0 |
| pos sine n=1000 c=5 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=6 snr=2.0 ar09 | 0 | 87 | 96 | 87 |
| pos sine n=1000 c=6 snr=1.0 ar09 | 0 | 6 | 15 | 6 |
| pos sine n=1000 c=6 snr=0.5 ar09 | 0 | 0 | 2 | 0 |
| pos sine n=1000 c=8 snr=2.0 ar09 | 96 | 96 | 98 | 97 |
| pos sine n=1000 c=8 snr=1.0 ar09 | 19 | 17 | 33 | 17 |
| pos sine n=1000 c=8 snr=0.5 ar09 | 1 | 0 | 3 | 0 |
| pos sine n=1000 c=10 snr=2.0 ar09 | 96 | 97 | 97 | 97 |
| pos sine n=1000 c=10 snr=1.0 ar09 | 24 | 14 | 31 | 15 |
| pos sine n=1000 c=10 snr=0.5 ar09 | 2 | 1 | 1 | 1 |
| pos sine n=1000 c=20 snr=2.0 ar09 | 96 | 92 | 92 | 96 |
| pos sine n=1000 c=20 snr=1.0 ar09 | 21 | 20 | 25 | 22 |
| pos sine n=1000 c=20 snr=0.5 ar09 | 0 | 1 | 1 | 1 |
| pos sine n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=4 snr=1.0 ar09 | 0 | 1 | 2 | 0 |
| pos sine n=3000 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=5 snr=2.0 ar09 | 0 | 93 | 97 | 83 |
| pos sine n=3000 c=5 snr=1.0 ar09 | 0 | 43 | 61 | 34 |
| pos sine n=3000 c=5 snr=0.5 ar09 | 0 | 4 | 13 | 0 |
| pos sine n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 100 |
| pos sine n=3000 c=6 snr=1.0 ar09 | 0 | 64 | 93 | 64 |
| pos sine n=3000 c=6 snr=0.5 ar09 | 0 | 4 | 9 | 4 |
| pos sine n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=1.0 ar09 | 82 | 78 | 84 | 84 |
| pos sine n=3000 c=8 snr=0.5 ar09 | 8 | 12 | 19 | 13 |
| pos sine n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 ar09 | 91 | 78 | 82 | 88 |
| pos sine n=3000 c=10 snr=0.5 ar09 | 15 | 7 | 14 | 8 |
| pos sine n=3000 c=20 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=1.0 ar09 | 91 | 91 | 91 | 91 |
| pos sine n=3000 c=20 snr=0.5 ar09 | 7 | 6 | 8 | 6 |
| pos square n=300 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos square n=300 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos square n=300 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos square n=300 c=4 snr=2.0 white | 0 | 9 | 9 | 0 |
| pos square n=300 c=4 snr=1.0 white | 0 | 13 | 17 | 0 |
| pos square n=300 c=4 snr=0.5 white | 0 | 1 | 2 | 0 |
| pos square n=300 c=5 snr=2.0 white | 0 | 95 | 95 | 59 |
| pos square n=300 c=5 snr=1.0 white | 0 | 90 | 92 | 52 |
| pos square n=300 c=5 snr=0.5 white | 0 | 16 | 35 | 8 |
| pos square n=300 c=6 snr=2.0 white | 1 | 100 | 100 | 100 |
| pos square n=300 c=6 snr=1.0 white | 1 | 100 | 100 | 100 |
| pos square n=300 c=6 snr=0.5 white | 0 | 37 | 66 | 35 |
| pos square n=300 c=8 snr=2.0 white | 98 | 100 | 100 | 100 |
| pos square n=300 c=8 snr=1.0 white | 95 | 99 | 99 | 100 |
| pos square n=300 c=8 snr=0.5 white | 38 | 45 | 60 | 50 |
| pos square n=300 c=10 snr=2.0 white | 99 | 100 | 100 | 100 |
| pos square n=300 c=10 snr=1.0 white | 99 | 98 | 98 | 100 |
| pos square n=300 c=10 snr=0.5 white | 62 | 39 | 60 | 47 |
| pos square n=300 c=20 snr=2.0 white | 100 | 98 | 98 | 100 |
| pos square n=300 c=20 snr=1.0 white | 97 | 94 | 94 | 97 |
| pos square n=300 c=20 snr=0.5 white | 41 | 34 | 40 | 36 |
| pos square n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos square n=1000 c=4 snr=2.0 white | 0 | 6 | 6 | 0 |
| pos square n=1000 c=4 snr=1.0 white | 0 | 12 | 12 | 0 |
| pos square n=1000 c=4 snr=0.5 white | 0 | 41 | 44 | 0 |
| pos square n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 83 |
| pos square n=1000 c=5 snr=1.0 white | 0 | 100 | 100 | 84 |
| pos square n=1000 c=5 snr=0.5 white | 0 | 99 | 100 | 79 |
| pos square n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 |
| pos square n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 |
| pos square n=1000 c=6 snr=0.5 white | 0 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos square n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos square n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos square n=1000 c=10 snr=0.5 white | 100 | 98 | 98 | 100 |
| pos square n=1000 c=20 snr=2.0 white | 100 | 98 | 98 | 100 |
| pos square n=1000 c=20 snr=1.0 white | 99 | 98 | 98 | 99 |
| pos square n=1000 c=20 snr=0.5 white | 93 | 92 | 92 | 93 |
| pos square n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos square n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos square n=3000 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos square n=3000 c=4 snr=2.0 white | 0 | 1 | 1 | 0 |
| pos square n=3000 c=4 snr=1.0 white | 0 | 13 | 13 | 0 |
| pos square n=3000 c=4 snr=0.5 white | 0 | 64 | 64 | 0 |
| pos square n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 91 |
| pos square n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 91 |
| pos square n=3000 c=5 snr=0.5 white | 0 | 100 | 100 | 96 |
| pos square n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=0.5 white | 0 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos square n=300 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos square n=300 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos square n=300 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=300 c=4 snr=2.0 ar09 | 0 | 1 | 3 | 0 |
| pos square n=300 c=4 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos square n=300 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=300 c=5 snr=2.0 ar09 | 0 | 35 | 48 | 29 |
| pos square n=300 c=5 snr=1.0 ar09 | 0 | 1 | 2 | 1 |
| pos square n=300 c=5 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=300 c=6 snr=2.0 ar09 | 1 | 83 | 89 | 83 |
| pos square n=300 c=6 snr=1.0 ar09 | 0 | 7 | 12 | 7 |
| pos square n=300 c=6 snr=0.5 ar09 | 0 | 0 | 1 | 0 |
| pos square n=300 c=8 snr=2.0 ar09 | 84 | 96 | 96 | 98 |
| pos square n=300 c=8 snr=1.0 ar09 | 8 | 12 | 24 | 13 |
| pos square n=300 c=8 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=300 c=10 snr=2.0 ar09 | 89 | 95 | 95 | 97 |
| pos square n=300 c=10 snr=1.0 ar09 | 16 | 13 | 22 | 14 |
| pos square n=300 c=10 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=300 c=20 snr=2.0 ar09 | 98 | 95 | 95 | 98 |
| pos square n=300 c=20 snr=1.0 ar09 | 30 | 35 | 37 | 38 |
| pos square n=300 c=20 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=1000 c=4 snr=2.0 ar09 | 0 | 4 | 4 | 0 |
| pos square n=1000 c=4 snr=1.0 ar09 | 0 | 0 | 1 | 0 |
| pos square n=1000 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=1000 c=5 snr=2.0 ar09 | 0 | 93 | 94 | 69 |
| pos square n=1000 c=5 snr=1.0 ar09 | 0 | 17 | 27 | 11 |
| pos square n=1000 c=5 snr=0.5 ar09 | 0 | 1 | 1 | 1 |
| pos square n=1000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 100 |
| pos square n=1000 c=6 snr=1.0 ar09 | 0 | 39 | 54 | 39 |
| pos square n=1000 c=6 snr=0.5 ar09 | 0 | 0 | 4 | 0 |
| pos square n=1000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 ar09 | 59 | 63 | 79 | 65 |
| pos square n=1000 c=8 snr=0.5 ar09 | 5 | 4 | 10 | 4 |
| pos square n=1000 c=10 snr=2.0 ar09 | 100 | 99 | 99 | 100 |
| pos square n=1000 c=10 snr=1.0 ar09 | 68 | 62 | 68 | 68 |
| pos square n=1000 c=10 snr=0.5 ar09 | 2 | 2 | 6 | 3 |
| pos square n=1000 c=20 snr=2.0 ar09 | 98 | 95 | 95 | 98 |
| pos square n=1000 c=20 snr=1.0 ar09 | 68 | 64 | 65 | 70 |
| pos square n=1000 c=20 snr=0.5 ar09 | 0 | 1 | 3 | 1 |
| pos square n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos square n=3000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos square n=3000 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos square n=3000 c=4 snr=2.0 ar09 | 0 | 5 | 5 | 0 |
| pos square n=3000 c=4 snr=1.0 ar09 | 0 | 3 | 5 | 0 |
| pos square n=3000 c=4 snr=0.5 ar09 | 0 | 0 | 1 | 0 |
| pos square n=3000 c=5 snr=2.0 ar09 | 0 | 100 | 100 | 91 |
| pos square n=3000 c=5 snr=1.0 ar09 | 0 | 91 | 97 | 75 |
| pos square n=3000 c=5 snr=0.5 ar09 | 0 | 12 | 23 | 6 |
| pos square n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=1.0 ar09 | 0 | 98 | 100 | 98 |
| pos square n=3000 c=6 snr=0.5 ar09 | 0 | 16 | 32 | 16 |
| pos square n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 ar09 | 100 | 98 | 98 | 100 |
| pos square n=3000 c=8 snr=0.5 ar09 | 31 | 28 | 41 | 32 |
| pos square n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=1.0 ar09 | 100 | 98 | 98 | 100 |
| pos square n=3000 c=10 snr=0.5 ar09 | 45 | 24 | 41 | 27 |
| pos square n=3000 c=20 snr=2.0 ar09 | 100 | 99 | 99 | 100 |
| pos square n=3000 c=20 snr=1.0 ar09 | 99 | 97 | 97 | 99 |
| pos square n=3000 c=20 snr=0.5 ar09 | 27 | 13 | 23 | 14 |
| pos lagged_square n=300 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 white | 0 | 3 | 3 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 white | 0 | 5 | 10 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 white | 0 | 0 | 1 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 white | 0 | 82 | 84 | 55 |
| pos lagged_square n=300 c=5 snr=1.0 white | 0 | 62 | 72 | 40 |
| pos lagged_square n=300 c=5 snr=0.5 white | 0 | 5 | 11 | 2 |
| pos lagged_square n=300 c=6 snr=2.0 white | 1 | 99 | 99 | 99 |
| pos lagged_square n=300 c=6 snr=1.0 white | 1 | 90 | 95 | 90 |
| pos lagged_square n=300 c=6 snr=0.5 white | 0 | 16 | 27 | 16 |
| pos lagged_square n=300 c=8 snr=2.0 white | 98 | 100 | 100 | 100 |
| pos lagged_square n=300 c=8 snr=1.0 white | 91 | 96 | 98 | 98 |
| pos lagged_square n=300 c=8 snr=0.5 white | 15 | 13 | 31 | 13 |
| pos lagged_square n=300 c=10 snr=2.0 white | 99 | 99 | 99 | 100 |
| pos lagged_square n=300 c=10 snr=1.0 white | 94 | 94 | 94 | 97 |
| pos lagged_square n=300 c=10 snr=0.5 white | 30 | 13 | 28 | 15 |
| pos lagged_square n=300 c=20 snr=2.0 white | 100 | 97 | 97 | 100 |
| pos lagged_square n=300 c=20 snr=1.0 white | 85 | 80 | 80 | 86 |
| pos lagged_square n=300 c=20 snr=0.5 white | 14 | 12 | 16 | 13 |
| pos lagged_square n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 white | 0 | 1 | 1 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 white | 0 | 8 | 9 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 white | 0 | 23 | 32 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 79 |
| pos lagged_square n=1000 c=5 snr=1.0 white | 0 | 100 | 100 | 82 |
| pos lagged_square n=1000 c=5 snr=0.5 white | 0 | 83 | 95 | 62 |
| pos lagged_square n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=6 snr=0.5 white | 0 | 90 | 100 | 90 |
| pos lagged_square n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=0.5 white | 98 | 94 | 99 | 95 |
| pos lagged_square n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=0.5 white | 95 | 89 | 90 | 94 |
| pos lagged_square n=1000 c=20 snr=2.0 white | 100 | 98 | 98 | 100 |
| pos lagged_square n=1000 c=20 snr=1.0 white | 99 | 98 | 98 | 99 |
| pos lagged_square n=1000 c=20 snr=0.5 white | 83 | 82 | 83 | 82 |
| pos lagged_square n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 white | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 white | 0 | 1 | 1 | 0 |
| pos lagged_square n=3000 c=4 snr=0.5 white | 0 | 61 | 62 | 0 |
| pos lagged_square n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 92 |
| pos lagged_square n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 96 |
| pos lagged_square n=3000 c=5 snr=0.5 white | 0 | 100 | 100 | 99 |
| pos lagged_square n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=6 snr=0.5 white | 0 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=0.5 white | 100 | 100 | 100 | 100 |
| pos lagged_square n=300 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 ar09 | 0 | 5 | 10 | 5 |
| pos lagged_square n=300 c=5 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=5 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=6 snr=2.0 ar09 | 0 | 34 | 46 | 34 |
| pos lagged_square n=300 c=6 snr=1.0 ar09 | 0 | 2 | 5 | 2 |
| pos lagged_square n=300 c=6 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=8 snr=2.0 ar09 | 48 | 64 | 77 | 69 |
| pos lagged_square n=300 c=8 snr=1.0 ar09 | 4 | 2 | 4 | 2 |
| pos lagged_square n=300 c=8 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=10 snr=2.0 ar09 | 71 | 74 | 79 | 86 |
| pos lagged_square n=300 c=10 snr=1.0 ar09 | 3 | 2 | 4 | 2 |
| pos lagged_square n=300 c=10 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=20 snr=2.0 ar09 | 95 | 93 | 93 | 96 |
| pos lagged_square n=300 c=20 snr=1.0 ar09 | 5 | 2 | 3 | 2 |
| pos lagged_square n=300 c=20 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 ar09 | 0 | 0 | 1 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 ar09 | 0 | 39 | 56 | 32 |
| pos lagged_square n=1000 c=5 snr=1.0 ar09 | 0 | 0 | 4 | 0 |
| pos lagged_square n=1000 c=5 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=6 snr=2.0 ar09 | 0 | 91 | 97 | 91 |
| pos lagged_square n=1000 c=6 snr=1.0 ar09 | 0 | 5 | 17 | 5 |
| pos lagged_square n=1000 c=6 snr=0.5 ar09 | 0 | 0 | 1 | 0 |
| pos lagged_square n=1000 c=8 snr=2.0 ar09 | 94 | 94 | 96 | 98 |
| pos lagged_square n=1000 c=8 snr=1.0 ar09 | 18 | 19 | 34 | 19 |
| pos lagged_square n=1000 c=8 snr=0.5 ar09 | 1 | 1 | 3 | 1 |
| pos lagged_square n=1000 c=10 snr=2.0 ar09 | 94 | 95 | 95 | 96 |
| pos lagged_square n=1000 c=10 snr=1.0 ar09 | 30 | 24 | 36 | 25 |
| pos lagged_square n=1000 c=10 snr=0.5 ar09 | 1 | 1 | 1 | 1 |
| pos lagged_square n=1000 c=20 snr=2.0 ar09 | 98 | 92 | 92 | 98 |
| pos lagged_square n=1000 c=20 snr=1.0 ar09 | 30 | 24 | 32 | 27 |
| pos lagged_square n=1000 c=20 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 ar09 | 0 | 1 | 2 | 0 |
| pos lagged_square n=3000 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=5 snr=2.0 ar09 | 0 | 90 | 96 | 80 |
| pos lagged_square n=3000 c=5 snr=1.0 ar09 | 0 | 43 | 63 | 32 |
| pos lagged_square n=3000 c=5 snr=0.5 ar09 | 0 | 2 | 8 | 0 |
| pos lagged_square n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=6 snr=1.0 ar09 | 0 | 65 | 87 | 65 |
| pos lagged_square n=3000 c=6 snr=0.5 ar09 | 0 | 6 | 14 | 6 |
| pos lagged_square n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 ar09 | 83 | 84 | 92 | 89 |
| pos lagged_square n=3000 c=8 snr=0.5 ar09 | 6 | 7 | 17 | 8 |
| pos lagged_square n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 ar09 | 96 | 85 | 87 | 92 |
| pos lagged_square n=3000 c=10 snr=0.5 ar09 | 18 | 7 | 13 | 8 |
| pos lagged_square n=3000 c=20 snr=2.0 ar09 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=1.0 ar09 | 92 | 91 | 91 | 92 |
| pos lagged_square n=3000 c=20 snr=0.5 ar09 | 12 | 4 | 6 | 5 |
