# exp29 results (round 2): dev seeds

Seeds: 60; runtime 546 s. Dev seeds are a harness check only (each seed: training, quiet and fault record); the frozen criteria apply to the test seeds.

## Criteria

| id | values | verdict |
| --- | --- | --- |
| B1 | false alarm events (any rule) per 24 h on 60 quiet records: mean 49.811 (pca 1.811), max 52.333 | MISS |
| B2 | drift detected 12/12 (1.000); by pca 12, by stuck 10 | PASS |
| B3 | freeze detected 11/12 (0.917); by pca 0, by stuck 11 | PASS |
| B4 | faulty tag in top 2 (stuck: named) 0.565 of 23 detected (21 by the stuck rule); SPE 0.565, T2 0.565 | MISS |
| B5 | removed-rows property 23/24 bad_quality+dropout records (other kinds 36/36) | MISS |
| B6 | stuck events per 24 h on 60 quiet records: mean 48.000, max 48.000, records with any 60 | MISS |

## Reported (no target)

| kind | records | rate (any) | median delay [min] | pca rate | pca delay | stuck rate | stuck delay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| drift | 12 | 1.000 | 19.2 | 1.000 | 90.9 | 0.833 | 17.6 |
| freeze | 12 | 0.917 | 1.5 | 0.000 | - | 0.917 | 1.5 |
| spike | 12 | 1.000 | 17.4 | 0.000 | - | 1.000 | 17.4 |
| bad_quality | 12 | 0.000 | - | 0.000 | - | 0.000 | - |
| dropout | 12 | 0.000 | - | 0.000 | - | 0.000 | - |

- training-record exceedance (expected near 1 - alpha = 0.01): T2 0.0099, SPE 0.0097 (mean over seeds)
- valid-row share: quiet 0.9995, fault 0.9812
- events starting before the fault onset on fault records: 1417
- model rank k values seen: [4, 5, 6]
- quiet records, events per 24 h by rule: pca 1.811, stuck 48.000
- valid rows lost to the lag history: total 288, mean 2.40 and max 4 per scanned record
- SPE limit method (seeds): {'empirical': 60}

## Per seed

| seed | k | SPE limit | train exc T2/SPE | quiet ev/24h pca/stuck | kind | tag | onset [h] | detected | delay [min] | rule | top2 hit | pca/stuck hit | B5 | valid share |
| ---: | ---: | --- | --- | --- | --- | --- | ---: | --- | ---: | --- | --- | --- | --- | ---: |
| 29601 | 5 | empirical | 0.008/0.010 | 1.00/48.00 | drift | hpgr_press | 11.20 | True | 20.0 | stuck | False | True/True | True | 0.9986 |
| 29602 | 4 | empirical | 0.015/0.010 | 1.33/48.00 | freeze | mill_feed | 10.45 | True | 1.8 | stuck | True | False/True | True | 0.9986 |
| 29603 | 5 | empirical | 0.001/0.010 | 2.33/48.00 | spike | cyc_water | 9.75 | True | 17.0 | stuck | False | False/True | True | 0.9986 |
| 29604 | 5 | empirical | 0.014/0.010 | 2.00/48.00 | bad_quality | feed_moisture | 15.27 | False | - | - | - | False/False | True | 0.9556 |
| 29605 | 5 | empirical | 0.007/0.010 | 2.67/48.00 | dropout | p80 | 12.36 | False | - | - | - | False/False | True | 0.9549 |
| 29606 | 4 | empirical | 0.008/0.010 | 0.67/48.00 | drift | mill_power | 10.50 | True | 2.1 | stuck | False | True/True | True | 0.9986 |
| 29607 | 5 | empirical | 0.009/0.010 | 4.33/48.00 | freeze | hpgr_power | 8.64 | True | 1.5 | stuck | True | False/True | True | 0.9986 |
| 29608 | 5 | empirical | 0.003/0.010 | 2.00/48.00 | spike | ore_hardness_est | 7.34 | True | 14.3 | stuck | True | False/True | True | 0.9986 |
| 29609 | 4 | empirical | 0.005/0.010 | 1.33/48.00 | bad_quality | hpgr_press | 12.66 | False | - | - | - | False/False | True | 0.9549 |
| 29610 | 5 | empirical | 0.010/0.010 | 0.00/48.00 | dropout | mill_feed | 14.29 | False | - | - | - | False/False | True | 0.9549 |
| 29611 | 5 | empirical | 0.006/0.010 | 1.00/48.00 | drift | cyc_water | 6.22 | True | 18.4 | stuck | False | True/True | True | 0.9986 |
| 29612 | 5 | empirical | 0.009/0.010 | 2.00/48.00 | freeze | feed_moisture | 14.94 | True | 1.5 | stuck | True | False/True | True | 0.9986 |
| 29613 | 4 | empirical | 0.000/0.010 | 0.33/48.00 | spike | p80 | 7.98 | True | 3.0 | stuck | False | False/True | True | 0.9986 |
| 29614 | 4 | empirical | 0.014/0.010 | 1.00/48.00 | bad_quality | mill_power | 12.37 | False | - | - | - | False/False | True | 0.9556 |
| 29615 | 6 | empirical | 0.010/0.010 | 3.67/48.00 | dropout | hpgr_power | 6.95 | False | - | - | - | False/False | True | 0.9549 |
| 29616 | 5 | empirical | 0.008/0.010 | 2.33/48.00 | drift | ore_hardness_est | 13.89 | True | 53.7 | pca | True | True/False | True | 0.9986 |
| 29617 | 5 | empirical | 0.021/0.010 | 0.33/48.00 | freeze | hpgr_press | 15.03 | True | 0.9 | stuck | True | False/True | True | 0.9986 |
| 29618 | 4 | empirical | 0.016/0.010 | 2.00/48.00 | spike | mill_feed | 15.70 | True | 19.8 | stuck | False | False/True | True | 0.9986 |
| 29619 | 5 | empirical | 0.017/0.010 | 3.00/48.00 | bad_quality | cyc_water | 9.27 | False | - | - | - | False/False | True | 0.9549 |
| 29620 | 4 | empirical | 0.009/0.010 | 1.33/48.00 | dropout | feed_moisture | 9.70 | False | - | - | - | False/False | True | 0.9556 |
| 29621 | 5 | empirical | 0.013/0.010 | 1.33/48.00 | drift | p80 | 14.48 | True | 3.1 | stuck | False | True/True | True | 0.9986 |
| 29622 | 5 | empirical | 0.010/0.010 | 2.00/48.00 | freeze | mill_power | 13.90 | True | 1.0 | stuck | True | False/True | True | 0.9986 |
| 29623 | 5 | empirical | 0.006/0.010 | 1.00/48.00 | spike | hpgr_power | 14.22 | True | 18.6 | stuck | False | False/True | True | 0.9986 |
| 29624 | 5 | empirical | 0.007/0.010 | 1.67/48.00 | bad_quality | ore_hardness_est | 15.58 | False | - | - | - | False/False | True | 0.9549 |
| 29625 | 4 | empirical | 0.011/0.010 | 4.00/48.00 | dropout | hpgr_press | 11.54 | False | - | - | - | False/False | True | 0.9549 |
| 29626 | 5 | empirical | 0.002/0.010 | 4.33/48.00 | drift | mill_feed | 9.44 | True | 5.7 | stuck | False | True/True | True | 0.9986 |
| 29627 | 5 | empirical | 0.009/0.010 | 3.33/48.00 | freeze | cyc_water | 9.94 | True | 1.7 | stuck | True | False/True | True | 0.9986 |
| 29628 | 4 | empirical | 0.008/0.010 | 1.33/48.00 | spike | feed_moisture | 7.93 | True | 6.2 | stuck | False | False/True | True | 0.9986 |
| 29629 | 5 | empirical | 0.015/0.010 | 0.33/48.00 | bad_quality | p80 | 6.70 | False | - | - | - | False/False | True | 0.9549 |
| 29630 | 4 | empirical | 0.010/0.010 | 1.00/48.00 | dropout | mill_power | 13.98 | False | - | - | - | False/False | True | 0.9549 |
| 29631 | 4 | empirical | 0.007/0.010 | 2.33/48.00 | drift | hpgr_power | 13.58 | True | 27.0 | stuck | False | True/True | True | 0.9986 |
| 29632 | 5 | empirical | 0.010/0.010 | 2.00/48.00 | freeze | ore_hardness_est | 8.39 | False | - | - | - | False/False | True | 0.9986 |
| 29633 | 5 | empirical | 0.002/0.010 | 1.67/48.00 | spike | hpgr_press | 6.48 | True | 3.1 | stuck | False | False/True | True | 0.9986 |
| 29634 | 4 | empirical | 0.019/0.010 | 1.33/48.00 | bad_quality | mill_feed | 8.94 | False | - | - | - | False/False | True | 0.9549 |
| 29635 | 4 | empirical | 0.021/0.010 | 1.67/48.00 | dropout | cyc_water | 13.84 | False | - | - | - | False/False | False | 0.9549 |
| 29636 | 4 | empirical | 0.010/0.010 | 2.00/48.00 | drift | feed_moisture | 11.12 | True | 24.3 | stuck | False | True/True | True | 0.9986 |
| 29637 | 4 | empirical | 0.003/0.010 | 1.67/48.00 | freeze | p80 | 13.82 | True | 1.4 | stuck | True | False/True | True | 0.9986 |
| 29638 | 5 | empirical | 0.006/0.010 | 1.33/48.00 | spike | mill_power | 12.07 | True | 27.8 | stuck | False | False/True | True | 0.9986 |
| 29639 | 5 | empirical | 0.009/0.010 | 2.33/48.00 | bad_quality | hpgr_power | 7.93 | False | - | - | - | False/False | True | 0.9556 |
| 29640 | 5 | empirical | 0.013/0.010 | 1.33/48.00 | dropout | ore_hardness_est | 9.56 | False | - | - | - | False/False | True | 0.9549 |
| 29641 | 4 | empirical | 0.006/0.010 | 2.00/48.00 | drift | hpgr_press | 6.75 | True | 16.9 | stuck | False | True/True | True | 0.9986 |
| 29642 | 5 | empirical | 0.005/0.010 | 3.00/48.00 | freeze | mill_feed | 8.47 | True | 1.7 | stuck | True | False/True | True | 0.9986 |
| 29643 | 4 | empirical | 0.006/0.010 | 0.33/48.00 | spike | cyc_water | 14.45 | True | 5.1 | stuck | False | False/True | True | 0.9986 |
| 29644 | 5 | empirical | 0.008/0.010 | 2.00/48.00 | bad_quality | feed_moisture | 12.56 | False | - | - | - | False/False | True | 0.9556 |
| 29645 | 5 | empirical | 0.027/0.010 | 1.00/48.00 | dropout | p80 | 13.57 | False | - | - | - | False/False | True | 0.9549 |
| 29646 | 4 | empirical | 0.008/0.010 | 2.00/48.00 | drift | mill_power | 13.02 | True | 0.5 | stuck | False | True/True | True | 0.9986 |
| 29647 | 5 | empirical | 0.019/0.010 | 1.67/48.00 | freeze | hpgr_power | 10.04 | True | 1.7 | stuck | True | False/True | True | 0.9986 |
| 29648 | 5 | empirical | 0.010/0.010 | 1.67/48.00 | spike | ore_hardness_est | 12.79 | True | 48.5 | stuck | True | False/True | True | 0.9986 |
| 29649 | 4 | empirical | 0.003/0.010 | 3.00/48.00 | bad_quality | hpgr_press | 14.89 | False | - | - | - | False/False | True | 0.9549 |
| 29650 | 4 | empirical | 0.010/0.010 | 1.33/48.00 | dropout | mill_feed | 14.08 | False | - | - | - | False/False | True | 0.9549 |
| 29651 | 5 | empirical | 0.008/0.010 | 3.67/48.00 | drift | cyc_water | 11.06 | True | 28.0 | stuck | False | True/True | True | 0.9986 |
| 29652 | 5 | empirical | 0.007/0.010 | 1.67/48.00 | freeze | feed_moisture | 11.07 | True | 1.5 | stuck | True | False/True | True | 0.9986 |
| 29653 | 4 | empirical | 0.012/0.010 | 1.67/48.00 | spike | p80 | 13.08 | True | 26.8 | stuck | False | False/True | True | 0.9986 |
| 29654 | 4 | empirical | 0.023/0.010 | 3.00/48.00 | bad_quality | mill_power | 15.08 | False | - | - | - | False/False | True | 0.9549 |
| 29655 | 4 | empirical | 0.009/0.010 | 1.00/48.00 | dropout | hpgr_power | 9.58 | False | - | - | - | False/False | True | 0.9549 |
| 29656 | 4 | empirical | 0.023/0.010 | 2.00/48.00 | drift | ore_hardness_est | 9.16 | True | 68.0 | pca | True | True/False | True | 0.9986 |
| 29657 | 5 | empirical | 0.004/0.010 | 1.67/48.00 | freeze | hpgr_press | 11.89 | True | 1.3 | stuck | True | False/True | True | 0.9986 |
| 29658 | 5 | empirical | 0.007/0.010 | 1.33/48.00 | spike | mill_feed | 8.23 | True | 17.8 | stuck | False | False/True | True | 0.9986 |
| 29659 | 4 | empirical | 0.014/0.010 | 1.00/48.00 | bad_quality | cyc_water | 15.47 | False | - | - | - | False/False | True | 0.9549 |
| 29660 | 5 | empirical | 0.008/0.010 | 1.00/48.00 | dropout | feed_moisture | 13.57 | False | - | - | - | False/False | True | 0.9549 |
