# exp29 results (round 3): test seeds

Seeds: 159; runtime 444 s. Test seeds, run once.

## Criteria

| id | values | verdict |
| --- | --- | --- |
| B1 | false alarm events (any rule) per 24 h on 60 quiet records: mean 0.356 (pca 0.356), max 1.667 | PASS |
| B2 | drift detected 16/20 (0.800); by pca 16, by stuck 0 | PASS |
| B3 | freeze detected 18/20 (0.900); by pca 2, by stuck 18 | PASS |
| B4 | faulty tag in top 2 (stuck: named) 1.000 of 34 detected (18 by the stuck rule); SPE 0.941, T2 0.941 | PASS |
| B5 | removed-rows property 39/39 bad_quality+dropout records (other kinds 60/60) | PASS |
| B6 | stuck events per 24 h on 60 quiet records: mean 0.000, max 0.000, records with any 0 | PASS |

## Reported (no target)

| kind | records | rate (any) | median delay [min] | pca rate | pca delay | stuck rate | stuck delay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| drift | 20 | 0.800 | 131.9 | 0.800 | 131.9 | 0.000 | - |
| freeze | 20 | 0.900 | 1.5 | 0.100 | 27.1 | 0.900 | 1.5 |
| spike | 20 | 0.050 | 36.5 | 0.050 | 36.5 | 0.000 | - |
| bad_quality | 20 | 0.000 | - | 0.000 | - | 0.000 | - |
| dropout | 19 | 0.000 | - | 0.000 | - | 0.000 | - |

- training-record exceedance (expected near 1 - alpha = 0.001): T2 0.0010, SPE 0.0007 (mean over seeds)
- valid-row share: quiet 0.9995, fault 0.9814
- events starting before the fault onset on fault records: 13
- model rank k values seen: [4, 5]
- quiet records, events per 24 h by rule: pca 0.356, stuck 0.000
- valid rows lost to the lag history: total 396, mean 2.49 and max 4 per scanned record
- SPE limit method (seeds): {'empirical': 159}
- longest constant training run per tag, max over seeds (hpgr_press, mill_feed, cyc_water, feed_moisture, p80, mill_power, hpgr_power, ore_hardness_est): [1, 1, 1, 1, 1, 1, 1, 29]

## Per seed

| seed | k | SPE limit | train exc T2/SPE | quiet ev/24h pca/stuck | kind | tag | onset [h] | detected | delay [min] | rule | top2 hit | pca/stuck hit | B5 | valid share |
| ---: | ---: | --- | --- | --- | --- | --- | ---: | --- | ---: | --- | --- | --- | --- | ---: |
| 33001 | 5 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33002 | 5 | empirical | 0.000/0.001 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33003 | 5 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33004 | 5 | empirical | 0.002/0.001 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33005 | 5 | empirical | 0.001/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33006 | 4 | empirical | 0.007/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33007 | 5 | empirical | 0.006/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33008 | 5 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33009 | 5 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33010 | 5 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33011 | 4 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33012 | 4 | empirical | 0.004/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33013 | 5 | empirical | 0.001/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33014 | 5 | empirical | 0.007/0.001 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33015 | 4 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33016 | 4 | empirical | 0.001/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33017 | 5 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33018 | 4 | empirical | 0.001/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33019 | 5 | empirical | 0.004/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33020 | 5 | empirical | 0.000/0.001 | 0.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33021 | 5 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33022 | 5 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33023 | 5 | empirical | 0.001/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33024 | 5 | empirical | 0.000/0.001 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33025 | 4 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33026 | 5 | empirical | 0.002/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33027 | 5 | empirical | 0.000/0.001 | 0.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33028 | 5 | empirical | 0.001/0.001 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33029 | 4 | empirical | 0.004/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33030 | 5 | empirical | 0.001/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33031 | 5 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33032 | 4 | empirical | 0.000/0.001 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33033 | 5 | empirical | 0.001/0.001 | 0.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33034 | 4 | empirical | 0.008/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33035 | 5 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33036 | 5 | empirical | 0.001/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33037 | 5 | empirical | 0.002/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33038 | 4 | empirical | 0.000/0.001 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33039 | 4 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33040 | 5 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33041 | 5 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33042 | 5 | empirical | 0.001/0.001 | 0.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33043 | 4 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33044 | 5 | empirical | 0.003/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33045 | 5 | empirical | 0.001/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33046 | 5 | empirical | 0.000/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33047 | 4 | empirical | 0.006/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33048 | 5 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33049 | 4 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33050 | 5 | empirical | 0.001/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33051 | 5 | empirical | 0.001/0.001 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33052 | 5 | empirical | 0.000/0.001 | 0.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33053 | 5 | empirical | 0.000/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33054 | 4 | empirical | 0.001/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33055 | 4 | empirical | 0.003/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33056 | 5 | empirical | 0.002/0.001 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33057 | 4 | empirical | 0.001/0.001 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33058 | 5 | empirical | 0.001/0.001 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33059 | 5 | empirical | 0.002/0.001 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33060 | 5 | empirical | 0.002/0.001 | 0.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 33101 | 5 | empirical | 0.001/0.001 | - | drift | hpgr_press | 7.67 | True | 168.7 | pca | True | True/False | True | 0.9986 |
| 33102 | 5 | empirical | 0.000/0.001 | - | freeze | mill_feed | 6.54 | True | 1.4 | stuck | True | False/True | True | 0.9986 |
| 33103 | 5 | empirical | 0.000/0.001 | - | spike | cyc_water | 15.74 | False | - | - | - | False/False | True | 0.9986 |
| 33104 | 5 | empirical | 0.000/0.001 | - | bad_quality | feed_moisture | 10.05 | False | - | - | - | False/False | True | 0.9549 |
| 33105 | 5 | empirical | 0.001/0.001 | - | dropout | p80 | 11.25 | False | - | - | - | False/False | True | 0.9556 |
| 33106 | 5 | empirical | 0.000/0.001 | - | drift | mill_power | 6.61 | True | 133.2 | pca | True | True/False | True | 0.9986 |
| 33107 | 4 | empirical | 0.000/0.001 | - | freeze | hpgr_power | 6.30 | True | 1.8 | stuck | True | False/True | True | 0.9986 |
| 33108 | 5 | empirical | 0.000/0.001 | - | spike | ore_hardness_est | 12.85 | False | - | - | - | False/False | True | 0.9986 |
| 33109 | 5 | empirical | 0.001/0.001 | - | bad_quality | hpgr_press | 11.82 | False | - | - | - | False/False | True | 0.9549 |
| 33110 | 5 | empirical | 0.005/0.001 | - | dropout | mill_feed | 14.64 | False | - | - | - | False/False | True | 0.9549 |
| 33111 | 5 | empirical | 0.000/0.001 | - | drift | cyc_water | 13.64 | False | - | - | - | False/False | True | 0.9986 |
| 33112 | 4 | empirical | 0.000/0.001 | - | freeze | feed_moisture | 13.60 | True | 1.6 | stuck | True | False/True | True | 0.9986 |
| 33113 | 5 | empirical | 0.002/0.001 | - | spike | p80 | 12.96 | False | - | - | - | False/False | True | 0.9986 |
| 33114 | 4 | empirical | 0.001/0.001 | - | bad_quality | mill_power | 10.42 | False | - | - | - | False/False | True | 0.9549 |
| 33115 | 4 | empirical | 0.000/0.001 | - | dropout | hpgr_power | 15.58 | False | - | - | - | False/False | True | 0.9556 |
| 33116 | 5 | empirical | 0.000/0.001 | - | drift | ore_hardness_est | 15.20 | True | 78.8 | pca | True | True/False | True | 0.9986 |
| 33117 | 5 | empirical | 0.000/0.001 | - | freeze | hpgr_press | 6.83 | True | 1.8 | stuck | True | False/True | True | 0.9986 |
| 33118 | 5 | empirical | 0.000/0.001 | - | spike | mill_feed | 9.66 | False | - | - | - | False/False | True | 0.9986 |
| 33119 | 5 | empirical | 0.001/0.001 | - | bad_quality | cyc_water | 9.32 | False | - | - | - | False/False | True | 0.9549 |
| 33120 | 5 | empirical | 0.000/0.001 | - | dropout | feed_moisture | 12.96 | False | - | - | - | False/False | True | 0.9549 |
| 33121 | 4 | empirical | 0.001/0.001 | - | drift | p80 | 8.35 | True | 175.6 | pca | True | True/False | True | 0.9986 |
| 33122 | 4 | empirical | 0.000/0.001 | - | freeze | mill_power | 11.64 | True | 1.3 | stuck | True | False/True | True | 0.9986 |
| 33123 | 5 | empirical | 0.000/0.001 | - | spike | hpgr_power | 12.93 | False | - | - | - | False/False | True | 0.9986 |
| 33124 | 4 | empirical | 0.000/0.001 | - | bad_quality | ore_hardness_est | 12.14 | False | - | - | - | False/False | True | 0.9549 |
| 33125 | 4 | empirical | 0.000/0.001 | - | dropout | hpgr_press | 11.04 | False | - | - | - | False/False | True | 0.9549 |
| 33126 | 4 | empirical | 0.000/0.001 | - | drift | mill_feed | 7.63 | True | 148.9 | pca | True | True/False | True | 0.9986 |
| 33127 | 4 | empirical | 0.000/0.001 | - | freeze | cyc_water | 12.25 | True | 1.8 | stuck | True | False/True | True | 0.9986 |
| 33128 | 5 | empirical | 0.000/0.001 | - | spike | feed_moisture | 14.84 | False | - | - | - | False/False | True | 0.9986 |
| 33129 | 5 | empirical | 0.000/0.001 | - | bad_quality | p80 | 12.50 | False | - | - | - | False/False | True | 0.9549 |
| 33130 | 5 | empirical | 0.002/0.001 | - | dropout | mill_power | 7.34 | False | - | - | - | False/False | True | 0.9549 |
| 33131 | 4 | empirical | 0.000/0.001 | - | drift | hpgr_power | 6.14 | True | 136.4 | pca | True | True/False | True | 0.9986 |
| 33132 | 5 | empirical | 0.000/0.001 | - | freeze | ore_hardness_est | 7.59 | False | - | - | - | False/False | True | 0.9986 |
| 33133 | 4 | empirical | 0.003/0.001 | - | spike | hpgr_press | 14.23 | False | - | - | - | False/False | True | 0.9986 |
| 33134 | 5 | empirical | 0.000/0.001 | - | bad_quality | mill_feed | 14.04 | False | - | - | - | False/False | True | 0.9549 |
| 33135 | 5 | empirical | 0.000/0.001 | - | dropout | cyc_water | 6.27 | False | - | - | - | False/False | True | 0.9549 |
| 33136 | 5 | empirical | 0.000/0.001 | - | drift | feed_moisture | 13.88 | False | - | - | - | False/False | True | 0.9986 |
| 33137 | 4 | empirical | 0.000/0.001 | - | freeze | p80 | 10.28 | True | 1.2 | stuck | True | True/True | True | 0.9986 |
| 33138 | 4 | empirical | 0.000/0.001 | - | spike | mill_power | 10.02 | False | - | - | - | False/False | True | 0.9986 |
| 33139 | 5 | empirical | 0.000/0.001 | - | bad_quality | hpgr_power | 8.96 | False | - | - | - | False/False | True | 0.9549 |
| 33140 | 4 | empirical | 0.001/0.001 | - | dropout | ore_hardness_est | 8.68 | False | - | - | - | False/False | True | 0.9549 |
| 33141 | 4 | empirical | 0.000/0.001 | - | drift | hpgr_press | 6.12 | True | 107.9 | pca | True | True/False | True | 0.9986 |
| 33142 | 5 | empirical | 0.000/0.001 | - | freeze | mill_feed | 9.10 | True | 1.6 | stuck | True | False/True | True | 0.9986 |
| 33143 | 4 | empirical | 0.000/0.001 | - | spike | cyc_water | 15.37 | True | 36.5 | pca | False | True/False | True | 0.9986 |
| 33144 | 4 | empirical | 0.000/0.001 | - | bad_quality | feed_moisture | 8.69 | False | - | - | - | False/False | True | 0.9549 |
| 33145 | 4 | empirical | 0.000/0.001 | - | dropout | p80 | 12.20 | False | - | - | - | False/False | True | 0.9549 |
| 33146 | 5 | empirical | 0.000/0.001 | - | drift | mill_power | 11.30 | True | 171.9 | pca | True | True/False | True | 0.9986 |
| 33147 | 4 | empirical | 0.000/0.001 | - | freeze | hpgr_power | 11.11 | True | 1.0 | stuck | True | False/True | True | 0.9986 |
| 33148 | 5 | empirical | 0.000/0.001 | - | spike | ore_hardness_est | 12.62 | False | - | - | - | False/False | True | 0.9986 |
| 33149 | 5 | empirical | 0.001/0.001 | - | bad_quality | hpgr_press | 7.57 | False | - | - | - | False/False | True | 0.9549 |
| 33150 | 4 | empirical | 0.001/0.001 | - | dropout | mill_feed | 8.25 | False | - | - | - | False/False | True | 0.9556 |
| 33151 | 5 | empirical | 0.000/0.001 | - | drift | cyc_water | 7.71 | True | 171.1 | pca | True | True/False | True | 0.9986 |
| 33152 | 5 | empirical | 0.001/0.001 | - | freeze | feed_moisture | 9.72 | True | 1.6 | stuck | True | False/True | True | 0.9986 |
| 33153 | 5 | empirical | 0.000/0.001 | - | spike | p80 | 15.04 | False | - | - | - | False/False | True | 0.9986 |
| 33154 | 5 | empirical | 0.000/0.001 | - | bad_quality | mill_power | 8.91 | False | - | - | - | False/False | True | 0.9549 |
| 33155 | 4 | empirical | 0.002/0.001 | - | dropout | hpgr_power | 8.39 | False | - | - | - | False/False | True | 0.9549 |
| 33156 | 5 | empirical | 0.000/0.001 | - | drift | ore_hardness_est | 10.71 | True | 90.1 | pca | True | True/False | True | 0.9986 |
| 33157 | 4 | empirical | 0.000/0.001 | - | freeze | hpgr_press | 8.12 | True | 1.4 | stuck | True | False/True | True | 0.9986 |
| 33158 | 5 | empirical | 0.000/0.001 | - | spike | mill_feed | 14.55 | False | - | - | - | False/False | True | 0.9986 |
| 33159 | 4 | empirical | 0.000/0.001 | - | bad_quality | cyc_water | 6.72 | False | - | - | - | False/False | True | 0.9549 |
| 33160 | 5 | empirical | 0.000/0.001 | - | dropout | feed_moisture | 10.31 | False | - | - | - | False/False | True | 0.9556 |
| 33161 | 5 | empirical | 0.000/0.001 | - | drift | p80 | 6.19 | False | - | - | - | False/False | True | 0.9986 |
| 33162 | 4 | empirical | 0.000/0.001 | - | freeze | mill_power | 14.90 | True | 1.1 | stuck | True | False/True | True | 0.9986 |
| 33163 | 5 | empirical | 0.000/0.001 | - | spike | hpgr_power | 12.55 | False | - | - | - | False/False | True | 0.9986 |
| 33164 | 5 | empirical | 0.000/0.001 | - | bad_quality | ore_hardness_est | 8.85 | False | - | - | - | False/False | True | 0.9556 |
| 33165 | 4 | empirical | 0.000/0.001 | - | dropout | hpgr_press | 8.35 | False | - | - | - | False/False | True | 0.9549 |
| 33166 | 4 | empirical | 0.000/0.001 | - | drift | mill_feed | 13.67 | True | 118.4 | pca | True | True/False | True | 0.9986 |
| 33167 | 4 | empirical | 0.010/0.001 | - | freeze | cyc_water | 10.48 | True | 0.9 | stuck | True | False/True | True | 0.9986 |
| 33168 | 5 | empirical | 0.000/0.001 | - | spike | feed_moisture | 13.72 | False | - | - | - | False/False | True | 0.9986 |
| 33169 | 5 | empirical | 0.001/0.001 | - | bad_quality | p80 | 14.68 | False | - | - | - | False/False | True | 0.9556 |
| 33170 | 5 | empirical | 0.000/0.001 | - | dropout | mill_power | 10.65 | False | - | - | - | False/False | True | 0.9549 |
| 33171 | 5 | empirical | 0.003/0.001 | - | drift | hpgr_power | 8.61 | True | 108.0 | pca | True | True/False | True | 0.9986 |
| 33172 | 5 | empirical | 0.007/0.001 | - | freeze | ore_hardness_est | 13.45 | False | - | - | - | False/False | True | 0.9986 |
| 33173 | 5 | empirical | 0.000/0.001 | - | spike | hpgr_press | 14.10 | False | - | - | - | False/False | True | 0.9986 |
| 33174 | 4 | empirical | 0.000/0.001 | - | bad_quality | mill_feed | 13.86 | False | - | - | - | False/False | True | 0.9549 |
| 33175 | 5 | empirical | 0.011/0.001 | - | dropout | cyc_water | 8.84 | False | - | - | - | False/False | True | 0.9549 |
| 33176 | 4 | empirical | 0.001/0.001 | - | drift | feed_moisture | 10.81 | False | - | - | - | False/False | True | 0.9986 |
| 33177 | 5 | empirical | 0.001/0.001 | - | freeze | p80 | 9.55 | True | 1.1 | stuck | True | True/True | True | 0.9986 |
| 33178 | 5 | empirical | 0.000/0.001 | - | spike | mill_power | 12.14 | False | - | - | - | False/False | True | 0.9986 |
| 33179 | 5 | empirical | 0.001/0.001 | - | bad_quality | hpgr_power | 12.52 | False | - | - | - | False/False | True | 0.9549 |
| 33180 | 5 | empirical | 0.000/0.001 | - | dropout | ore_hardness_est | 8.85 | False | - | - | - | False/False | True | 0.9549 |
| 33181 | 5 | empirical | 0.001/0.001 | - | drift | hpgr_press | 13.29 | True | 129.2 | pca | True | True/False | True | 0.9986 |
| 33182 | 5 | empirical | 0.000/0.001 | - | freeze | mill_feed | 7.45 | True | 1.6 | stuck | True | False/True | True | 0.9986 |
| 33183 | 5 | empirical | 0.000/0.001 | - | spike | cyc_water | 12.21 | False | - | - | - | False/False | True | 0.9986 |
| 33184 | 5 | empirical | 0.001/0.001 | - | bad_quality | feed_moisture | 7.48 | False | - | - | - | False/False | True | 0.9549 |
| 33185 | 4 | empirical | 0.000/0.001 | - | dropout | p80 | 6.95 | False | - | - | - | False/False | True | 0.9549 |
| 33186 | 5 | empirical | 0.000/0.001 | - | drift | mill_power | 9.18 | True | 137.8 | pca | True | True/False | True | 0.9986 |
| 33187 | 5 | empirical | 0.001/0.001 | - | freeze | hpgr_power | 14.27 | True | 1.8 | stuck | True | False/True | True | 0.9986 |
| 33188 | 5 | empirical | 0.001/0.001 | - | spike | ore_hardness_est | 13.91 | False | - | - | - | False/False | True | 0.9986 |
| 33189 | 5 | empirical | 0.008/0.001 | - | bad_quality | hpgr_press | 11.57 | False | - | - | - | False/False | True | 0.9549 |
| 33190 | 5 | empirical | 0.000/0.001 | - | dropout | mill_feed | 7.13 | False | - | - | - | False/False | True | 0.9556 |
| 33191 | 5 | empirical | 0.000/0.001 | - | drift | cyc_water | 9.89 | True | 130.5 | pca | True | True/False | True | 0.9986 |
| 33192 | 4 | empirical | 0.005/0.001 | - | freeze | feed_moisture | 11.13 | True | 0.9 | stuck | True | False/True | True | 0.9986 |
| 33193 | 4 | empirical | 0.000/0.001 | - | spike | p80 | 11.80 | False | - | - | - | False/False | True | 0.9986 |
| 33194 | 5 | empirical | 0.000/0.001 | - | bad_quality | mill_power | 6.99 | False | - | - | - | False/False | True | 0.9549 |
| 33195 | 4 | empirical | 0.000/0.001 | - | dropout | hpgr_power | 11.96 | False | - | - | - | False/False | True | 0.9549 |
| 33196 | 5 | empirical | 0.002/0.001 | - | drift | ore_hardness_est | 13.12 | True | 114.7 | pca | True | True/False | True | 0.9986 |
| 33197 | 4 | empirical | 0.001/0.001 | - | freeze | hpgr_press | 13.12 | True | 1.6 | stuck | True | False/True | True | 0.9986 |
| 33198 | 4 | empirical | 0.000/0.001 | - | spike | mill_feed | 12.07 | False | - | - | - | False/False | True | 0.9986 |
| 33199 | 4 | empirical | 0.000/0.001 | - | bad_quality | cyc_water | 13.87 | False | - | - | - | False/False | True | 0.9549 |
