# exp24 results: I vs A (single confirmation run)

- F: PASS
- S: PASS
- L: MISS
- no_cell_worse: PASS
- pooled_neg_I: 0.2 %
- S_I: 78.9 %
- L_I: 83.0 %
- pooled_neg_A: 1.1 %
- S_A: 50.2 %
- L_A: 85.0 %

**Ship I: no**

## Negative cells (gate the decision)

| cell | I | A |
| --- | --- | --- |
| neg white n=300 | 1/400 | 1/400 |
| neg white n=1000 | 4/400 | 24/400 |
| neg white n=3000 | 2/400 | 29/400 |
| neg ar050 n=300 | 0/400 | 0/400 |
| neg ar050 n=1000 | 2/400 | 2/400 |
| neg ar050 n=3000 | 5/400 | 36/400 |
| neg ar090 n=300 | 0/400 | 0/400 |
| neg ar090 n=1000 | 0/400 | 0/400 |
| neg ar090 n=3000 | 2/400 | 3/400 |
| neg ar097 n=300 | 0/400 | 0/400 |
| neg ar097 n=1000 | 0/400 | 0/400 |
| neg ar097 n=3000 | 1/400 | 1/400 |
| neg ar099 n=300 | 0/400 | 0/400 |
| neg ar099 n=1000 | 0/400 | 0/400 |
| neg ar099 n=3000 | 0/400 | 0/400 |
| neg random_walk n=300 | 0/400 | 0/400 |
| neg random_walk n=1000 | 0/400 | 0/400 |
| neg random_walk n=3000 | 0/400 | 0/400 |
| neg sp_steps n=300 | 0/400 | 0/400 |
| neg sp_steps n=1000 | 0/400 | 0/400 |
| neg sp_steps n=3000 | 0/400 | 0/400 |

## Report only: AR(2) resonance and drift

| cell | I | A |
| --- | --- | --- |
| ar2 r=0.9 n=300 | 4/400 | 4/400 |
| ar2 r=0.97 n=300 | 129/400 | 120/400 |
| drift n=300 | 1/400 | 0/400 |
| ar2 r=0.9 n=1000 | 3/400 | 8/400 |
| ar2 r=0.97 n=1000 | 125/400 | 127/400 |
| drift n=1000 | 0/400 | 1/400 |
| ar2 r=0.9 n=3000 | 5/400 | 21/400 |
| ar2 r=0.97 n=3000 | 167/400 | 167/400 |
| drift n=3000 | 0/400 | 0/400 |

## Report only: n=300, c=20 (period 15), SNR >= 1

| cell | I | A |
| --- | --- | --- |
| pos sine n=300 c=20 snr=2.0 white | 97/100 | 99/100 |
| pos sine n=300 c=20 snr=1.0 white | 84/100 | 87/100 |
| pos sine n=300 c=20 snr=2.0 ar09 | 85/100 | 88/100 |
| pos sine n=300 c=20 snr=1.0 ar09 | 4/100 | 3/100 |
| pos square n=300 c=20 snr=2.0 white | 99/100 | 99/100 |
| pos square n=300 c=20 snr=1.0 white | 91/100 | 94/100 |
| pos square n=300 c=20 snr=2.0 ar09 | 89/100 | 93/100 |
| pos square n=300 c=20 snr=1.0 ar09 | 32/100 | 27/100 |
| pos lagged_square n=300 c=20 snr=2.0 white | 98/100 | 99/100 |
| pos lagged_square n=300 c=20 snr=1.0 white | 87/100 | 89/100 |
| pos lagged_square n=300 c=20 snr=2.0 ar09 | 83/100 | 85/100 |
| pos lagged_square n=300 c=20 snr=1.0 ar09 | 4/100 | 4/100 |

## All positive cells

| cell | I | A |
| --- | --- | --- |
| pos sine n=300 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos sine n=300 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos sine n=300 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos sine n=300 c=4 snr=2.0 white | 2/100 | 0/100 |
| pos sine n=300 c=4 snr=1.0 white | 7/100 | 0/100 |
| pos sine n=300 c=4 snr=0.5 white | 0/100 | 0/100 |
| pos sine n=300 c=5 snr=2.0 white | 89/100 | 0/100 |
| pos sine n=300 c=5 snr=1.0 white | 71/100 | 0/100 |
| pos sine n=300 c=5 snr=0.5 white | 3/100 | 0/100 |
| pos sine n=300 c=6 snr=2.0 white | 100/100 | 1/100 |
| pos sine n=300 c=6 snr=1.0 white | 92/100 | 1/100 |
| pos sine n=300 c=6 snr=0.5 white | 13/100 | 0/100 |
| pos sine n=300 c=8 snr=2.0 white | 100/100 | 98/100 |
| pos sine n=300 c=8 snr=1.0 white | 98/100 | 96/100 |
| pos sine n=300 c=8 snr=0.5 white | 21/100 | 19/100 |
| pos sine n=300 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos sine n=300 c=10 snr=1.0 white | 98/100 | 100/100 |
| pos sine n=300 c=10 snr=0.5 white | 13/100 | 27/100 |
| pos sine n=300 c=20 snr=2.0 white | 97/100 | 99/100 |
| pos sine n=300 c=20 snr=1.0 white | 84/100 | 87/100 |
| pos sine n=300 c=20 snr=0.5 white | 6/100 | 13/100 |
| pos sine n=1000 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos sine n=1000 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos sine n=1000 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos sine n=1000 c=4 snr=2.0 white | 0/100 | 0/100 |
| pos sine n=1000 c=4 snr=1.0 white | 5/100 | 0/100 |
| pos sine n=1000 c=4 snr=0.5 white | 22/100 | 0/100 |
| pos sine n=1000 c=5 snr=2.0 white | 100/100 | 0/100 |
| pos sine n=1000 c=5 snr=1.0 white | 100/100 | 0/100 |
| pos sine n=1000 c=5 snr=0.5 white | 83/100 | 0/100 |
| pos sine n=1000 c=6 snr=2.0 white | 100/100 | 0/100 |
| pos sine n=1000 c=6 snr=1.0 white | 100/100 | 0/100 |
| pos sine n=1000 c=6 snr=0.5 white | 97/100 | 0/100 |
| pos sine n=1000 c=8 snr=2.0 white | 100/100 | 100/100 |
| pos sine n=1000 c=8 snr=1.0 white | 100/100 | 100/100 |
| pos sine n=1000 c=8 snr=0.5 white | 93/100 | 94/100 |
| pos sine n=1000 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos sine n=1000 c=10 snr=1.0 white | 100/100 | 100/100 |
| pos sine n=1000 c=10 snr=0.5 white | 88/100 | 97/100 |
| pos sine n=1000 c=20 snr=2.0 white | 96/100 | 100/100 |
| pos sine n=1000 c=20 snr=1.0 white | 97/100 | 100/100 |
| pos sine n=1000 c=20 snr=0.5 white | 81/100 | 84/100 |
| pos sine n=3000 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos sine n=3000 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos sine n=3000 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos sine n=3000 c=4 snr=2.0 white | 0/100 | 0/100 |
| pos sine n=3000 c=4 snr=1.0 white | 0/100 | 0/100 |
| pos sine n=3000 c=4 snr=0.5 white | 53/100 | 0/100 |
| pos sine n=3000 c=5 snr=2.0 white | 100/100 | 0/100 |
| pos sine n=3000 c=5 snr=1.0 white | 100/100 | 0/100 |
| pos sine n=3000 c=5 snr=0.5 white | 100/100 | 0/100 |
| pos sine n=3000 c=6 snr=2.0 white | 100/100 | 0/100 |
| pos sine n=3000 c=6 snr=1.0 white | 100/100 | 0/100 |
| pos sine n=3000 c=6 snr=0.5 white | 100/100 | 0/100 |
| pos sine n=3000 c=8 snr=2.0 white | 100/100 | 100/100 |
| pos sine n=3000 c=8 snr=1.0 white | 100/100 | 100/100 |
| pos sine n=3000 c=8 snr=0.5 white | 100/100 | 100/100 |
| pos sine n=3000 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos sine n=3000 c=10 snr=1.0 white | 100/100 | 100/100 |
| pos sine n=3000 c=10 snr=0.5 white | 100/100 | 100/100 |
| pos sine n=3000 c=20 snr=2.0 white | 100/100 | 100/100 |
| pos sine n=3000 c=20 snr=1.0 white | 100/100 | 100/100 |
| pos sine n=3000 c=20 snr=0.5 white | 100/100 | 100/100 |
| pos sine n=300 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=4 snr=2.0 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=4 snr=1.0 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=4 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=5 snr=2.0 ar09 | 5/100 | 0/100 |
| pos sine n=300 c=5 snr=1.0 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=5 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=6 snr=2.0 ar09 | 34/100 | 1/100 |
| pos sine n=300 c=6 snr=1.0 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=6 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=8 snr=2.0 ar09 | 67/100 | 63/100 |
| pos sine n=300 c=8 snr=1.0 ar09 | 1/100 | 2/100 |
| pos sine n=300 c=8 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=10 snr=2.0 ar09 | 74/100 | 72/100 |
| pos sine n=300 c=10 snr=1.0 ar09 | 1/100 | 1/100 |
| pos sine n=300 c=10 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=300 c=20 snr=2.0 ar09 | 85/100 | 88/100 |
| pos sine n=300 c=20 snr=1.0 ar09 | 4/100 | 3/100 |
| pos sine n=300 c=20 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=4 snr=2.0 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=4 snr=1.0 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=4 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=5 snr=2.0 ar09 | 39/100 | 0/100 |
| pos sine n=1000 c=5 snr=1.0 ar09 | 2/100 | 0/100 |
| pos sine n=1000 c=5 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=6 snr=2.0 ar09 | 87/100 | 0/100 |
| pos sine n=1000 c=6 snr=1.0 ar09 | 12/100 | 0/100 |
| pos sine n=1000 c=6 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=1000 c=8 snr=2.0 ar09 | 95/100 | 89/100 |
| pos sine n=1000 c=8 snr=1.0 ar09 | 16/100 | 15/100 |
| pos sine n=1000 c=8 snr=0.5 ar09 | 1/100 | 0/100 |
| pos sine n=1000 c=10 snr=2.0 ar09 | 98/100 | 96/100 |
| pos sine n=1000 c=10 snr=1.0 ar09 | 20/100 | 31/100 |
| pos sine n=1000 c=10 snr=0.5 ar09 | 0/100 | 1/100 |
| pos sine n=1000 c=20 snr=2.0 ar09 | 95/100 | 98/100 |
| pos sine n=1000 c=20 snr=1.0 ar09 | 16/100 | 28/100 |
| pos sine n=1000 c=20 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=3000 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos sine n=3000 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos sine n=3000 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=3000 c=4 snr=2.0 ar09 | 0/100 | 0/100 |
| pos sine n=3000 c=4 snr=1.0 ar09 | 0/100 | 0/100 |
| pos sine n=3000 c=4 snr=0.5 ar09 | 0/100 | 0/100 |
| pos sine n=3000 c=5 snr=2.0 ar09 | 97/100 | 0/100 |
| pos sine n=3000 c=5 snr=1.0 ar09 | 44/100 | 0/100 |
| pos sine n=3000 c=5 snr=0.5 ar09 | 4/100 | 0/100 |
| pos sine n=3000 c=6 snr=2.0 ar09 | 100/100 | 0/100 |
| pos sine n=3000 c=6 snr=1.0 ar09 | 72/100 | 0/100 |
| pos sine n=3000 c=6 snr=0.5 ar09 | 6/100 | 0/100 |
| pos sine n=3000 c=8 snr=2.0 ar09 | 100/100 | 100/100 |
| pos sine n=3000 c=8 snr=1.0 ar09 | 84/100 | 87/100 |
| pos sine n=3000 c=8 snr=0.5 ar09 | 7/100 | 10/100 |
| pos sine n=3000 c=10 snr=2.0 ar09 | 100/100 | 100/100 |
| pos sine n=3000 c=10 snr=1.0 ar09 | 80/100 | 91/100 |
| pos sine n=3000 c=10 snr=0.5 ar09 | 3/100 | 15/100 |
| pos sine n=3000 c=20 snr=2.0 ar09 | 100/100 | 100/100 |
| pos sine n=3000 c=20 snr=1.0 ar09 | 86/100 | 89/100 |
| pos sine n=3000 c=20 snr=0.5 ar09 | 4/100 | 8/100 |
| pos square n=300 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos square n=300 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos square n=300 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos square n=300 c=4 snr=2.0 white | 12/100 | 0/100 |
| pos square n=300 c=4 snr=1.0 white | 13/100 | 0/100 |
| pos square n=300 c=4 snr=0.5 white | 3/100 | 0/100 |
| pos square n=300 c=5 snr=2.0 white | 95/100 | 0/100 |
| pos square n=300 c=5 snr=1.0 white | 90/100 | 0/100 |
| pos square n=300 c=5 snr=0.5 white | 21/100 | 0/100 |
| pos square n=300 c=6 snr=2.0 white | 100/100 | 1/100 |
| pos square n=300 c=6 snr=1.0 white | 99/100 | 1/100 |
| pos square n=300 c=6 snr=0.5 white | 38/100 | 1/100 |
| pos square n=300 c=8 snr=2.0 white | 100/100 | 97/100 |
| pos square n=300 c=8 snr=1.0 white | 98/100 | 95/100 |
| pos square n=300 c=8 snr=0.5 white | 43/100 | 52/100 |
| pos square n=300 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos square n=300 c=10 snr=1.0 white | 97/100 | 100/100 |
| pos square n=300 c=10 snr=0.5 white | 41/100 | 55/100 |
| pos square n=300 c=20 snr=2.0 white | 99/100 | 99/100 |
| pos square n=300 c=20 snr=1.0 white | 91/100 | 94/100 |
| pos square n=300 c=20 snr=0.5 white | 31/100 | 39/100 |
| pos square n=1000 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos square n=1000 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos square n=1000 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos square n=1000 c=4 snr=2.0 white | 7/100 | 0/100 |
| pos square n=1000 c=4 snr=1.0 white | 22/100 | 0/100 |
| pos square n=1000 c=4 snr=0.5 white | 42/100 | 0/100 |
| pos square n=1000 c=5 snr=2.0 white | 100/100 | 0/100 |
| pos square n=1000 c=5 snr=1.0 white | 100/100 | 0/100 |
| pos square n=1000 c=5 snr=0.5 white | 99/100 | 0/100 |
| pos square n=1000 c=6 snr=2.0 white | 100/100 | 0/100 |
| pos square n=1000 c=6 snr=1.0 white | 100/100 | 0/100 |
| pos square n=1000 c=6 snr=0.5 white | 100/100 | 0/100 |
| pos square n=1000 c=8 snr=2.0 white | 100/100 | 100/100 |
| pos square n=1000 c=8 snr=1.0 white | 100/100 | 100/100 |
| pos square n=1000 c=8 snr=0.5 white | 100/100 | 99/100 |
| pos square n=1000 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos square n=1000 c=10 snr=1.0 white | 100/100 | 100/100 |
| pos square n=1000 c=10 snr=0.5 white | 99/100 | 99/100 |
| pos square n=1000 c=20 snr=2.0 white | 96/100 | 100/100 |
| pos square n=1000 c=20 snr=1.0 white | 97/100 | 100/100 |
| pos square n=1000 c=20 snr=0.5 white | 96/100 | 99/100 |
| pos square n=3000 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos square n=3000 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos square n=3000 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos square n=3000 c=4 snr=2.0 white | 0/100 | 0/100 |
| pos square n=3000 c=4 snr=1.0 white | 10/100 | 0/100 |
| pos square n=3000 c=4 snr=0.5 white | 68/100 | 0/100 |
| pos square n=3000 c=5 snr=2.0 white | 100/100 | 0/100 |
| pos square n=3000 c=5 snr=1.0 white | 100/100 | 0/100 |
| pos square n=3000 c=5 snr=0.5 white | 100/100 | 0/100 |
| pos square n=3000 c=6 snr=2.0 white | 100/100 | 0/100 |
| pos square n=3000 c=6 snr=1.0 white | 100/100 | 0/100 |
| pos square n=3000 c=6 snr=0.5 white | 100/100 | 0/100 |
| pos square n=3000 c=8 snr=2.0 white | 100/100 | 100/100 |
| pos square n=3000 c=8 snr=1.0 white | 100/100 | 100/100 |
| pos square n=3000 c=8 snr=0.5 white | 100/100 | 100/100 |
| pos square n=3000 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos square n=3000 c=10 snr=1.0 white | 100/100 | 100/100 |
| pos square n=3000 c=10 snr=0.5 white | 100/100 | 100/100 |
| pos square n=3000 c=20 snr=2.0 white | 100/100 | 100/100 |
| pos square n=3000 c=20 snr=1.0 white | 100/100 | 100/100 |
| pos square n=3000 c=20 snr=0.5 white | 100/100 | 100/100 |
| pos square n=300 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos square n=300 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos square n=300 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=300 c=4 snr=2.0 ar09 | 0/100 | 0/100 |
| pos square n=300 c=4 snr=1.0 ar09 | 0/100 | 0/100 |
| pos square n=300 c=4 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=300 c=5 snr=2.0 ar09 | 54/100 | 0/100 |
| pos square n=300 c=5 snr=1.0 ar09 | 2/100 | 0/100 |
| pos square n=300 c=5 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=300 c=6 snr=2.0 ar09 | 84/100 | 1/100 |
| pos square n=300 c=6 snr=1.0 ar09 | 5/100 | 0/100 |
| pos square n=300 c=6 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=300 c=8 snr=2.0 ar09 | 95/100 | 86/100 |
| pos square n=300 c=8 snr=1.0 ar09 | 16/100 | 12/100 |
| pos square n=300 c=8 snr=0.5 ar09 | 0/100 | 1/100 |
| pos square n=300 c=10 snr=2.0 ar09 | 97/100 | 97/100 |
| pos square n=300 c=10 snr=1.0 ar09 | 17/100 | 19/100 |
| pos square n=300 c=10 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=300 c=20 snr=2.0 ar09 | 89/100 | 93/100 |
| pos square n=300 c=20 snr=1.0 ar09 | 32/100 | 27/100 |
| pos square n=300 c=20 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=1000 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos square n=1000 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos square n=1000 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=1000 c=4 snr=2.0 ar09 | 1/100 | 0/100 |
| pos square n=1000 c=4 snr=1.0 ar09 | 0/100 | 0/100 |
| pos square n=1000 c=4 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=1000 c=5 snr=2.0 ar09 | 89/100 | 0/100 |
| pos square n=1000 c=5 snr=1.0 ar09 | 12/100 | 0/100 |
| pos square n=1000 c=5 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=1000 c=6 snr=2.0 ar09 | 99/100 | 0/100 |
| pos square n=1000 c=6 snr=1.0 ar09 | 33/100 | 0/100 |
| pos square n=1000 c=6 snr=0.5 ar09 | 1/100 | 0/100 |
| pos square n=1000 c=8 snr=2.0 ar09 | 99/100 | 98/100 |
| pos square n=1000 c=8 snr=1.0 ar09 | 55/100 | 52/100 |
| pos square n=1000 c=8 snr=0.5 ar09 | 1/100 | 3/100 |
| pos square n=1000 c=10 snr=2.0 ar09 | 99/100 | 99/100 |
| pos square n=1000 c=10 snr=1.0 ar09 | 66/100 | 69/100 |
| pos square n=1000 c=10 snr=0.5 ar09 | 0/100 | 4/100 |
| pos square n=1000 c=20 snr=2.0 ar09 | 96/100 | 99/100 |
| pos square n=1000 c=20 snr=1.0 ar09 | 64/100 | 67/100 |
| pos square n=1000 c=20 snr=0.5 ar09 | 0/100 | 1/100 |
| pos square n=3000 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos square n=3000 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos square n=3000 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos square n=3000 c=4 snr=2.0 ar09 | 5/100 | 0/100 |
| pos square n=3000 c=4 snr=1.0 ar09 | 8/100 | 0/100 |
| pos square n=3000 c=4 snr=0.5 ar09 | 1/100 | 0/100 |
| pos square n=3000 c=5 snr=2.0 ar09 | 100/100 | 0/100 |
| pos square n=3000 c=5 snr=1.0 ar09 | 85/100 | 0/100 |
| pos square n=3000 c=5 snr=0.5 ar09 | 15/100 | 0/100 |
| pos square n=3000 c=6 snr=2.0 ar09 | 100/100 | 0/100 |
| pos square n=3000 c=6 snr=1.0 ar09 | 98/100 | 0/100 |
| pos square n=3000 c=6 snr=0.5 ar09 | 23/100 | 0/100 |
| pos square n=3000 c=8 snr=2.0 ar09 | 100/100 | 100/100 |
| pos square n=3000 c=8 snr=1.0 ar09 | 97/100 | 98/100 |
| pos square n=3000 c=8 snr=0.5 ar09 | 21/100 | 36/100 |
| pos square n=3000 c=10 snr=2.0 ar09 | 100/100 | 100/100 |
| pos square n=3000 c=10 snr=1.0 ar09 | 99/100 | 100/100 |
| pos square n=3000 c=10 snr=0.5 ar09 | 17/100 | 44/100 |
| pos square n=3000 c=20 snr=2.0 ar09 | 100/100 | 100/100 |
| pos square n=3000 c=20 snr=1.0 ar09 | 99/100 | 100/100 |
| pos square n=3000 c=20 snr=0.5 ar09 | 17/100 | 26/100 |
| pos lagged_square n=300 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos lagged_square n=300 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos lagged_square n=300 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos lagged_square n=300 c=4 snr=2.0 white | 2/100 | 0/100 |
| pos lagged_square n=300 c=4 snr=1.0 white | 7/100 | 0/100 |
| pos lagged_square n=300 c=4 snr=0.5 white | 0/100 | 0/100 |
| pos lagged_square n=300 c=5 snr=2.0 white | 88/100 | 0/100 |
| pos lagged_square n=300 c=5 snr=1.0 white | 67/100 | 0/100 |
| pos lagged_square n=300 c=5 snr=0.5 white | 6/100 | 0/100 |
| pos lagged_square n=300 c=6 snr=2.0 white | 99/100 | 1/100 |
| pos lagged_square n=300 c=6 snr=1.0 white | 93/100 | 1/100 |
| pos lagged_square n=300 c=6 snr=0.5 white | 8/100 | 0/100 |
| pos lagged_square n=300 c=8 snr=2.0 white | 100/100 | 96/100 |
| pos lagged_square n=300 c=8 snr=1.0 white | 95/100 | 92/100 |
| pos lagged_square n=300 c=8 snr=0.5 white | 17/100 | 18/100 |
| pos lagged_square n=300 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos lagged_square n=300 c=10 snr=1.0 white | 93/100 | 98/100 |
| pos lagged_square n=300 c=10 snr=0.5 white | 16/100 | 23/100 |
| pos lagged_square n=300 c=20 snr=2.0 white | 98/100 | 99/100 |
| pos lagged_square n=300 c=20 snr=1.0 white | 87/100 | 89/100 |
| pos lagged_square n=300 c=20 snr=0.5 white | 5/100 | 9/100 |
| pos lagged_square n=1000 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos lagged_square n=1000 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos lagged_square n=1000 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos lagged_square n=1000 c=4 snr=2.0 white | 0/100 | 0/100 |
| pos lagged_square n=1000 c=4 snr=1.0 white | 10/100 | 0/100 |
| pos lagged_square n=1000 c=4 snr=0.5 white | 30/100 | 0/100 |
| pos lagged_square n=1000 c=5 snr=2.0 white | 97/100 | 0/100 |
| pos lagged_square n=1000 c=5 snr=1.0 white | 98/100 | 0/100 |
| pos lagged_square n=1000 c=5 snr=0.5 white | 86/100 | 0/100 |
| pos lagged_square n=1000 c=6 snr=2.0 white | 100/100 | 0/100 |
| pos lagged_square n=1000 c=6 snr=1.0 white | 100/100 | 0/100 |
| pos lagged_square n=1000 c=6 snr=0.5 white | 95/100 | 0/100 |
| pos lagged_square n=1000 c=8 snr=2.0 white | 100/100 | 100/100 |
| pos lagged_square n=1000 c=8 snr=1.0 white | 100/100 | 100/100 |
| pos lagged_square n=1000 c=8 snr=0.5 white | 93/100 | 98/100 |
| pos lagged_square n=1000 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos lagged_square n=1000 c=10 snr=1.0 white | 100/100 | 100/100 |
| pos lagged_square n=1000 c=10 snr=0.5 white | 94/100 | 98/100 |
| pos lagged_square n=1000 c=20 snr=2.0 white | 97/100 | 100/100 |
| pos lagged_square n=1000 c=20 snr=1.0 white | 98/100 | 100/100 |
| pos lagged_square n=1000 c=20 snr=0.5 white | 88/100 | 91/100 |
| pos lagged_square n=3000 c=3 snr=2.0 white | 0/100 | 0/100 |
| pos lagged_square n=3000 c=3 snr=1.0 white | 0/100 | 0/100 |
| pos lagged_square n=3000 c=3 snr=0.5 white | 0/100 | 0/100 |
| pos lagged_square n=3000 c=4 snr=2.0 white | 0/100 | 0/100 |
| pos lagged_square n=3000 c=4 snr=1.0 white | 0/100 | 0/100 |
| pos lagged_square n=3000 c=4 snr=0.5 white | 64/100 | 0/100 |
| pos lagged_square n=3000 c=5 snr=2.0 white | 100/100 | 0/100 |
| pos lagged_square n=3000 c=5 snr=1.0 white | 100/100 | 0/100 |
| pos lagged_square n=3000 c=5 snr=0.5 white | 100/100 | 0/100 |
| pos lagged_square n=3000 c=6 snr=2.0 white | 100/100 | 0/100 |
| pos lagged_square n=3000 c=6 snr=1.0 white | 100/100 | 0/100 |
| pos lagged_square n=3000 c=6 snr=0.5 white | 100/100 | 0/100 |
| pos lagged_square n=3000 c=8 snr=2.0 white | 100/100 | 100/100 |
| pos lagged_square n=3000 c=8 snr=1.0 white | 100/100 | 100/100 |
| pos lagged_square n=3000 c=8 snr=0.5 white | 100/100 | 100/100 |
| pos lagged_square n=3000 c=10 snr=2.0 white | 100/100 | 100/100 |
| pos lagged_square n=3000 c=10 snr=1.0 white | 100/100 | 100/100 |
| pos lagged_square n=3000 c=10 snr=0.5 white | 100/100 | 100/100 |
| pos lagged_square n=3000 c=20 snr=2.0 white | 100/100 | 100/100 |
| pos lagged_square n=3000 c=20 snr=1.0 white | 100/100 | 100/100 |
| pos lagged_square n=3000 c=20 snr=0.5 white | 100/100 | 100/100 |
| pos lagged_square n=300 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=4 snr=2.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=4 snr=1.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=4 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=5 snr=2.0 ar09 | 5/100 | 0/100 |
| pos lagged_square n=300 c=5 snr=1.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=5 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=6 snr=2.0 ar09 | 33/100 | 0/100 |
| pos lagged_square n=300 c=6 snr=1.0 ar09 | 2/100 | 0/100 |
| pos lagged_square n=300 c=6 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=8 snr=2.0 ar09 | 64/100 | 52/100 |
| pos lagged_square n=300 c=8 snr=1.0 ar09 | 3/100 | 2/100 |
| pos lagged_square n=300 c=8 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=10 snr=2.0 ar09 | 78/100 | 71/100 |
| pos lagged_square n=300 c=10 snr=1.0 ar09 | 1/100 | 1/100 |
| pos lagged_square n=300 c=10 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=300 c=20 snr=2.0 ar09 | 83/100 | 85/100 |
| pos lagged_square n=300 c=20 snr=1.0 ar09 | 4/100 | 4/100 |
| pos lagged_square n=300 c=20 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=4 snr=2.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=4 snr=1.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=4 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=5 snr=2.0 ar09 | 42/100 | 0/100 |
| pos lagged_square n=1000 c=5 snr=1.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=5 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=6 snr=2.0 ar09 | 84/100 | 0/100 |
| pos lagged_square n=1000 c=6 snr=1.0 ar09 | 11/100 | 0/100 |
| pos lagged_square n=1000 c=6 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=8 snr=2.0 ar09 | 94/100 | 90/100 |
| pos lagged_square n=1000 c=8 snr=1.0 ar09 | 16/100 | 13/100 |
| pos lagged_square n=1000 c=8 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=1000 c=10 snr=2.0 ar09 | 97/100 | 94/100 |
| pos lagged_square n=1000 c=10 snr=1.0 ar09 | 21/100 | 24/100 |
| pos lagged_square n=1000 c=10 snr=0.5 ar09 | 0/100 | 1/100 |
| pos lagged_square n=1000 c=20 snr=2.0 ar09 | 95/100 | 99/100 |
| pos lagged_square n=1000 c=20 snr=1.0 ar09 | 17/100 | 26/100 |
| pos lagged_square n=1000 c=20 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=3000 c=3 snr=2.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=3000 c=3 snr=1.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=3000 c=3 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=3000 c=4 snr=2.0 ar09 | 0/100 | 0/100 |
| pos lagged_square n=3000 c=4 snr=1.0 ar09 | 1/100 | 0/100 |
| pos lagged_square n=3000 c=4 snr=0.5 ar09 | 0/100 | 0/100 |
| pos lagged_square n=3000 c=5 snr=2.0 ar09 | 93/100 | 0/100 |
| pos lagged_square n=3000 c=5 snr=1.0 ar09 | 47/100 | 0/100 |
| pos lagged_square n=3000 c=5 snr=0.5 ar09 | 4/100 | 0/100 |
| pos lagged_square n=3000 c=6 snr=2.0 ar09 | 100/100 | 0/100 |
| pos lagged_square n=3000 c=6 snr=1.0 ar09 | 70/100 | 0/100 |
| pos lagged_square n=3000 c=6 snr=0.5 ar09 | 7/100 | 0/100 |
| pos lagged_square n=3000 c=8 snr=2.0 ar09 | 100/100 | 100/100 |
| pos lagged_square n=3000 c=8 snr=1.0 ar09 | 88/100 | 85/100 |
| pos lagged_square n=3000 c=8 snr=0.5 ar09 | 8/100 | 12/100 |
| pos lagged_square n=3000 c=10 snr=2.0 ar09 | 100/100 | 100/100 |
| pos lagged_square n=3000 c=10 snr=1.0 ar09 | 80/100 | 90/100 |
| pos lagged_square n=3000 c=10 snr=0.5 ar09 | 3/100 | 13/100 |
| pos lagged_square n=3000 c=20 snr=2.0 ar09 | 100/100 | 100/100 |
| pos lagged_square n=3000 c=20 snr=1.0 ar09 | 85/100 | 88/100 |
| pos lagged_square n=3000 c=20 snr=0.5 ar09 | 5/100 | 13/100 |
