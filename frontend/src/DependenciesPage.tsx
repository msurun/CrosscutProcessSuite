// frontend/src/DependenciesPage.tsx
/**
 * Site > Dependencies (#166): the configs, models and jobs that no longer match the published
 * catalogue (a tag was removed, remapped, changed unit or role). Each row names the reason and the
 * action: relearn the model, edit the config, or re-confirm it with an audited note. A stale item
 * never runs and a stale model cannot be deployed until one of those is done.
 */
import { useCallback, useEffect, useState } from "react";
import { useCan } from "./AuthContext";
import {
  confirmDependency, fetchDependencies, type DependencyList, type StaleDependency,
} from "./dependenciesApi";
import type { Translate } from "./findings";

export interface DependenciesPageProps {
  t: Translate;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function Reasons({ item, t }: { item: StaleDependency; t: Translate }) {
  return (
    <ul>
      {item.reasons.map((r) => (
        <li key={`${r.tag}-${r.kind}`}>
          <code>{r.tag}</code>: {t(`dependencies.reason.${r.kind}`)} ({r.detail})
        </li>
      ))}
    </ul>
  );
}

interface RowProps {
  item: StaleDependency;
  canEdit: boolean;
  busy: boolean;
  onConfirm: (key: string, note: string) => void;
  t: Translate;
}

function Row({ item, canEdit, busy, onConfirm, t }: RowProps) {
  const [note, setNote] = useState("");
  const noteId = `dep-note-${item.key}`;
  return (
    <tr data-testid={`dependency-${item.key}`}>
      <td>{t(`dependencies.kind.${item.kind}`)}</td>
      <td><code>{item.id}</code></td>
      <td><Reasons item={item} t={t} /></td>
      <td>
        {t("dependencies.versions", { built: item.built_on_version ?? "-", since: item.stale_since_version ?? "-" })}
      </td>
      <td>
        <ul>{item.actions.filter((a) => a !== "reconfirm").map((a) => (
          <li key={a}>{t(`dependencies.action.${a}`)}</li>
        ))}</ul>
        {item.actions.includes("reconfirm") && (
          <div className="field">
            <label className="field-label" htmlFor={noteId}>{t("dependencies.note")}</label>
            <input id={noteId} className="field-input" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
            <button type="button" disabled={!canEdit || busy || note.trim() === ""} onClick={() => onConfirm(item.key, note.trim())}>
              {t("dependencies.reconfirm")}
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

/** The Dependencies page. */
export function DependenciesPage({ t }: DependenciesPageProps) {
  const { allowed } = useCan("config.edit");
  const [list, setList] = useState<DependencyList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchDependencies().then((l) => { setList(l); setError(null); }).catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(load, [load]);

  const confirm = (key: string, note: string) => {
    setBusy(true);
    setMessage(null);
    confirmDependency(key, note)
      .then(() => { setMessage(t("dependencies.confirmed", { key })); load(); })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setBusy(false));
  };

  return (
    <div className="dependencies-page" data-testid="dependencies" style={{ maxWidth: 1100, margin: "20px auto", padding: "0 16px", boxSizing: "border-box" }}>
      <h1>{t("dependencies.title")}</h1>
      <p>{t("dependencies.subtitle")}</p>
      {error && <div className="notice notice-warning" role="alert"><p>{error}</p></div>}
      {message && <div className="notice" role="status"><p>{message}</p></div>}
      {list && list.items.length === 0 && (
        <p className="status-chip status-chip--ok" data-testid="dependencies-clean">
          {t("dependencies.none", { tracked: list.tracked })}
        </p>
      )}
      {list && list.items.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table aria-label={t("dependencies.title")}>
            <thead>
              <tr>
                <th scope="col">{t("dependencies.col.kind")}</th>
                <th scope="col">{t("dependencies.col.id")}</th>
                <th scope="col">{t("dependencies.col.reason")}</th>
                <th scope="col">{t("dependencies.col.versions")}</th>
                <th scope="col">{t("dependencies.col.action")}</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((item) => (
                <Row key={item.key} item={item} canEdit={allowed} busy={busy} onConfirm={confirm} t={t} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
