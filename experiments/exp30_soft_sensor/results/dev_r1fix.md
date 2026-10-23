# exp30 results: dev seeds

Seeds: 40; runtime 530 s. Dev seeds are a harness check only; the frozen criteria apply to the test seeds.

## Criteria

| id | values | verdict |
| --- | --- | --- |
| S1 | normal records with RMSE >= 20 % below carry-forward: 13/14 (0.929) | PASS |
| S2 | regime: 0.993 of 19028 rows outside the training hardness range flagged; normal: 0.969 of 140432 rows inside the range ok | PASS |
| S3 | drift raised by the deadline 1/13 (0.077); raised on normal records 1/14 (0.071) | MISS |
| S4 | identical coefficients without post-cut labs 40/40; CV gap = longest lag 40/40 (record truncated at the cut also identical 40/40) | PASS |

## Reported (no target)

| scenario | records | RMSE | RMSE corrected | RMSE carry-forward | R2 | beats baseline | ok | out_of_range | extrapolation | components |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| normal | 14 | 0.867 | 0.834 | 1.452 | 0.262 | 14 | 0.965 | 0.010 | 0.024 | [1, 2, 3] |
| regime | 13 | 1.432 | 1.326 | 1.846 | 0.438 | 11 | 0.829 | 0.153 | 0.018 | [1, 2, 3] |
| drift | 13 | 0.854 | 0.848 | 1.431 | 0.205 | 13 | 0.972 | 0.009 | 0.018 | [2, 3, 5] |

- regime window (24 h) RMSE: estimate 3.209, carry-forward 2.667 (mean over records)
- drift records: first drift flag after onset, delay [h]: [133.0, 53.0]
- drift records flagged between the cut and the onset: 0
- S4 refit model sha256 identical: 40 records

## Per seed

| seed | scenario | A | cv sigma | RMSE | carry-fwd | R2 | ok share | outside flagged | drift first [d] | detected | S4 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |
| 29401 | normal | 2 | 0.788 | 1.003 | 1.519 | 0.143 | 0.954 | 39/44 | - | False | True |
| 29402 | regime | 2 | 0.880 | 1.127 | 1.965 | 0.690 | 0.829 | 1440/1440 | - | False | True |
| 29403 | drift | 2 | 0.777 | 0.827 | 1.525 | 0.340 | 0.992 | 0/0 | - | False | True |
| 29404 | normal | 2 | 0.849 | 0.783 | 1.275 | 0.334 | 0.968 | 3/9 | - | False | True |
| 29405 | regime | 2 | 1.000 | 1.186 | 1.369 | 0.571 | 0.812 | 1440/1440 | 16.88 | True | True |
| 29406 | drift | 5 | 0.869 | 0.976 | 1.384 | 0.067 | 0.970 | 39/76 | - | False | True |
| 29407 | normal | 2 | 0.858 | 0.858 | 1.664 | 0.309 | 0.955 | 0/2 | - | False | True |
| 29408 | regime | 2 | 0.756 | 1.595 | 1.787 | 0.117 | 0.786 | 1640/1686 | 16.38 | True | True |
| 29409 | drift | 2 | 0.685 | 0.972 | 1.258 | -0.001 | 0.966 | 13/13 | 20.54 | False | True |
| 29410 | normal | 2 | 0.770 | 0.758 | 1.519 | 0.484 | 0.971 | 14/46 | - | False | True |
| 29411 | regime | 2 | 0.814 | 1.599 | 1.509 | 0.373 | 0.823 | 1440/1440 | 16.38 | True | True |
| 29412 | drift | 2 | 0.933 | 0.758 | 1.549 | 0.434 | 0.988 | 0/0 | - | False | True |
| 29413 | normal | 2 | 0.994 | 0.821 | 1.340 | 0.177 | 0.991 | 0/0 | - | False | True |
| 29414 | regime | 3 | 0.841 | 1.122 | 1.566 | 0.258 | 0.849 | 1333/1373 | 17.04 | True | True |
| 29415 | drift | 2 | 0.992 | 0.831 | 1.300 | 0.186 | 0.974 | 0/0 | - | False | True |
| 29416 | normal | 2 | 0.813 | 0.765 | 1.439 | 0.359 | 0.965 | 60/90 | - | False | True |
| 29417 | regime | 2 | 0.844 | 1.366 | 1.871 | 0.569 | 0.820 | 1586/1597 | 16.54 | True | True |
| 29418 | drift | 2 | 0.891 | 0.735 | 1.654 | 0.401 | 0.998 | 0/0 | - | False | True |
| 29419 | normal | 1 | 0.873 | 1.375 | 1.540 | -0.391 | 0.920 | 218/263 | 14.71 | True | True |
| 29420 | regime | 2 | 0.772 | 1.835 | 2.065 | 0.284 | 0.834 | 1440/1440 | 16.54 | True | True |
| 29421 | drift | 2 | 0.750 | 0.840 | 1.297 | 0.114 | 0.927 | 153/220 | - | False | True |
| 29422 | normal | 2 | 0.939 | 0.816 | 1.555 | 0.412 | 0.976 | 102/123 | - | False | True |
| 29423 | regime | 1 | 0.818 | 2.195 | 1.839 | 0.136 | 0.814 | 1440/1440 | 16.54 | True | True |
| 29424 | drift | 2 | 0.720 | 1.134 | 1.637 | -0.421 | 0.988 | 0/0 | 17.21 | True | True |
| 29425 | normal | 2 | 0.732 | 0.833 | 1.386 | 0.416 | 0.950 | 24/24 | - | False | True |
| 29426 | regime | 2 | 0.926 | 1.306 | 2.092 | 0.548 | 0.829 | 1440/1449 | 16.54 | True | True |
| 29427 | drift | 2 | 0.880 | 0.836 | 1.455 | 0.306 | 0.953 | 21/35 | - | False | True |
| 29428 | normal | 1 | 1.233 | 0.863 | 1.521 | 0.266 | 0.977 | 0/0 | - | False | True |
| 29429 | regime | 2 | 1.166 | 1.336 | 1.762 | 0.526 | 0.833 | 1449/1449 | 16.88 | True | True |
| 29430 | drift | 2 | 1.113 | 0.743 | 1.229 | 0.455 | 0.989 | 0/0 | - | False | True |
| 29431 | normal | 2 | 0.977 | 0.676 | 1.308 | 0.462 | 0.996 | 1/8 | - | False | True |
| 29432 | regime | 2 | 0.879 | 1.368 | 2.281 | 0.483 | 0.839 | 1440/1440 | 16.71 | True | True |
| 29433 | drift | 2 | 1.014 | 0.849 | 1.477 | 0.035 | 0.985 | 2/14 | - | False | True |
| 29434 | normal | 2 | 0.810 | 1.093 | 1.483 | -0.109 | 0.957 | 67/67 | - | False | True |
| 29435 | regime | 2 | 0.840 | 1.410 | 2.087 | 0.522 | 0.853 | 1381/1411 | 16.71 | True | True |
| 29436 | drift | 3 | 0.726 | 0.740 | 1.377 | 0.467 | 0.975 | 0/0 | - | False | True |
| 29437 | normal | 2 | 0.874 | 0.739 | 1.208 | 0.352 | 0.975 | 12/12 | - | False | True |
| 29438 | regime | 2 | 1.098 | 1.170 | 1.804 | 0.621 | 0.853 | 1422/1423 | 16.88 | True | True |
| 29439 | drift | 2 | 0.908 | 0.866 | 1.459 | 0.285 | 0.935 | 85/97 | - | False | True |
| 29440 | normal | 3 | 0.932 | 0.752 | 1.575 | 0.456 | 0.962 | 0/0 | - | False | True |
