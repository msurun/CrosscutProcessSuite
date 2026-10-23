# exp29 results: dev seeds

Seeds: 60; runtime 310 s. Dev seeds are a harness check only (each seed: training, quiet and fault record); the frozen criteria apply to the test seeds.

## Criteria

| id | values | verdict |
| --- | --- | --- |
| A1 | false alarm events per 24 h on 60 quiet records: mean 2.533, max 6.000 | MISS |
| A2 | drift detected 11/12 (0.917) | PASS |
| A3 | freeze detected 2/12 (0.167) | MISS |
| A4 | faulty tag in top 2 (dominant statistic) 0.846 of 13 detected; SPE 0.769, T2 0.692, either 0.923 | PASS |
| A5 | removed-rows property 24/24 bad_quality+dropout records (other kinds 36/36) | PASS |

## Reported (no target)

| kind | records | detection rate | median delay [min] |
| --- | ---: | ---: | ---: |
| drift | 12 | 0.917 | 111.7 |
| freeze | 12 | 0.167 | 38.4 |
| spike | 12 | 0.083 | 5.8 |
| bad_quality | 12 | 0.000 | - |
| dropout | 12 | 0.000 | - |

- training-record exceedance (expected near 1 - alpha = 0.01): T2 0.0085, SPE 0.0081 (mean over seeds)
- valid-row share: quiet 1.0000, fault 0.9831
- events starting before the fault onset on fault records: 72
- model rank k values seen: [4, 5]

## Per seed

| seed | k | train exc T2/SPE | quiet ev/24h | kind | tag | onset [h] | detected | delay [min] | dominant | top2 hit | A5 | valid share |
| ---: | ---: | --- | ---: | --- | --- | ---: | --- | ---: | --- | --- | --- | ---: |
| 29001 | 5 | 0.004/0.004 | 2.00 | drift | hpgr_press | 12.05 | True | 132.7 | spe | True | True | 1.0000 |
| 29002 | 4 | 0.003/0.009 | 4.33 | freeze | mill_feed | 9.34 | False | - | - | - | True | 1.0000 |
| 29003 | 5 | 0.007/0.011 | 2.00 | spike | cyc_water | 13.40 | False | - | - | - | True | 1.0000 |
| 29004 | 5 | 0.005/0.014 | 1.67 | bad_quality | feed_moisture | 14.01 | False | - | - | - | True | 0.9576 |
| 29005 | 4 | 0.007/0.009 | 1.67 | dropout | p80 | 6.44 | False | - | - | - | True | 0.9576 |
| 29006 | 4 | 0.004/0.009 | 1.67 | drift | mill_power | 6.94 | True | 111.7 | spe | True | True | 1.0000 |
| 29007 | 4 | 0.007/0.004 | 1.67 | freeze | hpgr_power | 8.76 | True | 25.5 | t2 | False | True | 1.0000 |
| 29008 | 5 | 0.004/0.008 | 3.67 | spike | ore_hardness_est | 8.53 | False | - | - | - | True | 1.0000 |
| 29009 | 4 | 0.006/0.008 | 1.33 | bad_quality | hpgr_press | 12.11 | False | - | - | - | True | 0.9576 |
| 29010 | 5 | 0.017/0.012 | 3.00 | dropout | mill_feed | 7.23 | False | - | - | - | True | 0.9576 |
| 29011 | 4 | 0.003/0.007 | 3.67 | drift | cyc_water | 6.62 | True | 75.9 | t2 | True | True | 1.0000 |
| 29012 | 5 | 0.007/0.013 | 4.67 | freeze | feed_moisture | 8.64 | False | - | - | - | True | 1.0000 |
| 29013 | 4 | 0.006/0.009 | 2.00 | spike | p80 | 11.70 | True | 5.8 | t2 | True | True | 1.0000 |
| 29014 | 4 | 0.019/0.008 | 1.33 | bad_quality | mill_power | 11.03 | False | - | - | - | True | 0.9576 |
| 29015 | 4 | 0.015/0.007 | 1.33 | dropout | hpgr_power | 13.64 | False | - | - | - | True | 0.9576 |
| 29016 | 4 | 0.010/0.005 | 2.67 | drift | ore_hardness_est | 9.75 | True | 68.8 | spe | True | True | 1.0000 |
| 29017 | 4 | 0.007/0.004 | 2.67 | freeze | hpgr_press | 15.58 | False | - | - | - | True | 1.0000 |
| 29018 | 5 | 0.008/0.016 | 5.33 | spike | mill_feed | 15.95 | False | - | - | - | True | 1.0000 |
| 29019 | 4 | 0.002/0.004 | 2.00 | bad_quality | cyc_water | 11.60 | False | - | - | - | True | 0.9583 |
| 29020 | 4 | 0.008/0.008 | 1.33 | dropout | feed_moisture | 12.39 | False | - | - | - | True | 0.9576 |
| 29021 | 5 | 0.016/0.008 | 4.00 | drift | p80 | 11.57 | True | 35.5 | spe | True | True | 1.0000 |
| 29022 | 4 | 0.008/0.013 | 4.00 | freeze | mill_power | 9.64 | False | - | - | - | True | 1.0000 |
| 29023 | 5 | 0.026/0.008 | 2.67 | spike | hpgr_power | 11.48 | False | - | - | - | True | 1.0000 |
| 29024 | 4 | 0.005/0.009 | 3.33 | bad_quality | ore_hardness_est | 13.49 | False | - | - | - | True | 0.9576 |
| 29025 | 5 | 0.015/0.009 | 3.00 | dropout | hpgr_press | 7.66 | False | - | - | - | True | 0.9576 |
| 29026 | 4 | 0.003/0.009 | 3.33 | drift | mill_feed | 8.17 | True | 138.9 | spe | True | True | 1.0000 |
| 29027 | 4 | 0.005/0.008 | 1.67 | freeze | cyc_water | 11.48 | False | - | - | - | True | 1.0000 |
| 29028 | 4 | 0.008/0.014 | 1.33 | spike | feed_moisture | 12.34 | False | - | - | - | True | 1.0000 |
| 29029 | 4 | 0.005/0.009 | 2.67 | bad_quality | p80 | 9.59 | False | - | - | - | True | 0.9576 |
| 29030 | 5 | 0.010/0.008 | 2.67 | dropout | mill_power | 10.75 | False | - | - | - | True | 0.9576 |
| 29031 | 5 | 0.010/0.009 | 3.67 | drift | hpgr_power | 11.54 | True | 115.4 | spe | True | True | 1.0000 |
| 29032 | 4 | 0.001/0.017 | 1.00 | freeze | ore_hardness_est | 8.20 | False | - | - | - | True | 1.0000 |
| 29033 | 4 | 0.006/0.012 | 1.33 | spike | hpgr_press | 6.93 | False | - | - | - | True | 1.0000 |
| 29034 | 4 | 0.004/0.004 | 0.33 | bad_quality | mill_feed | 6.43 | False | - | - | - | True | 0.9576 |
| 29035 | 4 | 0.020/0.003 | 1.00 | dropout | cyc_water | 12.73 | False | - | - | - | True | 0.9576 |
| 29036 | 5 | 0.013/0.007 | 3.67 | drift | feed_moisture | 7.89 | True | 137.2 | t2 | True | True | 1.0000 |
| 29037 | 5 | 0.005/0.009 | 6.00 | freeze | p80 | 13.46 | False | - | - | - | True | 1.0000 |
| 29038 | 5 | 0.012/0.007 | 3.00 | spike | mill_power | 11.52 | False | - | - | - | True | 1.0000 |
| 29039 | 5 | 0.011/0.008 | 4.67 | bad_quality | hpgr_power | 13.21 | False | - | - | - | True | 0.9576 |
| 29040 | 4 | 0.007/0.003 | 2.33 | dropout | ore_hardness_est | 8.25 | False | - | - | - | True | 0.9576 |
| 29041 | 5 | 0.008/0.011 | 3.33 | drift | hpgr_press | 6.24 | True | 138.7 | spe | True | True | 1.0000 |
| 29042 | 4 | 0.007/0.007 | 2.00 | freeze | mill_feed | 12.21 | False | - | - | - | True | 1.0000 |
| 29043 | 5 | 0.008/0.005 | 1.67 | spike | cyc_water | 7.98 | False | - | - | - | True | 1.0000 |
| 29044 | 5 | 0.007/0.008 | 1.67 | bad_quality | feed_moisture | 14.30 | False | - | - | - | True | 0.9576 |
| 29045 | 5 | 0.019/0.006 | 3.00 | dropout | p80 | 9.58 | False | - | - | - | True | 0.9576 |
| 29046 | 4 | 0.018/0.002 | 1.67 | drift | mill_power | 12.83 | True | 75.8 | spe | False | True | 1.0000 |
| 29047 | 5 | 0.007/0.012 | 3.00 | freeze | hpgr_power | 10.79 | True | 51.4 | spe | True | True | 1.0000 |
| 29048 | 4 | 0.004/0.005 | 1.67 | spike | ore_hardness_est | 6.23 | False | - | - | - | True | 1.0000 |
| 29049 | 4 | 0.013/0.007 | 2.33 | bad_quality | hpgr_press | 13.19 | False | - | - | - | True | 0.9576 |
| 29050 | 4 | 0.002/0.004 | 2.33 | dropout | mill_feed | 7.99 | False | - | - | - | True | 0.9576 |
| 29051 | 4 | 0.008/0.007 | 3.33 | drift | cyc_water | 10.27 | False | - | - | - | True | 1.0000 |
| 29052 | 4 | 0.008/0.011 | 0.33 | freeze | feed_moisture | 10.32 | False | - | - | - | True | 1.0000 |
| 29053 | 4 | 0.009/0.008 | 2.00 | spike | p80 | 9.57 | False | - | - | - | True | 1.0000 |
| 29054 | 5 | 0.005/0.003 | 4.00 | bad_quality | mill_power | 12.44 | False | - | - | - | True | 0.9576 |
| 29055 | 5 | 0.004/0.012 | 3.67 | dropout | hpgr_power | 13.18 | False | - | - | - | True | 0.9583 |
| 29056 | 5 | 0.010/0.006 | 3.00 | drift | ore_hardness_est | 8.70 | True | 111.7 | spe | True | True | 1.0000 |
| 29057 | 5 | 0.009/0.007 | 3.33 | freeze | hpgr_press | 13.89 | False | - | - | - | True | 1.0000 |
| 29058 | 4 | 0.012/0.007 | 2.33 | spike | mill_feed | 12.18 | False | - | - | - | True | 1.0000 |
| 29059 | 5 | 0.001/0.011 | 0.67 | bad_quality | cyc_water | 14.78 | False | - | - | - | True | 0.9576 |
| 29060 | 4 | 0.015/0.004 | 1.00 | dropout | feed_moisture | 12.81 | False | - | - | - | True | 0.9576 |
