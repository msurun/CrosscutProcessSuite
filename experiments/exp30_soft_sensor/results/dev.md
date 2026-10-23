# exp30 results: dev seeds

Seeds: 40; runtime 568 s. Dev seeds are a harness check only; the frozen criteria apply to the test seeds.

## Criteria

| id | values | verdict |
| --- | --- | --- |
| S1 | normal records with RMSE >= 20 % below carry-forward: 13/14 (0.929) | PASS |
| S2 | regime: 1.000 of 19028 rows outside the training hardness range flagged; normal: 0.794 of 140432 rows inside the range ok | MISS |
| S3 | drift raised by the deadline 0/13 (0.000); raised on normal records 0/14 (0.000) | MISS |
| S4 | identical coefficients without post-cut labs 40/40; CV gap = longest lag 40/40 (record truncated at the cut also identical 40/40) | PASS |

## Reported (no target)

| scenario | records | RMSE | RMSE corrected | RMSE carry-forward | R2 | beats baseline | ok | out_of_range | extrapolation | components |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| normal | 14 | 0.867 | 0.834 | 1.452 | 0.262 | 14 | 0.790 | 0.201 | 0.009 | [1, 2, 3] |
| regime | 13 | 1.432 | 1.326 | 1.846 | 0.438 | 11 | 0.674 | 0.315 | 0.012 | [1, 2, 3] |
| drift | 13 | 0.854 | 0.848 | 1.431 | 0.205 | 13 | 0.772 | 0.210 | 0.018 | [2, 3, 5] |

- regime window (24 h) RMSE: estimate 3.209, carry-forward 2.667 (mean over records)
- drift records: first drift flag after onset, delay [h]: [125.0]
- drift records flagged between the cut and the onset: 0
- S4 refit model sha256 identical: 40 records

## Per seed

| seed | scenario | A | cv sigma | RMSE | carry-fwd | R2 | ok share | outside flagged | drift first [d] | detected | S4 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |
| 29401 | normal | 2 | 0.788 | 1.003 | 1.519 | 0.143 | 0.773 | 44/44 | - | False | True |
| 29402 | regime | 2 | 0.880 | 1.127 | 1.965 | 0.690 | 0.684 | 1440/1440 | - | False | True |
| 29403 | drift | 2 | 0.777 | 0.827 | 1.525 | 0.340 | 0.889 | 0/0 | - | False | True |
| 29404 | normal | 2 | 0.849 | 0.783 | 1.275 | 0.334 | 0.771 | 9/9 | - | False | True |
| 29405 | regime | 2 | 1.000 | 1.186 | 1.369 | 0.571 | 0.534 | 1440/1440 | - | False | True |
| 29406 | drift | 5 | 0.869 | 0.976 | 1.384 | 0.067 | 0.651 | 76/76 | - | False | True |
| 29407 | normal | 2 | 0.858 | 0.858 | 1.664 | 0.309 | 0.753 | 2/2 | - | False | True |
| 29408 | regime | 2 | 0.756 | 1.595 | 1.787 | 0.117 | 0.574 | 1686/1686 | 16.54 | True | True |
| 29409 | drift | 2 | 0.685 | 0.972 | 1.258 | -0.001 | 0.724 | 13/13 | - | False | True |
| 29410 | normal | 2 | 0.770 | 0.758 | 1.519 | 0.484 | 0.771 | 44/46 | - | False | True |
| 29411 | regime | 2 | 0.814 | 1.599 | 1.509 | 0.373 | 0.687 | 1440/1440 | 16.88 | True | True |
| 29412 | drift | 2 | 0.933 | 0.758 | 1.549 | 0.434 | 0.820 | 0/0 | - | False | True |
| 29413 | normal | 2 | 0.994 | 0.821 | 1.340 | 0.177 | 0.866 | 0/0 | - | False | True |
| 29414 | regime | 3 | 0.841 | 1.122 | 1.566 | 0.258 | 0.738 | 1373/1373 | 17.04 | True | True |
| 29415 | drift | 2 | 0.992 | 0.831 | 1.300 | 0.186 | 0.771 | 0/0 | - | False | True |
| 29416 | normal | 2 | 0.813 | 0.765 | 1.439 | 0.359 | 0.766 | 90/90 | - | False | True |
| 29417 | regime | 2 | 0.844 | 1.366 | 1.871 | 0.569 | 0.724 | 1597/1597 | 16.71 | True | True |
| 29418 | drift | 2 | 0.891 | 0.735 | 1.654 | 0.401 | 0.947 | 0/0 | - | False | True |
| 29419 | normal | 1 | 0.873 | 1.375 | 1.540 | -0.391 | 0.683 | 263/263 | - | False | True |
| 29420 | regime | 2 | 0.772 | 1.835 | 2.065 | 0.284 | 0.655 | 1440/1440 | 16.54 | True | True |
| 29421 | drift | 2 | 0.750 | 0.840 | 1.297 | 0.114 | 0.723 | 220/220 | - | False | True |
| 29422 | normal | 2 | 0.939 | 0.816 | 1.555 | 0.412 | 0.799 | 123/123 | - | False | True |
| 29423 | regime | 1 | 0.818 | 2.195 | 1.839 | 0.136 | 0.642 | 1440/1440 | 16.54 | True | True |
| 29424 | drift | 2 | 0.720 | 1.134 | 1.637 | -0.421 | 0.775 | 0/0 | 20.21 | False | True |
| 29425 | normal | 2 | 0.732 | 0.833 | 1.386 | 0.416 | 0.773 | 24/24 | - | False | True |
| 29426 | regime | 2 | 0.926 | 1.306 | 2.092 | 0.548 | 0.612 | 1449/1449 | 16.54 | True | True |
| 29427 | drift | 2 | 0.880 | 0.836 | 1.455 | 0.306 | 0.740 | 35/35 | - | False | True |
| 29428 | normal | 1 | 1.233 | 0.863 | 1.521 | 0.266 | 0.805 | 0/0 | - | False | True |
| 29429 | regime | 2 | 1.166 | 1.336 | 1.762 | 0.526 | 0.691 | 1449/1449 | - | False | True |
| 29430 | drift | 2 | 1.113 | 0.743 | 1.229 | 0.455 | 0.821 | 0/0 | - | False | True |
| 29431 | normal | 2 | 0.977 | 0.676 | 1.308 | 0.462 | 0.857 | 8/8 | - | False | True |
| 29432 | regime | 2 | 0.879 | 1.368 | 2.281 | 0.483 | 0.713 | 1440/1440 | 17.38 | True | True |
| 29433 | drift | 2 | 1.014 | 0.849 | 1.477 | 0.035 | 0.670 | 14/14 | - | False | True |
| 29434 | normal | 2 | 0.810 | 1.093 | 1.483 | -0.109 | 0.764 | 67/67 | - | False | True |
| 29435 | regime | 2 | 0.840 | 1.410 | 2.087 | 0.522 | 0.731 | 1405/1411 | 17.04 | True | True |
| 29436 | drift | 3 | 0.726 | 0.740 | 1.377 | 0.467 | 0.792 | 0/0 | - | False | True |
| 29437 | normal | 2 | 0.874 | 0.739 | 1.208 | 0.352 | 0.840 | 12/12 | - | False | True |
| 29438 | regime | 2 | 1.098 | 1.170 | 1.804 | 0.621 | 0.771 | 1423/1423 | 16.88 | True | True |
| 29439 | drift | 2 | 0.908 | 0.866 | 1.459 | 0.285 | 0.707 | 92/97 | - | False | True |
| 29440 | normal | 3 | 0.932 | 0.752 | 1.575 | 0.456 | 0.834 | 0/0 | - | False | True |
