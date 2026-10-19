# exp21 dev report (synthetic short records)

Seeds: dev 2000..2099

## Summary

| candidate | F pass | worst negative cell | pooled neg | S pool | L share | c3-4 share | snr0.5 share | chosen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | no | neg white n=3000 (9.0%) | 1.1% | 50.6% | 86.2% | 0.0% | 17.7% |  |
| F | no | neg ar090 n=3000 (21.0%) | 4.9% | 87.7% | 83.2% | 41.1% | 48.3% |  |
| G | yes | neg ar090 n=3000 (2.0%) | 0.3% | 83.0% | 81.6% | 35.5% | 36.3% | yes |
| H | yes | neg white n=300 (1.0%) | 0.0% | 64.8% | 78.8% | 3.6% | 21.5% |  |
| I | yes | neg white n=1000 (2.0%) | 0.2% | 79.2% | 84.7% | 1.6% | 28.7% |  |

Winner: **G**

## Reason counts (positives)

- A: too few ACF zero crossings: 26003, regular: 11338, irregular: 459
- F: too few ACF zero crossings: 10654, regular: 24830, irregular: 2316
- G: too few ACF zero crossings: 10654, regular: 22069, weak ACF peak: 2761, irregular: 2316
- H: too few ACF zero crossings: 10654, weak ACF peak: 10193, irregular: 2316, regular: 14637
- I: too few ACF zero crossings: 17236, regular: 17992, weak ACF peak: 1447, irregular: 1125

## Reason counts (negatives)

- A: too few ACF zero crossings: 1862, irregular: 215, regular: 23
- F: regular: 102, irregular: 465, too few ACF zero crossings: 1533
- G: weak ACF peak: 95, irregular: 465, too few ACF zero crossings: 1533, regular: 7
- H: weak ACF peak: 101, irregular: 465, too few ACF zero crossings: 1533, regular: 1
- I: too few ACF zero crossings: 1779, irregular: 272, weak ACF peak: 45, regular: 4

## Per-cell detection share, negatives (percent)

| cell | A | F | G | H | I |
| --- | --- | --- | --- | --- | --- |
| neg white n=300 | 0 | 14 | 1 | 1 | 0 |
| neg white n=1000 | 4 | 8 | 1 | 0 | 2 |
| neg white n=3000 | 9 | 10 | 1 | 0 | 1 |
| neg ar050 n=300 | 0 | 10 | 0 | 0 | 0 |
| neg ar050 n=1000 | 2 | 15 | 1 | 0 | 0 |
| neg ar050 n=3000 | 8 | 9 | 1 | 0 | 1 |
| neg ar090 n=300 | 0 | 1 | 0 | 0 | 0 |
| neg ar090 n=1000 | 0 | 4 | 0 | 0 | 0 |
| neg ar090 n=3000 | 0 | 21 | 2 | 0 | 0 |
| neg ar097 n=300 | 0 | 0 | 0 | 0 | 0 |
| neg ar097 n=1000 | 0 | 1 | 0 | 0 | 0 |
| neg ar097 n=3000 | 0 | 7 | 0 | 0 | 0 |
| neg ar099 n=300 | 0 | 0 | 0 | 0 | 0 |
| neg ar099 n=1000 | 0 | 0 | 0 | 0 | 0 |
| neg ar099 n=3000 | 0 | 1 | 0 | 0 | 0 |
| neg random_walk n=300 | 0 | 0 | 0 | 0 | 0 |
| neg random_walk n=1000 | 0 | 0 | 0 | 0 | 0 |
| neg random_walk n=3000 | 0 | 0 | 0 | 0 | 0 |
| neg sp_steps n=300 | 0 | 1 | 0 | 0 | 0 |
| neg sp_steps n=1000 | 0 | 0 | 0 | 0 | 0 |
| neg sp_steps n=3000 | 0 | 0 | 0 | 0 | 0 |

## Per-cell detection share, positives (percent)

| cell | A | F | G | H | I |
| --- | --- | --- | --- | --- | --- |
| pos sine n=300 c=3 snr=2.0 white | 0 | 2 | 2 | 0 | 0 |
| pos sine n=300 c=3 snr=1.0 white | 0 | 5 | 4 | 0 | 0 |
| pos sine n=300 c=3 snr=0.5 white | 0 | 11 | 2 | 0 | 0 |
| pos sine n=300 c=4 snr=2.0 white | 0 | 93 | 88 | 0 | 3 |
| pos sine n=300 c=4 snr=1.0 white | 0 | 95 | 79 | 1 | 7 |
| pos sine n=300 c=4 snr=0.5 white | 0 | 73 | 29 | 0 | 0 |
| pos sine n=300 c=5 snr=2.0 white | 0 | 100 | 100 | 19 | 89 |
| pos sine n=300 c=5 snr=1.0 white | 0 | 100 | 92 | 16 | 67 |
| pos sine n=300 c=5 snr=0.5 white | 0 | 79 | 30 | 3 | 8 |
| pos sine n=300 c=6 snr=2.0 white | 2 | 100 | 100 | 88 | 100 |
| pos sine n=300 c=6 snr=1.0 white | 1 | 99 | 99 | 34 | 93 |
| pos sine n=300 c=6 snr=0.5 white | 0 | 80 | 28 | 1 | 11 |
| pos sine n=300 c=8 snr=2.0 white | 99 | 100 | 100 | 100 | 100 |
| pos sine n=300 c=8 snr=1.0 white | 91 | 100 | 100 | 72 | 97 |
| pos sine n=300 c=8 snr=0.5 white | 24 | 64 | 25 | 5 | 14 |
| pos sine n=300 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=300 c=10 snr=1.0 white | 93 | 97 | 97 | 84 | 92 |
| pos sine n=300 c=10 snr=0.5 white | 27 | 48 | 19 | 1 | 16 |
| pos sine n=300 c=20 snr=2.0 white | 99 | 91 | 91 | 91 | 95 |
| pos sine n=300 c=20 snr=1.0 white | 88 | 79 | 79 | 76 | 85 |
| pos sine n=300 c=20 snr=0.5 white | 14 | 20 | 5 | 0 | 4 |
| pos sine n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 | 0 |
| pos sine n=1000 c=3 snr=1.0 white | 0 | 1 | 1 | 0 | 0 |
| pos sine n=1000 c=3 snr=0.5 white | 0 | 10 | 7 | 0 | 0 |
| pos sine n=1000 c=4 snr=2.0 white | 0 | 100 | 100 | 0 | 0 |
| pos sine n=1000 c=4 snr=1.0 white | 0 | 100 | 100 | 5 | 9 |
| pos sine n=1000 c=4 snr=0.5 white | 0 | 100 | 94 | 10 | 27 |
| pos sine n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 42 | 99 |
| pos sine n=1000 c=5 snr=1.0 white | 0 | 100 | 100 | 63 | 100 |
| pos sine n=1000 c=5 snr=0.5 white | 0 | 98 | 96 | 22 | 84 |
| pos sine n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 96 | 100 |
| pos sine n=1000 c=6 snr=0.5 white | 0 | 96 | 94 | 35 | 88 |
| pos sine n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=8 snr=0.5 white | 98 | 95 | 93 | 50 | 91 |
| pos sine n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=1000 c=10 snr=0.5 white | 98 | 99 | 99 | 56 | 92 |
| pos sine n=1000 c=20 snr=2.0 white | 100 | 97 | 97 | 97 | 100 |
| pos sine n=1000 c=20 snr=1.0 white | 100 | 97 | 97 | 97 | 100 |
| pos sine n=1000 c=20 snr=0.5 white | 87 | 92 | 90 | 57 | 80 |
| pos sine n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=3 snr=0.5 white | 0 | 1 | 1 | 0 | 0 |
| pos sine n=3000 c=4 snr=2.0 white | 0 | 100 | 100 | 0 | 0 |
| pos sine n=3000 c=4 snr=1.0 white | 0 | 100 | 100 | 0 | 0 |
| pos sine n=3000 c=4 snr=0.5 white | 0 | 100 | 100 | 43 | 57 |
| pos sine n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 51 | 100 |
| pos sine n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 92 | 100 |
| pos sine n=3000 c=5 snr=0.5 white | 0 | 100 | 100 | 93 | 100 |
| pos sine n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=6 snr=0.5 white | 0 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=8 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos sine n=300 c=3 snr=2.0 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos sine n=300 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=4 snr=2.0 ar09 | 0 | 33 | 4 | 0 | 0 |
| pos sine n=300 c=4 snr=1.0 ar09 | 0 | 4 | 0 | 0 | 0 |
| pos sine n=300 c=4 snr=0.5 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos sine n=300 c=5 snr=2.0 ar09 | 0 | 80 | 37 | 0 | 7 |
| pos sine n=300 c=5 snr=1.0 ar09 | 0 | 16 | 4 | 0 | 0 |
| pos sine n=300 c=5 snr=0.5 ar09 | 0 | 1 | 1 | 0 | 0 |
| pos sine n=300 c=6 snr=2.0 ar09 | 0 | 93 | 55 | 0 | 25 |
| pos sine n=300 c=6 snr=1.0 ar09 | 0 | 12 | 0 | 0 | 0 |
| pos sine n=300 c=6 snr=0.5 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos sine n=300 c=8 snr=2.0 ar09 | 58 | 86 | 78 | 18 | 74 |
| pos sine n=300 c=8 snr=1.0 ar09 | 1 | 13 | 4 | 0 | 2 |
| pos sine n=300 c=8 snr=0.5 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos sine n=300 c=10 snr=2.0 ar09 | 80 | 83 | 81 | 37 | 83 |
| pos sine n=300 c=10 snr=1.0 ar09 | 5 | 17 | 4 | 0 | 1 |
| pos sine n=300 c=10 snr=0.5 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos sine n=300 c=20 snr=2.0 ar09 | 89 | 71 | 71 | 71 | 86 |
| pos sine n=300 c=20 snr=1.0 ar09 | 2 | 13 | 4 | 0 | 1 |
| pos sine n=300 c=20 snr=0.5 ar09 | 0 | 2 | 1 | 0 | 0 |
| pos sine n=1000 c=3 snr=2.0 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos sine n=1000 c=3 snr=1.0 ar09 | 0 | 3 | 0 | 0 | 0 |
| pos sine n=1000 c=3 snr=0.5 ar09 | 0 | 2 | 0 | 0 | 0 |
| pos sine n=1000 c=4 snr=2.0 ar09 | 0 | 82 | 48 | 0 | 0 |
| pos sine n=1000 c=4 snr=1.0 ar09 | 0 | 44 | 9 | 0 | 0 |
| pos sine n=1000 c=4 snr=0.5 ar09 | 0 | 14 | 1 | 0 | 0 |
| pos sine n=1000 c=5 snr=2.0 ar09 | 0 | 100 | 92 | 1 | 35 |
| pos sine n=1000 c=5 snr=1.0 ar09 | 0 | 54 | 14 | 1 | 0 |
| pos sine n=1000 c=5 snr=0.5 ar09 | 0 | 7 | 0 | 0 | 0 |
| pos sine n=1000 c=6 snr=2.0 ar09 | 0 | 100 | 95 | 10 | 80 |
| pos sine n=1000 c=6 snr=1.0 ar09 | 0 | 52 | 14 | 0 | 3 |
| pos sine n=1000 c=6 snr=0.5 ar09 | 0 | 5 | 1 | 0 | 0 |
| pos sine n=1000 c=8 snr=2.0 ar09 | 93 | 99 | 99 | 71 | 95 |
| pos sine n=1000 c=8 snr=1.0 ar09 | 18 | 60 | 33 | 2 | 20 |
| pos sine n=1000 c=8 snr=0.5 ar09 | 0 | 7 | 0 | 0 | 0 |
| pos sine n=1000 c=10 snr=2.0 ar09 | 95 | 99 | 99 | 92 | 95 |
| pos sine n=1000 c=10 snr=1.0 ar09 | 24 | 44 | 23 | 3 | 12 |
| pos sine n=1000 c=10 snr=0.5 ar09 | 1 | 10 | 2 | 1 | 1 |
| pos sine n=1000 c=20 snr=2.0 ar09 | 96 | 91 | 91 | 91 | 91 |
| pos sine n=1000 c=20 snr=1.0 ar09 | 35 | 41 | 29 | 8 | 27 |
| pos sine n=1000 c=20 snr=0.5 ar09 | 0 | 6 | 2 | 0 | 0 |
| pos sine n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos sine n=3000 c=3 snr=0.5 ar09 | 0 | 6 | 2 | 0 | 0 |
| pos sine n=3000 c=4 snr=2.0 ar09 | 0 | 100 | 97 | 0 | 0 |
| pos sine n=3000 c=4 snr=1.0 ar09 | 0 | 92 | 63 | 1 | 0 |
| pos sine n=3000 c=4 snr=0.5 ar09 | 0 | 60 | 18 | 1 | 0 |
| pos sine n=3000 c=5 snr=2.0 ar09 | 0 | 100 | 100 | 7 | 95 |
| pos sine n=3000 c=5 snr=1.0 ar09 | 0 | 98 | 77 | 6 | 43 |
| pos sine n=3000 c=5 snr=0.5 ar09 | 0 | 64 | 20 | 1 | 3 |
| pos sine n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 87 | 100 |
| pos sine n=3000 c=6 snr=1.0 ar09 | 0 | 100 | 91 | 20 | 80 |
| pos sine n=3000 c=6 snr=0.5 ar09 | 0 | 60 | 16 | 3 | 6 |
| pos sine n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 99 | 100 |
| pos sine n=3000 c=8 snr=1.0 ar09 | 86 | 96 | 88 | 38 | 83 |
| pos sine n=3000 c=8 snr=0.5 ar09 | 9 | 47 | 13 | 1 | 6 |
| pos sine n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=10 snr=1.0 ar09 | 94 | 96 | 92 | 52 | 88 |
| pos sine n=3000 c=10 snr=0.5 ar09 | 15 | 39 | 11 | 1 | 7 |
| pos sine n=3000 c=20 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos sine n=3000 c=20 snr=1.0 ar09 | 95 | 99 | 94 | 73 | 89 |
| pos sine n=3000 c=20 snr=0.5 ar09 | 10 | 31 | 9 | 1 | 4 |
| pos square n=300 c=3 snr=2.0 white | 0 | 5 | 5 | 0 | 0 |
| pos square n=300 c=3 snr=1.0 white | 0 | 5 | 5 | 0 | 0 |
| pos square n=300 c=3 snr=0.5 white | 0 | 6 | 4 | 0 | 0 |
| pos square n=300 c=4 snr=2.0 white | 0 | 98 | 98 | 12 | 13 |
| pos square n=300 c=4 snr=1.0 white | 0 | 95 | 93 | 12 | 13 |
| pos square n=300 c=4 snr=0.5 white | 0 | 91 | 51 | 1 | 5 |
| pos square n=300 c=5 snr=2.0 white | 0 | 100 | 100 | 81 | 94 |
| pos square n=300 c=5 snr=1.0 white | 0 | 100 | 100 | 49 | 91 |
| pos square n=300 c=5 snr=0.5 white | 0 | 97 | 61 | 7 | 15 |
| pos square n=300 c=6 snr=2.0 white | 1 | 100 | 100 | 100 | 100 |
| pos square n=300 c=6 snr=1.0 white | 1 | 100 | 100 | 84 | 99 |
| pos square n=300 c=6 snr=0.5 white | 1 | 96 | 59 | 7 | 37 |
| pos square n=300 c=8 snr=2.0 white | 99 | 100 | 100 | 100 | 100 |
| pos square n=300 c=8 snr=1.0 white | 94 | 100 | 100 | 99 | 98 |
| pos square n=300 c=8 snr=0.5 white | 50 | 85 | 67 | 12 | 47 |
| pos square n=300 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=300 c=10 snr=1.0 white | 97 | 99 | 99 | 98 | 98 |
| pos square n=300 c=10 snr=0.5 white | 56 | 79 | 49 | 11 | 41 |
| pos square n=300 c=20 snr=2.0 white | 99 | 90 | 90 | 90 | 95 |
| pos square n=300 c=20 snr=1.0 white | 96 | 82 | 82 | 82 | 91 |
| pos square n=300 c=20 snr=0.5 white | 39 | 38 | 31 | 10 | 35 |
| pos square n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=0.5 white | 0 | 4 | 4 | 0 | 0 |
| pos square n=1000 c=4 snr=2.0 white | 0 | 100 | 100 | 22 | 4 |
| pos square n=1000 c=4 snr=1.0 white | 0 | 100 | 100 | 42 | 26 |
| pos square n=1000 c=4 snr=0.5 white | 0 | 100 | 100 | 33 | 49 |
| pos square n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 98 | 100 |
| pos square n=1000 c=5 snr=1.0 white | 0 | 100 | 100 | 98 | 100 |
| pos square n=1000 c=5 snr=0.5 white | 0 | 100 | 100 | 69 | 97 |
| pos square n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=6 snr=0.5 white | 0 | 100 | 100 | 80 | 100 |
| pos square n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=0.5 white | 100 | 100 | 100 | 95 | 100 |
| pos square n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=10 snr=0.5 white | 100 | 100 | 100 | 97 | 98 |
| pos square n=1000 c=20 snr=2.0 white | 100 | 97 | 97 | 97 | 99 |
| pos square n=1000 c=20 snr=1.0 white | 99 | 97 | 97 | 97 | 98 |
| pos square n=1000 c=20 snr=0.5 white | 95 | 95 | 95 | 94 | 94 |
| pos square n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 | 0 |
| pos square n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 | 0 |
| pos square n=3000 c=3 snr=0.5 white | 0 | 0 | 0 | 0 | 0 |
| pos square n=3000 c=4 snr=2.0 white | 0 | 100 | 100 | 53 | 1 |
| pos square n=3000 c=4 snr=1.0 white | 0 | 100 | 100 | 69 | 8 |
| pos square n=3000 c=4 snr=0.5 white | 0 | 100 | 100 | 90 | 70 |
| pos square n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=5 snr=0.5 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=0.5 white | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos square n=300 c=3 snr=2.0 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos square n=300 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos square n=300 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos square n=300 c=4 snr=2.0 ar09 | 0 | 77 | 45 | 1 | 0 |
| pos square n=300 c=4 snr=1.0 ar09 | 0 | 10 | 2 | 0 | 0 |
| pos square n=300 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos square n=300 c=5 snr=2.0 ar09 | 0 | 96 | 87 | 13 | 41 |
| pos square n=300 c=5 snr=1.0 ar09 | 0 | 30 | 9 | 0 | 1 |
| pos square n=300 c=5 snr=0.5 ar09 | 0 | 4 | 1 | 0 | 0 |
| pos square n=300 c=6 snr=2.0 ar09 | 1 | 100 | 99 | 30 | 87 |
| pos square n=300 c=6 snr=1.0 ar09 | 0 | 30 | 9 | 0 | 4 |
| pos square n=300 c=6 snr=0.5 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos square n=300 c=8 snr=2.0 ar09 | 85 | 99 | 99 | 84 | 98 |
| pos square n=300 c=8 snr=1.0 ar09 | 9 | 42 | 17 | 1 | 13 |
| pos square n=300 c=8 snr=0.5 ar09 | 0 | 3 | 0 | 0 | 0 |
| pos square n=300 c=10 snr=2.0 ar09 | 95 | 96 | 96 | 95 | 91 |
| pos square n=300 c=10 snr=1.0 ar09 | 16 | 22 | 14 | 1 | 18 |
| pos square n=300 c=10 snr=0.5 ar09 | 0 | 1 | 1 | 0 | 0 |
| pos square n=300 c=20 snr=2.0 ar09 | 97 | 80 | 80 | 80 | 94 |
| pos square n=300 c=20 snr=1.0 ar09 | 27 | 29 | 25 | 18 | 41 |
| pos square n=300 c=20 snr=0.5 ar09 | 0 | 7 | 1 | 0 | 0 |
| pos square n=1000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=1.0 ar09 | 0 | 2 | 0 | 0 | 0 |
| pos square n=1000 c=3 snr=0.5 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos square n=1000 c=4 snr=2.0 ar09 | 0 | 97 | 95 | 4 | 2 |
| pos square n=1000 c=4 snr=1.0 ar09 | 0 | 65 | 33 | 0 | 1 |
| pos square n=1000 c=4 snr=0.5 ar09 | 0 | 18 | 2 | 0 | 0 |
| pos square n=1000 c=5 snr=2.0 ar09 | 0 | 100 | 100 | 48 | 93 |
| pos square n=1000 c=5 snr=1.0 ar09 | 0 | 87 | 51 | 1 | 12 |
| pos square n=1000 c=5 snr=0.5 ar09 | 0 | 19 | 3 | 0 | 0 |
| pos square n=1000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 77 | 100 |
| pos square n=1000 c=6 snr=1.0 ar09 | 0 | 83 | 55 | 7 | 32 |
| pos square n=1000 c=6 snr=0.5 ar09 | 0 | 13 | 2 | 0 | 0 |
| pos square n=1000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=1000 c=8 snr=1.0 ar09 | 49 | 79 | 68 | 20 | 59 |
| pos square n=1000 c=8 snr=0.5 ar09 | 1 | 20 | 3 | 0 | 0 |
| pos square n=1000 c=10 snr=2.0 ar09 | 99 | 100 | 100 | 100 | 99 |
| pos square n=1000 c=10 snr=1.0 ar09 | 68 | 75 | 71 | 24 | 65 |
| pos square n=1000 c=10 snr=0.5 ar09 | 2 | 17 | 3 | 2 | 1 |
| pos square n=1000 c=20 snr=2.0 ar09 | 99 | 94 | 94 | 94 | 97 |
| pos square n=1000 c=20 snr=1.0 ar09 | 79 | 70 | 68 | 59 | 75 |
| pos square n=1000 c=20 snr=0.5 ar09 | 2 | 18 | 5 | 0 | 3 |
| pos square n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos square n=3000 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos square n=3000 c=3 snr=0.5 ar09 | 0 | 7 | 3 | 0 | 0 |
| pos square n=3000 c=4 snr=2.0 ar09 | 0 | 100 | 100 | 23 | 3 |
| pos square n=3000 c=4 snr=1.0 ar09 | 0 | 99 | 93 | 7 | 3 |
| pos square n=3000 c=4 snr=0.5 ar09 | 0 | 74 | 35 | 2 | 1 |
| pos square n=3000 c=5 snr=2.0 ar09 | 0 | 100 | 100 | 93 | 100 |
| pos square n=3000 c=5 snr=1.0 ar09 | 0 | 100 | 96 | 34 | 87 |
| pos square n=3000 c=5 snr=0.5 ar09 | 0 | 82 | 29 | 2 | 10 |
| pos square n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=6 snr=1.0 ar09 | 0 | 100 | 100 | 65 | 100 |
| pos square n=3000 c=6 snr=0.5 ar09 | 0 | 83 | 51 | 6 | 27 |
| pos square n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=8 snr=1.0 ar09 | 100 | 100 | 100 | 89 | 98 |
| pos square n=3000 c=8 snr=0.5 ar09 | 36 | 64 | 41 | 5 | 29 |
| pos square n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=10 snr=1.0 ar09 | 100 | 100 | 100 | 98 | 100 |
| pos square n=3000 c=10 snr=0.5 ar09 | 49 | 63 | 40 | 5 | 27 |
| pos square n=3000 c=20 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=1.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos square n=3000 c=20 snr=0.5 ar09 | 30 | 36 | 26 | 7 | 21 |
| pos lagged_square n=300 c=3 snr=2.0 white | 0 | 5 | 3 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 white | 0 | 6 | 4 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 white | 0 | 6 | 2 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 white | 0 | 97 | 89 | 1 | 3 |
| pos lagged_square n=300 c=4 snr=1.0 white | 0 | 96 | 80 | 0 | 6 |
| pos lagged_square n=300 c=4 snr=0.5 white | 0 | 77 | 31 | 1 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 white | 0 | 100 | 100 | 21 | 90 |
| pos lagged_square n=300 c=5 snr=1.0 white | 0 | 100 | 94 | 14 | 62 |
| pos lagged_square n=300 c=5 snr=0.5 white | 0 | 79 | 29 | 2 | 6 |
| pos lagged_square n=300 c=6 snr=2.0 white | 1 | 100 | 100 | 84 | 99 |
| pos lagged_square n=300 c=6 snr=1.0 white | 1 | 100 | 98 | 30 | 93 |
| pos lagged_square n=300 c=6 snr=0.5 white | 0 | 78 | 23 | 1 | 12 |
| pos lagged_square n=300 c=8 snr=2.0 white | 99 | 100 | 100 | 100 | 100 |
| pos lagged_square n=300 c=8 snr=1.0 white | 88 | 100 | 97 | 74 | 93 |
| pos lagged_square n=300 c=8 snr=0.5 white | 16 | 59 | 24 | 2 | 12 |
| pos lagged_square n=300 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=300 c=10 snr=1.0 white | 98 | 99 | 99 | 86 | 93 |
| pos lagged_square n=300 c=10 snr=0.5 white | 25 | 46 | 24 | 1 | 12 |
| pos lagged_square n=300 c=20 snr=2.0 white | 99 | 91 | 91 | 91 | 97 |
| pos lagged_square n=300 c=20 snr=1.0 white | 90 | 78 | 78 | 77 | 88 |
| pos lagged_square n=300 c=20 snr=0.5 white | 13 | 22 | 4 | 1 | 6 |
| pos lagged_square n=1000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 white | 0 | 10 | 7 | 1 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 white | 0 | 100 | 97 | 0 | 1 |
| pos lagged_square n=1000 c=4 snr=1.0 white | 0 | 100 | 97 | 5 | 8 |
| pos lagged_square n=1000 c=4 snr=0.5 white | 0 | 100 | 92 | 12 | 30 |
| pos lagged_square n=1000 c=5 snr=2.0 white | 0 | 100 | 100 | 59 | 100 |
| pos lagged_square n=1000 c=5 snr=1.0 white | 0 | 100 | 100 | 70 | 100 |
| pos lagged_square n=1000 c=5 snr=0.5 white | 0 | 99 | 99 | 25 | 85 |
| pos lagged_square n=1000 c=6 snr=2.0 white | 0 | 100 | 100 | 99 | 100 |
| pos lagged_square n=1000 c=6 snr=1.0 white | 0 | 100 | 100 | 97 | 100 |
| pos lagged_square n=1000 c=6 snr=0.5 white | 0 | 95 | 93 | 33 | 91 |
| pos lagged_square n=1000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=8 snr=0.5 white | 98 | 98 | 96 | 56 | 95 |
| pos lagged_square n=1000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=1000 c=10 snr=0.5 white | 99 | 100 | 98 | 57 | 92 |
| pos lagged_square n=1000 c=20 snr=2.0 white | 100 | 98 | 98 | 98 | 99 |
| pos lagged_square n=1000 c=20 snr=1.0 white | 100 | 98 | 98 | 98 | 99 |
| pos lagged_square n=1000 c=20 snr=0.5 white | 88 | 93 | 88 | 56 | 81 |
| pos lagged_square n=3000 c=3 snr=2.0 white | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 white | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 white | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 white | 0 | 100 | 100 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 white | 0 | 100 | 100 | 0 | 1 |
| pos lagged_square n=3000 c=4 snr=0.5 white | 0 | 100 | 100 | 44 | 57 |
| pos lagged_square n=3000 c=5 snr=2.0 white | 0 | 100 | 100 | 64 | 100 |
| pos lagged_square n=3000 c=5 snr=1.0 white | 0 | 100 | 100 | 85 | 100 |
| pos lagged_square n=3000 c=5 snr=0.5 white | 0 | 100 | 100 | 92 | 100 |
| pos lagged_square n=3000 c=6 snr=2.0 white | 0 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=6 snr=1.0 white | 0 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=6 snr=0.5 white | 0 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=8 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=2.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=1.0 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=0.5 white | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=300 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=1.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=3 snr=0.5 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=2.0 ar09 | 0 | 33 | 7 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=1.0 ar09 | 0 | 6 | 0 | 0 | 0 |
| pos lagged_square n=300 c=4 snr=0.5 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=5 snr=2.0 ar09 | 0 | 72 | 31 | 1 | 7 |
| pos lagged_square n=300 c=5 snr=1.0 ar09 | 0 | 12 | 3 | 0 | 1 |
| pos lagged_square n=300 c=5 snr=0.5 ar09 | 0 | 2 | 1 | 0 | 0 |
| pos lagged_square n=300 c=6 snr=2.0 ar09 | 0 | 83 | 51 | 0 | 32 |
| pos lagged_square n=300 c=6 snr=1.0 ar09 | 0 | 14 | 1 | 0 | 0 |
| pos lagged_square n=300 c=6 snr=0.5 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=300 c=8 snr=2.0 ar09 | 56 | 88 | 80 | 15 | 72 |
| pos lagged_square n=300 c=8 snr=1.0 ar09 | 1 | 9 | 6 | 0 | 1 |
| pos lagged_square n=300 c=8 snr=0.5 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos lagged_square n=300 c=10 snr=2.0 ar09 | 79 | 79 | 79 | 40 | 88 |
| pos lagged_square n=300 c=10 snr=1.0 ar09 | 6 | 12 | 4 | 0 | 5 |
| pos lagged_square n=300 c=10 snr=0.5 ar09 | 0 | 2 | 0 | 0 | 0 |
| pos lagged_square n=300 c=20 snr=2.0 ar09 | 88 | 72 | 72 | 72 | 83 |
| pos lagged_square n=300 c=20 snr=1.0 ar09 | 3 | 13 | 4 | 0 | 5 |
| pos lagged_square n=300 c=20 snr=0.5 ar09 | 0 | 2 | 1 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=1.0 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=3 snr=0.5 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=2.0 ar09 | 0 | 82 | 51 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=1.0 ar09 | 0 | 37 | 11 | 0 | 0 |
| pos lagged_square n=1000 c=4 snr=0.5 ar09 | 0 | 10 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=5 snr=2.0 ar09 | 0 | 100 | 89 | 2 | 43 |
| pos lagged_square n=1000 c=5 snr=1.0 ar09 | 0 | 55 | 9 | 1 | 1 |
| pos lagged_square n=1000 c=5 snr=0.5 ar09 | 0 | 8 | 0 | 0 | 0 |
| pos lagged_square n=1000 c=6 snr=2.0 ar09 | 0 | 100 | 96 | 15 | 81 |
| pos lagged_square n=1000 c=6 snr=1.0 ar09 | 0 | 54 | 17 | 0 | 2 |
| pos lagged_square n=1000 c=6 snr=0.5 ar09 | 0 | 8 | 2 | 0 | 0 |
| pos lagged_square n=1000 c=8 snr=2.0 ar09 | 94 | 99 | 99 | 71 | 99 |
| pos lagged_square n=1000 c=8 snr=1.0 ar09 | 20 | 51 | 32 | 2 | 14 |
| pos lagged_square n=1000 c=8 snr=0.5 ar09 | 0 | 5 | 1 | 0 | 0 |
| pos lagged_square n=1000 c=10 snr=2.0 ar09 | 97 | 100 | 100 | 95 | 98 |
| pos lagged_square n=1000 c=10 snr=1.0 ar09 | 29 | 45 | 23 | 3 | 15 |
| pos lagged_square n=1000 c=10 snr=0.5 ar09 | 1 | 9 | 2 | 1 | 1 |
| pos lagged_square n=1000 c=20 snr=2.0 ar09 | 95 | 90 | 90 | 90 | 94 |
| pos lagged_square n=1000 c=20 snr=1.0 ar09 | 36 | 42 | 32 | 11 | 35 |
| pos lagged_square n=1000 c=20 snr=0.5 ar09 | 0 | 4 | 1 | 0 | 1 |
| pos lagged_square n=3000 c=3 snr=2.0 ar09 | 0 | 0 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=1.0 ar09 | 0 | 1 | 0 | 0 | 0 |
| pos lagged_square n=3000 c=3 snr=0.5 ar09 | 0 | 5 | 1 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=2.0 ar09 | 0 | 99 | 93 | 0 | 0 |
| pos lagged_square n=3000 c=4 snr=1.0 ar09 | 0 | 88 | 58 | 0 | 1 |
| pos lagged_square n=3000 c=4 snr=0.5 ar09 | 0 | 60 | 9 | 1 | 0 |
| pos lagged_square n=3000 c=5 snr=2.0 ar09 | 0 | 100 | 99 | 17 | 96 |
| pos lagged_square n=3000 c=5 snr=1.0 ar09 | 0 | 96 | 77 | 2 | 47 |
| pos lagged_square n=3000 c=5 snr=0.5 ar09 | 0 | 66 | 16 | 1 | 3 |
| pos lagged_square n=3000 c=6 snr=2.0 ar09 | 0 | 100 | 100 | 83 | 100 |
| pos lagged_square n=3000 c=6 snr=1.0 ar09 | 0 | 99 | 92 | 23 | 75 |
| pos lagged_square n=3000 c=6 snr=0.5 ar09 | 0 | 58 | 19 | 2 | 6 |
| pos lagged_square n=3000 c=8 snr=2.0 ar09 | 100 | 100 | 100 | 99 | 100 |
| pos lagged_square n=3000 c=8 snr=1.0 ar09 | 90 | 95 | 90 | 42 | 83 |
| pos lagged_square n=3000 c=8 snr=0.5 ar09 | 10 | 54 | 18 | 1 | 10 |
| pos lagged_square n=3000 c=10 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=10 snr=1.0 ar09 | 94 | 98 | 95 | 48 | 87 |
| pos lagged_square n=3000 c=10 snr=0.5 ar09 | 21 | 39 | 11 | 1 | 7 |
| pos lagged_square n=3000 c=20 snr=2.0 ar09 | 100 | 100 | 100 | 100 | 100 |
| pos lagged_square n=3000 c=20 snr=1.0 ar09 | 91 | 95 | 90 | 79 | 85 |
| pos lagged_square n=3000 c=20 snr=0.5 ar09 | 14 | 34 | 9 | 1 | 4 |
