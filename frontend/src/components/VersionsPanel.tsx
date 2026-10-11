/**
 * "Versions" panel: lists the saved snapshots of a rule base, shows what changed against the edited document
 * and lets the user restore one.
 *
 * A snapshot is only loaded once the user picks it from the list; nothing happens while the list is empty.
 */

import { useEffect, useRef, useState } from "react";
import { diffFuzzy, fetchFuzzyVersion, fetchFuzzyVersions, type FuzzyChange } from "../api";
import type { Translate } from "../findings";
import type { FuzzyDocument } from "../fuzzy";
import { changeText, versionLabel } from "../fuzzyDiff";

/** How much older than the current document a snapshot is. */
interface DiffState {
  /** The chosen version, or "" when the user has not picked one yet. */
  versionId: string;
  changes: FuzzyChange[];
  isReady: boolean;
  isLoading: boolean;
  errorReason: string;
}

const EMPTY_DIFF: DiffState = {
  versionId: "",
  changes: [],
  isReady: false,
  isLoading: false,
  errorReason: "",
};

/** Human-readable text for a rejected request promise. */
function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

/**
 * Load the version ids of a rule base.
 *
 * The list is reloaded whenever `systemId` or `refreshKey` changes; the answer of an outdated request is dropped.
 */
function useVersionIds(systemId: string, refreshKey: number): { ids: string[]; errorReason: string } {
  const [ids, setIds] = useState<string[]>([]);
  const [errorReason, setErrorReason] = useState("");
  const requestCounter = useRef(0);

  useEffect(() => {
    requestCounter.current += 1;
    const requestId = requestCounter.current;
    let isCurrent = true;

    fetchFuzzyVersions(systemId)
      .then((versionIds) => {
        if (!isCurrent || requestId !== requestCounter.current) return;
        setIds(versionIds);
        setErrorReason("");
      })
      .catch((error: unknown) => {
        if (!isCurrent || requestId !== requestCounter.current) return;
        setIds([]);
        setErrorReason(describeError(error));
      });

    return () => {
      isCurrent = false;
    };
  }, [systemId, refreshKey]);

  return { ids, errorReason };
}

/**
 * Compare the chosen snapshot against the current document.
 *
 * Runs again when `document` changes, so an edit right after choosing a version is reflected immediately.
 */
function useVersionDiff(systemId: string, document: FuzzyDocument, versionId: string): DiffState {
  const [state, setState] = useState<DiffState>(EMPTY_DIFF);

  useEffect(() => {
    if (versionId === "") {
      setState(EMPTY_DIFF);
      return;
    }
    let isCurrent = true;
    setState({ ...EMPTY_DIFF, versionId, isLoading: true });

    loadVersionDiff(systemId, versionId, document)
      .then((changes) => {
        if (!isCurrent) return;
        setState({ versionId, changes, isReady: true, isLoading: false, errorReason: "" });
      })
      .catch((error: unknown) => {
        if (!isCurrent) return;
        setState({ ...EMPTY_DIFF, versionId, errorReason: describeError(error) });
      });

    return () => {
      isCurrent = false;
    };
  }, [systemId, document, versionId]);

  return state;
}

/** Fetch the snapshot, then list what changed from it to the current document. */
async function loadVersionDiff(
  systemId: string,
  versionId: string,
  document: FuzzyDocument,
): Promise<FuzzyChange[]> {
  const versionDocument = await fetchFuzzyVersion(systemId, versionId);
  return diffFuzzy(versionDocument, document);
}

/** The list of changes, one sentence per change. */
function ChangeList({ changes, t }: { changes: FuzzyChange[]; t: Translate }) {
  if (changes.length === 0) {
    return <p className="hint">{t("fuzzy.versions.noChanges")}</p>;
  }
  return (
    <ul>
      {changes.map((change, index) => (
        <li key={index}>{changeText(t, change)}</li>
      ))}
    </ul>
  );
}

/** Props of {@link VersionsPanel}. */
export interface VersionsPanelProps {
  /** Rule base whose snapshots are listed. */
  systemId: string;
  /** The edited document the snapshots are compared against. */
  document: FuzzyDocument;
  /** Called with the snapshot to load into the editor. */
  onRestore: (document: FuzzyDocument) => void;
  /** Changes after every save, which reloads the list. */
  refreshKey: number;
  /** Translator bound to the current language. */
  t: Translate;
}

/**
 * Panel listing the saved snapshots of `systemId`; choosing one shows its differences and offers to restore it.
 *
 * @param props See {@link VersionsPanelProps}.
 */
export function VersionsPanel({ systemId, document, onRestore, refreshKey, t }: VersionsPanelProps) {
  const { ids, errorReason } = useVersionIds(systemId, refreshKey);
  const [versionId, setVersionId] = useState("");
  const [restoreError, setRestoreError] = useState("");
  const diff = useVersionDiff(systemId, document, versionId);

  useEffect(() => {
    setVersionId("");
  }, [systemId]);

  const restore = () => {
    fetchFuzzyVersion(systemId, versionId)
      .then((versionDocument) => onRestore(versionDocument))
      .catch((error: unknown) => setRestoreError(describeError(error)));
  };

  return (
    <>
      <h3>{t("fuzzy.versions.title")}</h3>
      {errorReason !== "" && <p className="status status-error">{t("trends.error", { reason: errorReason })}</p>}
      {errorReason === "" && ids.length === 0 && <p className="hint">{t("fuzzy.versions.none")}</p>}
      {ids.length > 0 && (
        <div className="toolbar">
          <label>
            {t("fuzzy.versions.compare")}
            <select value={versionId} onChange={(event) => setVersionId(event.target.value)}>
              <option value="" />
              {ids.map((id) => (
                <option key={id} value={id}>
                  {versionLabel(id)}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="filter-chip" disabled={versionId === ""} onClick={restore}>
            {t("fuzzy.versions.restore")}
          </button>
        </div>
      )}
      {diff.isLoading && <p className="status">{t("trends.loading")}</p>}
      {diff.errorReason !== "" && (
        <p className="status status-error">{t("trends.error", { reason: diff.errorReason })}</p>
      )}
      {restoreError !== "" && <p className="status status-error">{t("trends.error", { reason: restoreError })}</p>}
      {diff.isReady && <ChangeList changes={diff.changes} t={t} />}
    </>
  );
}
