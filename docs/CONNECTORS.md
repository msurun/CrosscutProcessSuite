# Read connectors

Phase 1 item 1 (#43) uses `crosscut_connectors.base.Connector` for source reads.
The registry creates CSV, SQL and OPC UA adapters from catalogue source definitions.
Check `capabilities()` before requesting optional operations. Unsupported operations
raise `NotSupportedError`. Connectors expose no control-system write operation;
all actuator writes belong to the Write Gateway (ADR 012).

## CSV history

`CsvConnector.history(tag_ids, start_utc, end_utc, period_s=None)` returns
`{"tag_ids": [...], "data": [...]}` with CSV row dictionaries. Addresses use
`file.csv/tag`. Without a layout option, tag/value headers identify long rows;
otherwise the layout is wide. Set `options["layout"]` to `"wide"` or `"long"`
to choose explicitly. Column names can be configured with
`timestamp_column`, `tag_column` and `value_column`.

History includes the start instant and excludes the end instant. Offset timestamps
are compared in UTC; file timestamps without an offset mean UTC. Filtering precedes
sampling, so values outside the requested interval cannot enter the result.

Sampling uses the **last value per period**, with periods anchored at `start_utc`:
bucket `k` covers `[start + k * period_s, start + (k + 1) * period_s)`.
Periods are seconds and must be finite and positive. The latest timestamp wins;
equal timestamps retain the last input row. Long layout samples each tag independently.
Wide layout retains the last row of requested columns. The actual sample timestamp
and associated quality remain attached to the value. Empty periods produce no rows;
there is no interpolation or forward fill. Without a period, all matching rows remain.

## Legacy imports and recording

The public CSV wide/long, SQL, OPC UA polling/subscription and simulator collector
entry points retain their signatures and dataset formats. Source acquisition passes
through connector adapters; existing parsing, duplicate handling, quality conversion,
provenance and dataset writing remain compatible with those entry points.

File history requests and whole-file imports have different purposes: imports retain
their timezone, delimiter, decimal and quality rules and do not apply a history window
unless their existing API requests one. SQL connections remain caller-owned and SQLite
file imports remain read-only. OPC UA recording retains its existing clock and session
semantics; the simulator collector still timestamps from elapsed plant time.

`AsyncOpcUaReads` provides native async reads on an already connected OPC UA session.
`OpcUaSessionConnector` implements this extension so legacy quality conversion retains
native DataValues and the collector reads its clock and tags in one atomic batch.

## Catalogue mapping and generated module configs

`PUT /catalogue/mapping` saves signals and loops to `_site/site.json` and (re)generates the default module configs `_anomaly/default.json` and `_softsensor/default.json`. Next to each generated file a sidecar `default.generated.sha256` stores the fingerprint of the text the catalogue wrote. On a remap:

- no config yet: created;
- config text still equals the sidecar fingerprint (never edited): updated to the new mapping;
- config edited by hand, or without a sidecar (unknown origin): left untouched and reported as `conflict`.

The response carries `module_configs` (`{anomaly|softsensor: {status, path}}`, status one of `created`, `updated`, `unchanged`, `conflict`) and `stale_configs` (the modules in conflict), so the GUI can show that a config no longer follows the catalogue. The owner resolves a conflict by editing the config or deleting it and saving the mapping again.
