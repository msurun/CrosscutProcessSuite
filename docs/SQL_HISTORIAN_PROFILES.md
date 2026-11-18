# SQL historian profiles

Phase 5, issue #50. A **historian profile** is one JSON file that teaches the generic SQL
connector how to read a particular vendor's historian tables. The connector code stays
vendor-neutral; only the profile changes. Profiles are read-only: they contain `SELECT`
templates and never write to the plant.

Shipped profiles live in `connectors/src/crosscut_connectors/sql_profiles/`:

| Profile | Vendor | Tags from | History from | Notes |
| --- | --- | --- | --- | --- |
| `aspen_ip21` | AspenTech InfoPlus.21 (SQLplus / ODBC) | `IP_AnalogDef` | `HISTORY`, optional `PERIOD` request | quality 0 good, 1 uncertain, 2..255 bad |
| `honeywell_phd` | Honeywell Uniformance PHD (RDBMS adapter) | `TAG` | `HISTORY` | quality 0 good, 1 uncertain, 2..255 bad |
| `aveva_wonderware` | AVEVA/Wonderware Historian (InSQL) | `Tag`, `AnalogTag`, `EngineeringUnit` | `History` with `wwRetrievalMode = 'Delta'` or `'Cyclic'` | `QualityDetail` 192 good, 64 uncertain, 128 bad |
| `siemens_wincc` | Siemens WinCC OLE-DB / Connectivity Pack | site `TAG` view | site `WINCC_ARCHIVE` view over `TAG:R` | wins by wrapping `TAG:R` in a view, see below |

Each profile provides four queries:

* **browse** – the tag list with description and engineering unit, shown in the tree;
* **metadata** – description, unit and engineering limits for one tag;
* **history** – time-bounded samples ordered by time, with value and quality columns;
* **latest** – the newest archived sample per tag, returned as a `LiveValue`.

A profile also maps vendor quality codes to Crosscut quality: **0 good, 1 uncertain,
2 bad**. Codes outside every listed range become the profile's `default`, which every
shipped profile sets to `bad`. A value nobody can classify must not look trustworthy.

## Selecting a profile in the site file

A SQL source selects exactly one profile with `profile`:

```json
{
  "id": "plant_historian",
  "driver": "sql",
  "endpoint": "sqlite:///C:/data/historian.db",
  "profile": "aveva_wonderware"
}
```

The same keys are accepted inside `options` when code builds an options mapping directly;
the site loader copies a source-level `profile`/`profile_path` into those options.

With a profile the source advertises `browse`, `metadata`, `history` and `read_live`.
Without one, `SqlConnector` keeps its generic table/column behaviour and does not
advertise `read_live`.

The connector runs every template with qmark parameters (`?`), passed separately to the
driver; no user value is ever formatted into SQL. The templates therefore work with any
DB-API 2.0 driver that uses qmark parameters, including the test sqlite databases. The
repository does not depend on `pyodbc`: the host supplies an open DB-API connection when
the endpoint is not a sqlite file.

## Overriding a profile per site

Vendor table and column names are site-specific. To correct one, copy the shipped file,
edit the SQL or the quality map, and point the source at your copy with
`profile_path`:

```json
{
  "id": "plant_historian",
  "driver": "sql",
  "endpoint": "odbc:DSN=PLANT_HISTORIAN",
  "profile": "aveva_wonderware",
  "profile_path": "C:/data/_site/profiles/aveva_plant.json"
}
```

`profile_path` wins over `profile`; keeping `profile` records which shipped file the copy
started from. The same JSON Schema
(`schemas/sql-historian-profile.schema.json`) validates the copy, and the loader also
checks that no vendor quality code is claimed by two classes and that the required column
positions are present. A bad file fails at connector creation with a `ProfileError` that
lists every problem, for example:

```
aveva_plant.json: history.columns: missing 'quality'
```

Guidelines for edits:

1. Change only the `sql`, `period_sql` and `columns` entries that your site needs.
2. Keep the column map in the same order as the `SELECT` list.
3. Keep the `ORDER BY` in history and latest queries; Crosscut also sorts samples by tag
   and ISO timestamp before returning them.
4. A period-aware query (`period_sql`) binds one extra trailing value: the period in
   seconds. Profiles without it return all archive samples and the caller may downsample.
5. Record every table or column you could not confirm in `unverified` instead of
   pretending it is known.

## Unverified names

These names were not confirmed against vendor documentation or a real site. They are
listed in each profile's `unverified` array and must be checked during commissioning.

**aspen_ip21**

* `IP_AnalogDef.LO_LIMIT` / `HI_LIMIT` – some sites use `RANGE_LO` / `RANGE_HI`.
* `HISTORY.PERIOD` – older SQLplus versions use a `REQUEST` clause instead.
* The latest query's `ORDER BY ... LIMIT 1` – SQLplus may need `FIRST 1` or a view.
* Quality ranges – IP.21 quality classes are site-configured.

**honeywell_phd**

* `TAG` and its `TAGNAME` / `DESCRIPTION` / `UNIT` columns – versions differ between
  `TAG` and `TAGDEF`, and some name the tag column `TAG`.
* `TAG.RANGE_LOW` / `RANGE_HIGH` – engineering limits may live elsewhere.
* `HISTORY.TIMESTAMP` / `VALUE` – older adapters may expose `TIME` / `VAL`.
* Quality ranges – PHD quality classes are site-configured.

**aveva_wonderware**

* `History.wwRetrievalMode` and `wwResolution` – InSQL retrieval keywords, not physical
  columns; they belong to the `History` query grammar.
* `AnalogTag.MinEU` / `MaxEU` – some versions keep limits only in the tag definition.
* `Tag.Description` – older schemas use `AnalogTag.Description`.
* Quality ranges other than `QualityDetail = 192` – they follow the OPC bit pairs and need
  confirmation on the site.

**siemens_wincc**

* `TAG.TAG_NAME` / `COMMENT` / `UNIT` – WinCC stores external tags in
  `CC_ExternalTag` / `CC_Tag`; the shipped names are a view.
* `WINCC_ARCHIVE` – a site-supplied one-row-per-sample view over the Connectivity Pack.
* `WINCC_ARCHIVE.TIMESTAMP_UTC` / `VALUE` / `QUALITY` – depend on the WinCC project.
* `LIMIT 1` – the provider may need `TOP 1`.
* Quality ranges – need confirmation against the project's archive codes.

### Why WinCC uses a view

The Connectivity Pack reads archive values through the rowset syntax
`TAG:R,'tag','start','end'`. The tag name and times are embedded inside a string literal,
so they cannot be passed as bound parameters. Formatting them in would break the rule that
user values never enter SQL text. The shipped profile therefore expects a site view
`WINCC_ARCHIVE` that wraps `TAG:R` and exposes one row per sample. The view is created once
per site during commissioning and is listed in `unverified` until it exists.

## Tests

`connectors/tests/test_sql_profiles.py` builds one in-memory sqlite database per profile
with the profile's table names and synthetic tags. It checks browse, metadata, time-bounded
and ordered history, quality mapping, latest values, the optional period queries, and
schema validation of every shipped profile. The tests do not connect to a real historian;
real-source verification is an owner task.
