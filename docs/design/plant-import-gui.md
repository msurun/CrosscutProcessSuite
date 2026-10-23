# Plant import GUI: module interfaces and i18n keys (appendix to plant-import.md)

Files (frontend/src): `plantImport.ts` (types, fetch calls, helpers), `components/ImportPlantState.ts` (hook),
`components/ImportPlant.tsx` (page section), `components/ImportPlantPreview.tsx` (preview tables). Each starts with a 2-4
line `//` header. Tests: `plantImport.test.ts`, `components/ImportPlant.test.tsx`, `e2e/plant_import.spec.ts`.

## plantImport.ts exports
```ts
export type TimeZoneBody = { kind: "utc" | "iana" | "offset"; value: string | number | null };
export interface PlantLoop { id: string; name: string; process_kind: "integrating" | "self_regulating"; pv: string | null;
  sp: string | null; out: string | null; mode: string | null; feedback: string | null; valves: string[]; unit: string;
  cell: string; complete: boolean; missing: string[] }
export interface PlantGap { start_utc: string; end_utc: string; seconds: number }
export interface PlantWindow { label: string; start_utc: string; end_utc: string; rows: number }
export interface PlantNote { code: string; text: string; params: Record<string, unknown> }
export interface PlantPreview { n_rows: number; n_columns: number; start_local: string; end_local: string; start_utc: string;
  end_utc: string; period_s: number; n_gaps: number; gaps: PlantGap[]; loops: PlantLoop[];
  skipped: { count: number; reason: string }; test_windows: PlantWindow[]; notes: PlantNote[] }
export interface PlantImportResult { dataset_id: string; loops: PlantLoop[]; notes: PlantNote[]; tags_written: number;
  tags_skipped: number; test_windows: PlantWindow[] }
export type TzPreset = "utc" | "santiago" | "offset";
export function timezoneBody(preset: TzPreset, offsetHours: string): TimeZoneBody | null; // utc -> {kind:"utc",value:null}; santiago -> {kind:"iana",value:"America/Santiago"}; offset -> number from text (comma or dot decimal), null when not a number or |h|>14
export function validDatasetId(id: string): boolean; // ^[A-Za-z0-9_-]{1,64}$
export function noteText(note: PlantNote, t: Translate): string; // key `plant.note.<code>` with params as strings; if the key is missing (t returns the key itself) or a param missing: note.text
export function uploadPlantFile(role: "data" | "dictionary", file: File): Promise<{ upload_id: string; bytes: number }>; // POST /intake/plant/upload?role=..., raw body = file, Content-Type application/octet-stream
export function previewPlant(body: { data_upload: string; dictionary_upload: string | null; timezone: TimeZoneBody }): Promise<PlantPreview>;
export function importPlant(body: { data_upload: string; dictionary_upload: string | null; timezone: TimeZoneBody; scope: "loops" | "process"; dataset_id: string }): Promise<PlantImportResult>;
export function deletePlantUpload(uploadId: string): Promise<void>;
```
URL prefix and error handling (`readErrorMessage`, `sendJson`) follow `api.ts`; failures throw `Error(message)`.

## Hook (ImportPlantState.ts)
`usePlantImport(t: Translate, onCreated: () => void)` returns `{ dataFile, dictionaryFile, setDataFile, setDictionaryFile,
preset, setPreset, offsetHours, setOffsetHours, preview, scope, setScope, datasetId, setDatasetId, busy
(null | "preview" | "import"), error (string | null), result (PlantImportResult | null), canPreview, canImport, runPreview(),
runImport(), reset() }`. runPreview uploads both files (data, optional dictionary), keeps the upload ids, then previews;
runImport imports with the kept upload ids, calls onCreated() on success; reset deletes kept uploads (deletePlantUpload).

## Component (ImportPlant.tsx)
`export function ImportPlant({ onCreated, onOpen, t }: { onCreated: () => void; onOpen: (datasetId: string, loop: string) => void; t: Translate })`.
Order: note, data file input, optional dictionary file input, time zone select (+ number input when "offset"), button "Read
and preview", then (preview) `ImportPlantPreview`, scope select, dataset id input (invalid -> `plant.dataset.invalid`),
button "Import", then result with one button per loop (`onOpen(result.dataset_id, loop.id)`) and "Start again". Errors in
`<p className="status status-error" role="alert">`. All labels linked to inputs (axe). Reuse CSS classes already used by
ImportPage/ImportPreview (toolbar, notice, status, tables).

## i18n keys (en/pl/es; `{name}` placeholders as in the existing files)
plant.tab.single, plant.tab.plant, plant.title, plant.note.local, plant.data.label, plant.dictionary.label,
plant.dictionary.hint, plant.tz.label, plant.tz.utc, plant.tz.santiago, plant.tz.offset, plant.tz.offsetHours,
plant.tz.invalid, plant.preview.run, plant.preview.running, plant.preview.rows ({rows}, {columns}), plant.preview.range
({start}, {end}), plant.preview.period ({seconds}), plant.preview.gaps ({count}), plant.preview.noGaps,
plant.preview.skipped ({count}), plant.loops.title, plant.loops.id, plant.loops.kind, plant.loops.cell, plant.loops.status,
plant.loops.complete, plant.loops.missing ({roles}), plant.kind.integrating, plant.kind.self_regulating, plant.windows.title,
plant.windows.label, plant.windows.start, plant.windows.end, plant.windows.rows, plant.windows.none, plant.scope.label,
plant.scope.loops, plant.scope.process, plant.dataset.label, plant.dataset.invalid, plant.import.run, plant.import.running,
plant.done.title, plant.done.written ({written}, {skipped}), plant.done.open ({loop}), plant.done.reset, plant.notes.title,
plant.note.tz_utc, plant.note.tz_offset ({hours}), plant.note.tz_iana ({zone}, {first}, {last}), plant.note.tz_ambiguous
({rows}), plant.note.tz_nonexistent ({rows}), plant.note.read_plant ({rows}, {columns}), plant.note.import_scope ({scope},
{written}, {skipped}), plant.note.gaps ({count}, {period}), plant.note.mode_leading_gap.
