
### T1_Cu_conc (primary)

| R1 | R2 | R3 | R4 | R5 |
|---|---|---|---|---|
| PASS | MISS | MISS | PASS | PASS |

| method | RMSE | MAE | R2 |
|---|---|---|---|
| M0 | 1.2742 | 1.0452 | -0.3082 |
| M1 | 0.6606 | 0.4990 | 0.6484 |
| M2 | 0.6479 | 0.4862 | 0.6618 |
| M3 | 0.6960 | 0.5594 | 0.6097 |

train a=-0.2633  b=1.0624  n_train=67  n_test=45  CV RMSE (M2)=0.7811  unusable share=0.222

R1 M2/M0=0.508  R2 M3/M2=1.074  R3 unusable=0.222  R5 TEST/CV=0.829

### T2_Mo_conc (primary)

| R1 | R2 | R3 | R4 | R5 |
|---|---|---|---|---|
| PASS | PASS | MISS | PASS | PASS |

| method | RMSE | MAE | R2 |
|---|---|---|---|
| M0 | 0.0306 | 0.0210 | 0.4147 |
| M1 | 0.0120 | 0.0100 | 0.9099 |
| M2 | 0.0130 | 0.0105 | 0.8938 |
| M3 | 0.0116 | 0.0094 | 0.9165 |

train a=-0.0003  b=0.9470  n_train=67  n_test=45  CV RMSE (M2)=0.0420  unusable share=0.222

R1 M2/M0=0.426  R2 M3/M2=0.886  R3 unusable=0.222  R5 TEST/CV=0.310

### S_Fe_conc (secondary (reported, no criteria))

| method | RMSE | MAE | R2 |
|---|---|---|---|
| M0 | 6.1720 | 4.9016 | -0.2827 |
| M1 | 3.3213 | 2.6809 | 0.6286 |
| M2 | 3.2873 | 2.4065 | 0.6361 |
| M3 | 3.3968 | 2.6712 | 0.6115 |

train a=-2.0635  b=1.1198  n_train=66  n_test=45  CV RMSE (M2)=3.4840  unusable share=0.229

R1 M2/M0=0.533  R2 M3/M2=1.033  R3 unusable=0.229  R5 TEST/CV=0.944

### S_Cu_tail (secondary (reported, no criteria))

| method | RMSE | MAE | R2 |
|---|---|---|---|
| M0 | 0.0187 | 0.0148 | 0.1019 |
| M1 | 0.0108 | 0.0089 | 0.7004 |
| M2 | 0.0149 | 0.0117 | 0.4329 |
| M3 | 0.0123 | 0.0091 | 0.6134 |

train a=-0.0306  b=1.4670  n_train=67  n_test=45  CV RMSE (M2)=0.0129  unusable share=0.222

R1 M2/M0=0.795  R2 M3/M2=0.826  R3 unusable=0.222  R5 TEST/CV=1.152

### S_Fe_tail (secondary (reported, no criteria))

| method | RMSE | MAE | R2 |
|---|---|---|---|
| M0 | 0.4840 | 0.3893 | 0.2151 |
| M1 | 0.3586 | 0.3009 | 0.5691 |
| M2 | 0.4528 | 0.3567 | 0.3132 |
| M3 | 0.3056 | 0.2565 | 0.6871 |

train a=1.5000  b=0.6430  n_train=67  n_test=45  CV RMSE (M2)=0.2289  unusable share=0.222

R1 M2/M0=0.935  R2 M3/M2=0.675  R3 unusable=0.222  R5 TEST/CV=1.978

### S_Mo_tail (secondary (reported, no criteria))

| method | RMSE | MAE | R2 |
|---|---|---|---|
| M0 | 0.0007 | 0.0005 | 0.4042 |
| M1 | 0.0005 | 0.0004 | 0.7185 |
| M2 | 0.0009 | 0.0007 | 0.0172 |
| M3 | 0.0007 | 0.0005 | 0.3388 |

train a=-0.0019  b=1.6134  n_train=67  n_test=45  CV RMSE (M2)=0.0008  unusable share=0.222

R1 M2/M0=1.284  R2 M3/M2=0.820  R3 unusable=0.222  R5 TEST/CV=1.095
