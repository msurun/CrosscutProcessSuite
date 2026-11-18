# Lab and analyser alignment

The soft-sensor fit, bias correction and alignment scan resolve target timing through
`crosscut_softsensor.alignment.align_target`. Catalogue entries in `labs` match their
`tag` to the sensor's `target_tag`. Upload original catalogue timestamps as
`sample_time,value`; do not apply the same timestamp correction before uploading.

All durations are seconds. `composite_window_s` is the sampling window length.
`stamp.meaning` selects `start`, `end`, or `middle` (`mid` is also accepted).
The corresponding midpoint offset is half the window, minus half the window, or zero.
An explicit `stamp.offset_s` replaces that offset.

`analyser_delay_s` moves the represented process midpoint backwards. It does not
postpone report availability. `report_delay_s` postpones availability after the
represented sampling window ends; it overrides the legacy `latency_s`. When neither
report field is present, fit and bias tracking retain the sensor's `lab_delay_s`.
Training uses the corrected process time for feature pairing and requires the report
to be available strictly before the training cut.

Missing codes resolve from site import settings, then tag settings, then lab settings;
each explicit list replaces the earlier list. Nonfinite values and values outside a
lab's `valid_range` are excluded. Dataset quality flags also exclude bad reference values.

POST `/api/datasets/{dataset_id}/softsensor/{sid}/alignment-scan` with:

```json
{"reference_tag":"online_or_process_tag","min_delay_s":-600,"max_delay_s":600,"step_s":30}
```

The target is the sensor's uploaded lab series. The reference is a dataset process
or analyser tag, with its own catalogue timing corrections. A positive inferred delay
means reference measurements occur later than the corrected target process time.
The result is an additional relative delay after existing metadata corrections.
Scanning does not save or apply the inferred value.

For composites, each candidate compares the lab value with the reference mean within
the shifted sampling window. Point samples use linear interpolation. All candidates
use the same valid lab rows. The best delay maximizes absolute Pearson correlation,
equivalent to minimizing affine-calibration SSE on those rows. The response includes
the signed correlation profile, paired-row count and a boundary flag.

The 95% uncertainty band uses reproducible paired bootstrap resampling and includes
half a grid step on either side to represent scan resolution. It assumes independent
lab observations and is conditional on the searched range; correlated samples can
understate uncertainty. Inspect the full profile for competing peaks and expand the
range when the optimum lies at its boundary. Constant signals, fewer than eight shared
pairs, or more than 1001 candidate delays produce a validation error.
