# ADR 002: Parquet long format for datasets

Status: accepted (2026-10-10)

Time series are stored as Parquet in long format (`ts`, `tag_id`, `value`, `quality`), one file per UTC day,
described by `dataset.json` (validated by `schemas/dataset.schema.json`). Long format handles irregular sampling
and sparse laboratory data; a wide view for modelling is produced on demand (`to_wide`, resampling in later stages).
`data_sha256` hashes the logical content, not the Parquet bytes, so the hash does not depend on library versions.
Consequence: readers must not assume a regular grid; regular grids are an explicit conversion step.
