# Validation report generator

Compares one online analyser with one lab tag and writes the same report every time from a
frozen template. It validates an instrument; plant data never defines features or thresholds.

## Run

```
python tools/validation_report.py DATA.csv CONFIG.json OUT_DIR
```

`DATA.csv` is long format with columns `timestamp,tag,value` (as `load_long_csv` reads it).
The tool writes `OUT_DIR/report.md` and `OUT_DIR/report.json`. Equal input gives identical bytes.

## Config (JSON)

| Field | Meaning |
| --- | --- |
| `analyser_tag`, `lab_tag` | tag roles (required) |
| `process_tags` | optional list; reported with its correlation to the analyser-lab difference |
| `composite_window_s` | length of the lab composite in seconds (required) |
| `stamp` | `{"meaning": "start"/"middle"/"end"}` or `{"offset_s": n}`: what the lab stamp marks |
| `delay_scan` | `min_delay_s`, `max_delay_s`, `step_s`, optional `bootstrap_samples` (required); the #38 scan |
| `window` | optional `{"start","end"}` stamps in the site time zone |
| `site_root` | data root with `_site/site.json`; time zone and missing codes are read from it |
| `gap_factor`, `drift_bins`, `bland_altman_z` | gap = step above this many median periods (3); time slices for drift (4); Bland-Altman multiplier (1.96) |
| `thresholds` | `max_abs_bias`, `max_rmse`, `min_correlation`, `max_abs_trend_per_day`; none has a default, an absent one is "not assessed" |

Missing codes are not a config field: they come from the site file (`read_import_settings`).

## What the report holds

Coverage per tag, stamp and missing-code checks (rows, missing-code rows, non-numeric rows,
duplicate and out-of-order stamps), the delay scan (best delay with 95 percent interval; positive
means the analyser is recorded later than the lab process time), then at the best delay: bias,
RMSE, MAE, correlation, Bland-Altman limits (differences are analyser minus lab, tag unit),
drift (trend per day and mean difference per time slice), process-tag correlations and the
threshold results. `report.json` has every number plus a `sources` map naming the function that
computes each section; the dataset, config and template SHA-256 are in both files.

## Frozen template

The Markdown wording lives in `softsensor/src/crosscut_softsensor/validation_template.py`
(`TEMPLATE_V1`, version `1`). A test pins its SHA-256. To change the wording add `TEMPLATE_V2`
with a new version and hash and keep V1 as it is.

Code: `crosscut_softsensor.validation_report` (assembly), `validation_stats` (numbers),
`alignment.scan_alignment` (delay scan, #38). Tests: `softsensor/tests/test_validation_report.py`.
