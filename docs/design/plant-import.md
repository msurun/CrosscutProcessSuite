# Plant import: whole PI wide files with a tag dictionary (design, 2026-10-23)

Why: the first real plant data (flotation line, 10 s, 448 and 714 columns, 47 521 and 7 203 rows) does not fit the
single-loop step-test intake (one loop, 25 MB JSON body, UTC only, text modes). This adds a second path next to it. The
old path stays untouched.

## Input
- Data file: wide CSV, first column `timestamp` (naive LOCAL plant time), optional text column `test` (window label,
  empty outside test windows), all other columns numeric tags (empty cell = missing). Up to about 300 MB.
- Dictionary (optional): CSV `tag,description,unit,signal,loop,cell` (UTF-8 with BOM). `signal` values seen:
  `PV (measured)`, `OUT (controller output)`, `SP`, `mode flag`, `feedback (actuator position)`,
  `valve position (AI)`, `valve reference (AO)`, `other`. `loop` is the loop number (`20103`), may be empty.
- Without a dictionary the roles are guessed from the tag names (`<prefix>-<loop>.mv|.out|.sp|.auto#state|.feedback`).

## Rules
- Time zone option: `utc` (default, old behaviour), `iana` with a name (`America/Santiago`; DST applied by `zoneinfo`,
  ambiguous or nonexistent local times resolved by taking the first occurrence / shifting forward, counted in a note) or
  `offset` with hours (`-3`). Everything is stored in UTC. The note records the zone and the offset of the first row.
- Loop = all dictionary rows with the same `loop` number that have a PV, an OUT, an SP and a mode flag. Loop id
  `<PREFIX>-<number>` from the tag name (`LIC-20103`). Incomplete loops are listed with the missing roles and are not
  written to `project.json`.
- `process_kind`: `integrating` when the controller prefix is `lic` or `lc` (level), otherwise `self_regulating`.
- Mode is numeric: 1 = automatic, 0 = manual (as in the dictionary's `mode flag`). The existing project loop schema
  already treats MODE 0 as manual. Missing mode values are held from the last value, a leading gap is 0 (manual) with a note.
- Dataset: original timestamps are kept (NO resampling, gaps between test windows stay gaps), values float64, a missing
  cell is written with quality 2 (bad) and value NaN. Tags written: all loop signals (pv, sp, out, mode, feedback,
  valve AI/AO) plus, by `scope`: `loops` (only those) or `process` (default: also every other analog tag that has at
  least 50 % present values and is not constant, at most 1200 tags in total; the rest is listed as skipped with a count).
- `tags.json`: `description` and `unit` from the dictionary; `role` PV/SP/OUT/MODE for loop tags (see tags schema), the
  other roles per the schema's enum (check it).
- `project.json`: one `loops` entry per complete loop: id, name, pv, sp, out, mode, unit (PV unit), process_kind,
  cell when known.
- Sidecar `test_windows.json` in the dataset folder: list of `{label, start_utc, end_utc, rows}` from the `test` column
  (contiguous runs of the same non-empty label), used later by the step analyzer.
- Memory: the dataset writer builds a long table; keep the written tag count bounded as above.

## Python API (module `crosscut_loops/plant_import.py`, pure, no HTTP)
- `read_dictionary(text) -> list[DictRow]`
- `detect_loops(columns, dictionary) -> list[DetectedLoop]` (id, name, process_kind, pv, sp, out, mode, feedback,
  valves, unit, cell, complete, missing)
- `TimeZoneSpec(kind, value)`, `to_utc_ns(naive_times, spec) -> (ns array, notes)`
- `preview_plant(data_path, dictionary_text | None, tz) -> dict` JSON-safe: n_rows, n_columns, time range local and UTC,
  sampling period (median), n_gaps and gap list (> 5 sampling periods, at most 20 listed), loops (detected), skipped
  counts, test windows, notes. Reads the file once with `pyarrow.csv`.
- `import_plant(data_path, dictionary_text | None, out_dir, tz, scope) -> PlantImportResult` (notes as coded `Note`
  objects like step_test_io, loops list, tags written, tags skipped, test windows).

## HTTP (module `crosscut_api/plant_import_routes.py`)
- `POST /intake/plant/upload?role=data|dictionary` raw body (not JSON, streamed to disk in chunks, 300 MB cap,
  413 above) -> `{upload_id, bytes}`. Files go to `<data root>/_uploads/<id>`; folders starting with `_` are not datasets.
- `POST /intake/plant/preview` `{data_upload, dictionary_upload?, timezone:{kind,value}}` -> preview dict.
- `POST /intake/plant/import` `{data_upload, dictionary_upload?, timezone, scope, dataset_id}` -> 201
  `{dataset_id, loops, notes, tags_written, tags_skipped}`; 409 if the dataset exists; uploads deleted after success.
- `DELETE /intake/plant/upload/{id}`. Nothing here reaches a plant.

## GUI (Import view, new section "Whole PI file")
Two file pickers (data, optional dictionary), time zone select (UTC / America/Santiago / fixed offset input), preview
(counts, time range local and UTC, gaps, detected loops table with kind and missing roles, test windows), scope select,
dataset id, import button, result with links to open each loop. en/pl/es strings, vitest, Playwright e2e with axe.
