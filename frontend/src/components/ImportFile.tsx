// Step 1 of the Import view: choose a CSV file or paste its text. The file is read in the browser
// (FileReader) and shown by name and size; nothing is sent until the preview is requested.
import { useState } from "react";
import type { Translate } from "../findings";
import { formatFixed } from "../format";
import type { ImportSource } from "./ImportState";

const BYTES_PER_KB = 1000;
const BYTES_PER_MB = 1_000_000;

/** File size as a short text: bytes, kB or MB. */
export function sizeText(bytes: number): string {
  if (bytes < BYTES_PER_KB) return `${bytes} B`;
  if (bytes < BYTES_PER_MB) return `${formatFixed(bytes / BYTES_PER_KB, 1)} kB`;
  return `${formatFixed(bytes / BYTES_PER_MB, 1)} MB`;
}

interface FileProps {
  source: ImportSource | null;
  busy: boolean;
  onFile: (file: File) => void;
  onPasted: (text: string) => void;
  t: Translate;
}

/** The file input, the paste box and the name and size of what was chosen. */
export function ImportFile({ source, busy, onFile, onPasted, t }: FileProps) {
  const [pasted, setPasted] = useState("");
  return (
    <section aria-label={t("import.step1")}>
      <h3>{t("import.step1")}</h3>
      <label className="field">
        <span className="field-label">{t("import.file")}</span>
        <input
          className="field-input"
          type="file"
          accept=".csv,.txt,.tsv,text/csv,text/plain"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onFile(file);
            event.target.value = "";
          }}
        />
      </label>
      <label className="field">
        <span className="field-label">{t("import.paste")}</span>
        <textarea className="field-input import-paste" rows={4} value={pasted} onChange={(event) => setPasted(event.target.value)} />
      </label>
      <div className="toolbar">
        <button type="button" disabled={busy || pasted.trim() === ""} onClick={() => onPasted(pasted)}>{t("import.usePasted")}</button>
        {source !== null && (
          <span data-testid="import-source">{t("import.chosen", { name: source.name, size: sizeText(source.size) })}</span>
        )}
      </div>
      <p className="hint">{t("import.limit")}</p>
    </section>
  );
}
