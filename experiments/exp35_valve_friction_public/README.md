# exp35: guided stroke test analysis on public valve friction data (issue #84; protocol frozen before the run)

Product feature: guided valve stroke test (`crosscut_loops/valve_test.py`, `docs/VALVE_STROKE_TEST.md`). This is a validation
case, not a feature: it replaces #27 (no real stroke test record exists). Plant data of the owner is not used.

## Data

1. **Marques, "Diaphragm control valve model estimation - algorithms and experimental data"**, Mendeley Data,
   doi:10.17632/y7jkjt9jjf (v4, 2020-08-14), Polytechnic School of the University of Sao Paulo. Licence **CC BY 4.0**
   (read from the Mendeley public API record, `data_licence`); the code archive also carries an MIT LICENSE. Files used:
   `experimental_data.rar` (sha256 f96f6af5...483191e) holding `graphite_data_ol_ramps.csv` and
   `graphite_data_ol_sinusoidal.csv`; `ValveEstimation.zip` (sha256 ef513a9e...5255296) for the published parameters only.
   Downloaded to a scratch folder outside the repo, never committed, never redistributed; files were treated as untrusted
   (nothing executed, read with numpy only). Attribution: F. Marques, CC BY 4.0.
2. **DAMADICS** (Lublin sugar factory actuator benchmark): **blocked on terms**. Terms of use are not confirmed (site
   unreachable on 2026-11-17), so nothing was downloaded. Not part of this experiment.

CSV layout (no header): column 1 time, column 2 actuator input pressure in Pa, column 3 stem position in m. The time
column is NOT monotonic after the first rows (98503 negative steps in the ramps file), so it is ignored; the sample period
is the spacing of the first rows: ramps 0.026752 s, sinusoidal 0.01 s. The input is the pressure on the diaphragm
(open loop), the output is the measured stem position, so friction is observed directly.

## Reference values and where they come from

The code archive compiles the model parameters it estimated for this valve in `ValveEstimation/valve_models.h`
(`GRAPHITE_CHOUDHURY`, `GRAPHITE_HE`; the thesis, https://www.teses.usp.br/teses/disponiveis/3/3139/tde-12022020-100441/publico/FellipeGarciaMarquesCorr20.pdf,
was NOT read). That these are estimates from exactly these two files is inferred from the names (graphite valve) and the
README ("compiled parameters"); not confirmed. Parameter order read from `valve_models.cpp` (`set_friction_param_value`):
Choudhury = {S, J, D, x_minP, x_maxP}; the input is `(u - p_min)/(p_max - p_min) * 100` with p_min = 41368 Pa, p_max = 180000 Pa
(`PARAM_VALVULA`).

- `GRAPHITE_CHOUDHURY` = S 26.4235916, J 0.0861440961, D 14.5382759 (all in % of input span), stem limits 1.44083 mm and 27.9369 mm.
- Cross-check, `GRAPHITE_HE` = Fs 13.2061838, Fc 13.1861444, D 14.5397180: Fs + Fc = 26.39, the same total width.

Mapping to Crosscut definitions: Choudhury's S is the input travel after a reversal until the stem slips (deadband plus
stick band); Crosscut's "deadband" is the output travel after a reversal before the valve visibly moves. We take them as the
same quantity, **S_ref = 26.42 % of span** (a modelling choice; a model parameter is not a measured deadband). J (0.086 %) is
the slip jump; Crosscut's "resolution <= s" is an upper bound, so it is only checked for consistency (J <= s).

## Method (frozen)

Both files are processed identically (ramps is primary, sinusoidal is the second case).

1. u% = (pressure - 41368) / (180000 - 41368) * 100 (OP, % of span); stem position x in m is the PV.
2. **Rebuilt stroke-test record.** The data is a continuous excitation, not a stroke test, so a staircase is rebuilt:
   split the record into blocks of 50 samples; OP of a block = mean of u% over the block, held flat; PV = the real stem
   samples; time axis rescaled so one block = 1 s (dwell 1 s). The within-block dynamics are not kept. The incomplete last
   block is dropped. Block size 50 was fixed by looking at the block-to-block OP change only (median change of the
   moving blocks 1.67 % ramps, 1.92 % sinusoidal), before any stem or analysis output was seen.
3. **Crosscut analysis:** `plan_stroke_test(0, 1, -10, 130, None, step_sizes=(2.0,), steps_per_leg=(20,))` then
   `analyze_stroke_test(t, op, pv, plan)`, unchanged code and default thresholds. The estimate is the median
   bracket midpoint over reversals (`deadband`).
4. **Independent reference computation (transparent, not Crosscut code):** with the same blocks, level = block mean of u%,
   stem = block median of x. Reversal points: zigzag of level with a minimum run of 20 % of span. After each reversal, the
   travel in level until the stem has moved by more than gate in the new direction, gate = 5 * 1.4826 * median(|x - block
   median|) over all samples. Reference = median of these travels.

## Targets (frozen before the run)

Tolerance: 5.0 % of span absolute (about 2.5 steps of the 2.0 % plan step; about 19 % of S_ref).

- **T1 (acceptance):** on **each** of the two files, Crosscut's `deadband` is not None and |deadband - 26.42| <= 5.0.
  The issue is reproduced only if T1 holds on both files.
- **T2 (reference check):** on each file, the independent reference median is within 5.0 of 26.42. If T2 fails the
  comparison to the published S is not corroborated and the verdict is labelled inconclusive even if T1 passes.
- **T3 (informational):** Crosscut's bracket contains 26.42.
- **T4 (informational):** `resolution_le` is None or >= J (0.086); a None means "not certified" and is consistent with a 2 % step.

Failure rules: a missed target is reported as missed; the tolerance, block size, plan and thresholds are not changed after
seeing results. A second variant would be a new, labelled round.

## Risks stated beforehand

- The valve has a large offset D (14.5 %) and a stem that jumps near u% about 32 in the raw data (seen in the structure
  check only); the process gain is non-constant, the analysis uses one gain.
- Ramp slopes vary, so the rebuilt steps are 0.8 to above 20 % (classified as the 2.0 step by nearest size); big steps widen
  the bracket. Noise on u% makes spurious tiny reversals possible.
- The reference S is a model parameter fit, not a direct measurement; the dataset is one valve of one kind (graphite packing).
- Sinusoidal file: with 0.5 s blocks the valve dynamics may not have settled.

## Run

`python experiments/exp35_valve_friction_public/run35.py --data <folder with the two CSV files> --out result.json`
(folder also from env `EXP35_DATA`). Without the data it prints SKIP and exits 0.
