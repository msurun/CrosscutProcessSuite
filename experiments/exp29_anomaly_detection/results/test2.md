# exp29 results (round 2): test seeds

Seeds: 159; runtime 746 s. Test seeds, run once.

## Criteria

| id | values | verdict |
| --- | --- | --- |
| B1 | false alarm events (any rule) per 24 h on 60 quiet records: mean 1.789 (pca 1.789), max 4.333 | MISS |
| B2 | drift detected 19/20 (0.950); by pca 19, by stuck 0 | PASS |
| B3 | freeze detected 19/20 (0.950); by pca 2, by stuck 19 | PASS |
| B4 | faulty tag in top 2 (stuck: named) 0.947 of 38 detected (19 by the stuck rule); SPE 0.868, T2 0.895 | PASS |
| B5 | removed-rows property 39/39 bad_quality+dropout records (other kinds 60/60) | PASS |
| B6 | stuck events per 24 h on 60 quiet records: mean 0.000, max 0.000, records with any 0 | PASS |

## Reported (no target)

| kind | records | rate (any) | median delay [min] | pca rate | pca delay | stuck rate | stuck delay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| drift | 20 | 0.950 | 116.5 | 0.950 | 116.5 | 0.000 | - |
| freeze | 20 | 0.950 | 1.2 | 0.100 | 25.1 | 0.950 | 1.2 |
| spike | 20 | 0.050 | 8.3 | 0.050 | 8.3 | 0.000 | - |
| bad_quality | 20 | 0.000 | - | 0.000 | - | 0.000 | - |
| dropout | 19 | 0.000 | - | 0.000 | - | 0.000 | - |

- training-record exceedance (expected near 1 - alpha = 0.01): T2 0.0096, SPE 0.0097 (mean over seeds)
- valid-row share: quiet 0.9995, fault 0.9814
- events starting before the fault onset on fault records: 84
- model rank k values seen: [4, 5]
- quiet records, events per 24 h by rule: pca 1.789, stuck 0.000
- valid rows lost to the lag history: total 396, mean 2.49 and max 4 per scanned record
- SPE limit method (seeds): {'empirical': 159}
- longest constant training run per tag, max over seeds (hpgr_press, mill_feed, cyc_water, feed_moisture, p80, mill_power, hpgr_power, ore_hardness_est): [1, 1, 1, 1, 1, 1, 1, 29]

## Per seed

| seed | k | SPE limit | train exc T2/SPE | quiet ev/24h pca/stuck | kind | tag | onset [h] | detected | delay [min] | rule | top2 hit | pca/stuck hit | B5 | valid share |
| ---: | ---: | --- | --- | --- | --- | --- | ---: | --- | ---: | --- | --- | --- | --- | ---: |
| 29701 | 4 | empirical | 0.003/0.010 | 3.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29702 | 5 | empirical | 0.021/0.010 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29703 | 5 | empirical | 0.016/0.010 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29704 | 5 | empirical | 0.004/0.010 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29705 | 4 | empirical | 0.014/0.010 | 2.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29706 | 5 | empirical | 0.011/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29707 | 5 | empirical | 0.014/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29708 | 4 | empirical | 0.021/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29709 | 4 | empirical | 0.001/0.010 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29710 | 5 | empirical | 0.005/0.010 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29711 | 5 | empirical | 0.002/0.010 | 2.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29712 | 5 | empirical | 0.008/0.010 | 4.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29713 | 4 | empirical | 0.006/0.010 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29714 | 4 | empirical | 0.006/0.010 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29715 | 4 | empirical | 0.003/0.010 | 3.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29716 | 4 | empirical | 0.010/0.010 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29717 | 5 | empirical | 0.014/0.010 | 3.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29718 | 5 | empirical | 0.008/0.010 | 2.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29719 | 4 | empirical | 0.013/0.010 | 2.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29720 | 4 | empirical | 0.006/0.010 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29721 | 5 | empirical | 0.019/0.010 | 2.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29722 | 4 | empirical | 0.010/0.010 | 3.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29723 | 5 | empirical | 0.008/0.010 | 2.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29724 | 5 | empirical | 0.017/0.010 | 3.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29725 | 5 | empirical | 0.008/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29726 | 5 | empirical | 0.022/0.010 | 2.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29727 | 5 | empirical | 0.017/0.010 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29728 | 4 | empirical | 0.002/0.010 | 2.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29729 | 5 | empirical | 0.007/0.010 | 0.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29730 | 4 | empirical | 0.005/0.010 | 4.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29731 | 4 | empirical | 0.018/0.010 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29732 | 5 | empirical | 0.007/0.010 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29733 | 5 | empirical | 0.006/0.010 | 2.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29734 | 5 | empirical | 0.010/0.010 | 2.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29735 | 4 | empirical | 0.005/0.010 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29736 | 4 | empirical | 0.012/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29737 | 4 | empirical | 0.004/0.010 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29738 | 5 | empirical | 0.005/0.010 | 0.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29739 | 4 | empirical | 0.012/0.010 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29740 | 5 | empirical | 0.002/0.010 | 3.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29741 | 4 | empirical | 0.007/0.010 | 2.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29742 | 5 | empirical | 0.006/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29743 | 5 | empirical | 0.007/0.010 | 2.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29744 | 5 | empirical | 0.005/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29745 | 4 | empirical | 0.007/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29746 | 5 | empirical | 0.017/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29747 | 5 | empirical | 0.013/0.010 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29748 | 5 | empirical | 0.001/0.010 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29749 | 5 | empirical | 0.017/0.010 | 2.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29750 | 5 | empirical | 0.003/0.010 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29751 | 5 | empirical | 0.017/0.010 | 2.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29752 | 4 | empirical | 0.006/0.010 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29753 | 4 | empirical | 0.004/0.010 | 1.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29754 | 5 | empirical | 0.005/0.010 | 2.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29755 | 4 | empirical | 0.014/0.010 | 4.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29756 | 5 | empirical | 0.009/0.010 | 4.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29757 | 4 | empirical | 0.016/0.010 | 1.33/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29758 | 5 | empirical | 0.010/0.010 | 0.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29759 | 4 | empirical | 0.012/0.010 | 1.00/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29760 | 4 | empirical | 0.009/0.010 | 0.67/0.00 | - | - | - | - | - | - | - | - | - | - |
| 29801 | 4 | empirical | 0.000/0.010 | - | drift | hpgr_press | 7.36 | True | 116.5 | pca | True | True/False | True | 0.9986 |
| 29802 | 4 | empirical | 0.006/0.010 | - | freeze | mill_feed | 7.86 | True | 1.2 | stuck | True | True/True | True | 0.9986 |
| 29803 | 5 | empirical | 0.002/0.010 | - | spike | cyc_water | 9.79 | False | - | - | - | False/False | True | 0.9986 |
| 29804 | 4 | empirical | 0.008/0.010 | - | bad_quality | feed_moisture | 7.83 | False | - | - | - | False/False | True | 0.9549 |
| 29805 | 4 | empirical | 0.015/0.010 | - | dropout | p80 | 7.05 | False | - | - | - | False/False | True | 0.9549 |
| 29806 | 4 | empirical | 0.008/0.010 | - | drift | mill_power | 10.46 | True | 119.2 | pca | True | True/False | True | 0.9986 |
| 29807 | 5 | empirical | 0.005/0.010 | - | freeze | hpgr_power | 14.58 | True | 1.1 | stuck | True | False/True | True | 0.9986 |
| 29808 | 4 | empirical | 0.017/0.010 | - | spike | ore_hardness_est | 10.92 | False | - | - | - | False/False | True | 0.9986 |
| 29809 | 5 | empirical | 0.015/0.010 | - | bad_quality | hpgr_press | 10.23 | False | - | - | - | False/False | True | 0.9549 |
| 29810 | 4 | empirical | 0.002/0.010 | - | dropout | mill_feed | 7.82 | False | - | - | - | False/False | True | 0.9549 |
| 29811 | 5 | empirical | 0.007/0.010 | - | drift | cyc_water | 12.68 | True | 172.8 | pca | True | True/False | True | 0.9986 |
| 29812 | 5 | empirical | 0.011/0.010 | - | freeze | feed_moisture | 15.80 | True | 1.7 | stuck | True | False/True | True | 0.9986 |
| 29813 | 5 | empirical | 0.007/0.010 | - | spike | p80 | 6.90 | False | - | - | - | False/False | True | 0.9986 |
| 29814 | 5 | empirical | 0.001/0.010 | - | bad_quality | mill_power | 12.74 | False | - | - | - | False/False | True | 0.9549 |
| 29815 | 5 | empirical | 0.005/0.010 | - | dropout | hpgr_power | 7.80 | False | - | - | - | False/False | True | 0.9549 |
| 29816 | 5 | empirical | 0.008/0.010 | - | drift | ore_hardness_est | 6.75 | True | 83.5 | pca | True | True/False | True | 0.9986 |
| 29817 | 4 | empirical | 0.001/0.010 | - | freeze | hpgr_press | 13.99 | True | 1.2 | stuck | True | False/True | True | 0.9986 |
| 29818 | 4 | empirical | 0.010/0.010 | - | spike | mill_feed | 11.67 | False | - | - | - | False/False | True | 0.9986 |
| 29819 | 4 | empirical | 0.003/0.010 | - | bad_quality | cyc_water | 15.79 | False | - | - | - | False/False | True | 0.9549 |
| 29820 | 5 | empirical | 0.011/0.010 | - | dropout | feed_moisture | 14.85 | False | - | - | - | False/False | True | 0.9556 |
| 29821 | 5 | empirical | 0.005/0.010 | - | drift | p80 | 10.61 | True | 127.0 | pca | True | True/False | True | 0.9986 |
| 29822 | 5 | empirical | 0.014/0.010 | - | freeze | mill_power | 7.92 | True | 0.9 | stuck | True | False/True | True | 0.9986 |
| 29823 | 4 | empirical | 0.015/0.010 | - | spike | hpgr_power | 12.71 | False | - | - | - | False/False | True | 0.9986 |
| 29824 | 5 | empirical | 0.004/0.010 | - | bad_quality | ore_hardness_est | 14.00 | False | - | - | - | False/False | True | 0.9549 |
| 29825 | 5 | empirical | 0.011/0.010 | - | dropout | hpgr_press | 7.38 | False | - | - | - | False/False | True | 0.9556 |
| 29826 | 5 | empirical | 0.001/0.010 | - | drift | mill_feed | 15.89 | True | 104.7 | pca | True | True/False | True | 0.9986 |
| 29827 | 5 | empirical | 0.017/0.010 | - | freeze | cyc_water | 11.92 | True | 1.6 | stuck | True | False/True | True | 0.9986 |
| 29828 | 5 | empirical | 0.002/0.010 | - | spike | feed_moisture | 7.11 | False | - | - | - | False/False | True | 0.9986 |
| 29829 | 5 | empirical | 0.008/0.010 | - | bad_quality | p80 | 10.63 | False | - | - | - | False/False | True | 0.9549 |
| 29830 | 4 | empirical | 0.017/0.010 | - | dropout | mill_power | 15.30 | False | - | - | - | False/False | True | 0.9549 |
| 29831 | 5 | empirical | 0.010/0.010 | - | drift | hpgr_power | 6.47 | True | 67.5 | pca | True | True/False | True | 0.9986 |
| 29832 | 5 | empirical | 0.012/0.010 | - | freeze | ore_hardness_est | 7.51 | True | 1.1 | stuck | True | False/True | True | 0.9986 |
| 29833 | 4 | empirical | 0.008/0.010 | - | spike | hpgr_press | 13.93 | False | - | - | - | False/False | True | 0.9986 |
| 29834 | 5 | empirical | 0.004/0.010 | - | bad_quality | mill_feed | 6.05 | False | - | - | - | False/False | True | 0.9549 |
| 29835 | 5 | empirical | 0.008/0.010 | - | dropout | cyc_water | 11.96 | False | - | - | - | False/False | True | 0.9549 |
| 29836 | 5 | empirical | 0.008/0.010 | - | drift | feed_moisture | 8.53 | True | 162.9 | pca | True | True/False | True | 0.9986 |
| 29837 | 5 | empirical | 0.008/0.010 | - | freeze | p80 | 14.34 | True | 1.3 | stuck | True | False/True | True | 0.9986 |
| 29838 | 4 | empirical | 0.013/0.010 | - | spike | mill_power | 12.09 | True | 8.3 | pca | True | True/False | True | 0.9986 |
| 29839 | 4 | empirical | 0.025/0.010 | - | bad_quality | hpgr_power | 13.75 | False | - | - | - | False/False | True | 0.9549 |
| 29840 | 5 | empirical | 0.016/0.010 | - | dropout | ore_hardness_est | 8.74 | False | - | - | - | False/False | True | 0.9549 |
| 29841 | 5 | empirical | 0.008/0.010 | - | drift | hpgr_press | 9.20 | True | 119.9 | pca | True | True/False | True | 0.9986 |
| 29842 | 5 | empirical | 0.003/0.010 | - | freeze | mill_feed | 11.28 | True | 1.1 | stuck | True | False/True | True | 0.9986 |
| 29843 | 5 | empirical | 0.017/0.010 | - | spike | cyc_water | 11.17 | False | - | - | - | False/False | True | 0.9986 |
| 29844 | 5 | empirical | 0.003/0.010 | - | bad_quality | feed_moisture | 9.52 | False | - | - | - | False/False | True | 0.9549 |
| 29845 | 4 | empirical | 0.010/0.010 | - | dropout | p80 | 12.25 | False | - | - | - | False/False | True | 0.9549 |
| 29846 | 5 | empirical | 0.008/0.010 | - | drift | mill_power | 14.28 | True | 108.8 | pca | True | True/False | True | 0.9986 |
| 29847 | 4 | empirical | 0.004/0.010 | - | freeze | hpgr_power | 8.31 | True | 1.4 | stuck | True | False/True | True | 0.9986 |
| 29848 | 4 | empirical | 0.007/0.010 | - | spike | ore_hardness_est | 7.79 | False | - | - | - | False/False | True | 0.9986 |
| 29849 | 5 | empirical | 0.016/0.010 | - | bad_quality | hpgr_press | 14.94 | False | - | - | - | False/False | True | 0.9549 |
| 29850 | 4 | empirical | 0.019/0.010 | - | dropout | mill_feed | 14.54 | False | - | - | - | False/False | True | 0.9549 |
| 29851 | 4 | empirical | 0.012/0.010 | - | drift | cyc_water | 14.45 | False | - | - | - | False/False | True | 0.9986 |
| 29852 | 5 | empirical | 0.004/0.010 | - | freeze | feed_moisture | 15.53 | True | 1.1 | stuck | True | False/True | True | 0.9986 |
| 29853 | 4 | empirical | 0.011/0.010 | - | spike | p80 | 14.71 | False | - | - | - | False/False | True | 0.9986 |
| 29854 | 5 | empirical | 0.011/0.010 | - | bad_quality | mill_power | 11.51 | False | - | - | - | False/False | True | 0.9556 |
| 29855 | 5 | empirical | 0.010/0.010 | - | dropout | hpgr_power | 15.46 | False | - | - | - | False/False | True | 0.9549 |
| 29856 | 5 | empirical | 0.007/0.010 | - | drift | ore_hardness_est | 11.03 | True | 94.1 | pca | True | True/False | True | 0.9986 |
| 29857 | 5 | empirical | 0.008/0.010 | - | freeze | hpgr_press | 6.68 | True | 1.3 | stuck | True | False/True | True | 0.9986 |
| 29858 | 5 | empirical | 0.008/0.010 | - | spike | mill_feed | 12.62 | False | - | - | - | False/False | True | 0.9986 |
| 29859 | 4 | empirical | 0.018/0.010 | - | bad_quality | cyc_water | 15.99 | False | - | - | - | False/False | True | 0.9549 |
| 29860 | 5 | empirical | 0.008/0.010 | - | dropout | feed_moisture | 9.92 | False | - | - | - | False/False | True | 0.9549 |
| 29861 | 5 | empirical | 0.004/0.010 | - | drift | p80 | 7.46 | True | 113.1 | pca | True | True/False | True | 0.9986 |
| 29862 | 4 | empirical | 0.003/0.010 | - | freeze | mill_power | 14.40 | True | 0.9 | stuck | True | False/True | True | 0.9986 |
| 29863 | 4 | empirical | 0.006/0.010 | - | spike | hpgr_power | 7.52 | False | - | - | - | False/False | True | 0.9986 |
| 29864 | 5 | empirical | 0.007/0.010 | - | bad_quality | ore_hardness_est | 11.64 | False | - | - | - | False/False | True | 0.9549 |
| 29865 | 5 | empirical | 0.014/0.010 | - | dropout | hpgr_press | 6.90 | False | - | - | - | False/False | True | 0.9556 |
| 29866 | 5 | empirical | 0.008/0.010 | - | drift | mill_feed | 13.80 | True | 33.5 | pca | False | True/False | True | 0.9986 |
| 29867 | 5 | empirical | 0.012/0.010 | - | freeze | cyc_water | 9.74 | True | 1.5 | stuck | True | False/True | True | 0.9986 |
| 29868 | 5 | empirical | 0.005/0.010 | - | spike | feed_moisture | 8.06 | False | - | - | - | False/False | True | 0.9986 |
| 29869 | 5 | empirical | 0.012/0.010 | - | bad_quality | p80 | 10.85 | False | - | - | - | False/False | True | 0.9556 |
| 29870 | 5 | empirical | 0.014/0.010 | - | dropout | mill_power | 9.71 | False | - | - | - | False/False | True | 0.9549 |
| 29871 | 5 | empirical | 0.007/0.010 | - | drift | hpgr_power | 10.60 | True | 145.8 | pca | True | True/False | True | 0.9986 |
| 29872 | 4 | empirical | 0.008/0.010 | - | freeze | ore_hardness_est | 6.23 | False | - | - | - | False/False | True | 0.9986 |
| 29873 | 4 | empirical | 0.008/0.010 | - | spike | hpgr_press | 14.40 | False | - | - | - | False/False | True | 0.9986 |
| 29874 | 5 | empirical | 0.009/0.010 | - | bad_quality | mill_feed | 11.13 | False | - | - | - | False/False | True | 0.9549 |
| 29875 | 5 | empirical | 0.003/0.010 | - | dropout | cyc_water | 8.42 | False | - | - | - | False/False | True | 0.9549 |
| 29876 | 5 | empirical | 0.017/0.010 | - | drift | feed_moisture | 7.51 | True | 78.1 | pca | True | True/False | True | 0.9986 |
| 29877 | 5 | empirical | 0.011/0.010 | - | freeze | p80 | 15.23 | True | 1.0 | stuck | True | True/True | True | 0.9986 |
| 29878 | 5 | empirical | 0.007/0.010 | - | spike | mill_power | 13.86 | False | - | - | - | False/False | True | 0.9986 |
| 29879 | 5 | empirical | 0.009/0.010 | - | bad_quality | hpgr_power | 15.10 | False | - | - | - | False/False | True | 0.9549 |
| 29880 | 5 | empirical | 0.007/0.010 | - | dropout | ore_hardness_est | 7.02 | False | - | - | - | False/False | True | 0.9549 |
| 29881 | 5 | empirical | 0.006/0.010 | - | drift | hpgr_press | 10.59 | True | 128.2 | pca | True | True/False | True | 0.9986 |
| 29882 | 4 | empirical | 0.014/0.010 | - | freeze | mill_feed | 12.48 | True | 0.9 | stuck | True | False/True | True | 0.9986 |
| 29883 | 5 | empirical | 0.017/0.010 | - | spike | cyc_water | 13.38 | False | - | - | - | False/False | True | 0.9986 |
| 29884 | 4 | empirical | 0.033/0.010 | - | bad_quality | feed_moisture | 15.66 | False | - | - | - | False/False | True | 0.9549 |
| 29885 | 4 | empirical | 0.025/0.010 | - | dropout | p80 | 6.48 | False | - | - | - | False/False | True | 0.9549 |
| 29886 | 4 | empirical | 0.023/0.010 | - | drift | mill_power | 6.59 | True | 60.2 | pca | True | True/False | True | 0.9986 |
| 29887 | 5 | empirical | 0.005/0.010 | - | freeze | hpgr_power | 7.23 | True | 1.8 | stuck | True | False/True | True | 0.9986 |
| 29888 | 5 | empirical | 0.008/0.010 | - | spike | ore_hardness_est | 6.63 | False | - | - | - | False/False | True | 0.9986 |
| 29889 | 4 | empirical | 0.009/0.010 | - | bad_quality | hpgr_press | 8.78 | False | - | - | - | False/False | True | 0.9549 |
| 29890 | 5 | empirical | 0.020/0.010 | - | dropout | mill_feed | 10.30 | False | - | - | - | False/False | True | 0.9549 |
| 29891 | 5 | empirical | 0.004/0.010 | - | drift | cyc_water | 12.19 | True | 157.2 | pca | False | True/False | True | 0.9986 |
| 29892 | 5 | empirical | 0.016/0.010 | - | freeze | feed_moisture | 13.47 | True | 1.5 | stuck | True | False/True | True | 0.9986 |
| 29893 | 4 | empirical | 0.007/0.010 | - | spike | p80 | 14.81 | False | - | - | - | False/False | True | 0.9986 |
| 29894 | 4 | empirical | 0.001/0.010 | - | bad_quality | mill_power | 12.08 | False | - | - | - | False/False | True | 0.9549 |
| 29895 | 4 | empirical | 0.022/0.010 | - | dropout | hpgr_power | 12.89 | False | - | - | - | False/False | True | 0.9549 |
| 29896 | 5 | empirical | 0.010/0.010 | - | drift | ore_hardness_est | 12.53 | True | 135.2 | pca | True | True/False | True | 0.9986 |
| 29897 | 5 | empirical | 0.003/0.010 | - | freeze | hpgr_press | 13.75 | True | 1.7 | stuck | True | False/True | True | 0.9986 |
| 29898 | 4 | empirical | 0.011/0.010 | - | spike | mill_feed | 10.30 | False | - | - | - | False/False | True | 0.9986 |
| 29899 | 5 | empirical | 0.011/0.010 | - | bad_quality | cyc_water | 6.69 | False | - | - | - | False/False | True | 0.9549 |
