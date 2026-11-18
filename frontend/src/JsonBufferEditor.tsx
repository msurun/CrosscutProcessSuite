/**
 * Advanced raw JSON editor (issue #127). Keeps the user's text in its own buffer so
 * an incomplete document is never reset; only valid JSON is reported to the owner.
 */
import { useEffect, useState } from "react";
import type { Translate } from "./schemaFormModel";

export interface JsonBufferEditorProps {
  id: string;
  text: string; // last committed value rendered as JSON
  t: Translate;
  onValid: (text: string) => void;
}

/** Return the parse error message, or null when the text is valid JSON. */
function parseError(text: string): string | null {
  try {
    JSON.parse(text);
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
}

/** True when both texts hold the same JSON value (formatting aside). */
function sameJson(left: string, right: string): boolean {
  try {
    return JSON.stringify(JSON.parse(left)) === JSON.stringify(JSON.parse(right));
  } catch {
    return false;
  }
}

/** Textarea with a local buffer, a parse error line and commit on valid input. */
export function JsonBufferEditor({ id, text, t, onValid }: JsonBufferEditorProps) {
  const [buffer, setBuffer] = useState(text);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setBuffer((current) => (sameJson(current, text) ? current : text));
    setError((current) => (current === null ? null : parseError(text)));
  }, [text]);
  function change(next: string) {
    setBuffer(next);
    const problem = parseError(next);
    setError(problem);
    if (problem === null) onValid(next);
  }
  return (
    <>
      <textarea className="field-input" id={id} rows={8} value={buffer}
        aria-invalid={error !== null} onChange={(event) => change(event.target.value)} />
      {error !== null && (
        <p className="status status-error" role="alert" data-testid={`${id}-error`}>
          {t("configEditor.invalidJson", { detail: error })}
        </p>
      )}
    </>
  );
}
