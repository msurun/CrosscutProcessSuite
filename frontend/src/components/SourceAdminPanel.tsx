// List of the configured sources with Add, Edit, Delete and Test (issue #208), above the browse panel.
// Add and Edit open SourceForm; a delete refused with 409 lists the catalogue tags that use the source.
import { useCallback, useEffect, useState, type ReactElement } from "react";

import type { Translate } from "../findings";
import {
  SourceInUseError,
  deleteSource,
  listSourceEntries,
  testSavedSource,
  type SourceEntry,
} from "../sourceAdminApi";
import { SourceForm } from "./SourceForm";

export interface SourceAdminPanelProps {
  t: Translate;
}

interface RowProps {
  t: Translate;
  source: SourceEntry;
  onEdit: () => void;
  onDelete: () => void;
  onTest: () => void;
}

function SourceRow({ t, source, onEdit, onDelete, onTest }: RowProps): ReactElement {
  return (
    <li>
      <strong>{source.id}</strong> ({source.driver})
      <button type="button" onClick={onEdit}>{t("sources.edit")}</button>
      <button type="button" onClick={onDelete}>{t("sources.delete")}</button>
      <button type="button" onClick={onTest}>{t("sources.test")}</button>
    </li>
  );
}

/** Load the sources and offer delete and test, each ending in one message line. */
function useSources(t: Translate) {
  const [sources, setSources] = useState<SourceEntry[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const reload = useCallback(
    () => listSourceEntries().then((r) => setSources(r.sources ?? []), () => setSources([])),
    [],
  );
  useEffect(() => {
    void reload();
  }, [reload]);

  async function report(action: () => Promise<string>): Promise<void> {
    try {
      setMessage(await action());
    } catch (e) {
      if (e instanceof SourceInUseError) setMessage(t("sources.inUse", { tags: e.tags.join(", ") }));
      else setMessage(e instanceof Error ? e.message : String(e));
    }
  }
  const remove = (id: string) =>
    report(async () => {
      await deleteSource(id);
      await reload();
      return t("sources.deleted", { id });
    });
  const test = (id: string) =>
    report(async () => t("sources.testOk", { capabilities: (await testSavedSource(id)).capabilities.join(", ") }));
  return { sources, message, reload, remove, test };
}

/** Panel that manages the entries of `sources` in site.json. */
export function SourceAdminPanel({ t }: SourceAdminPanelProps): ReactElement {
  const { sources, message, reload, remove, test } = useSources(t);
  const [editing, setEditing] = useState<SourceEntry | "new" | null>(null);
  const onSaved = () => {
    setEditing(null);
    void reload();
  };

  if (editing) {
    const initial = editing === "new" ? undefined : editing;
    return <SourceForm t={t} initial={initial} onSaved={onSaved} onCancel={() => setEditing(null)} />;
  }
  return (
    <section aria-label={t("sources.title")}>
      <h3>{t("sources.title")}</h3>
      <button type="button" onClick={() => setEditing("new")}>{t("sources.add")}</button>
      {sources.length === 0 && <p>{t("sources.none")}</p>}
      <ul>
        {sources.map((s) => (
          <SourceRow key={s.id} t={t} source={s} onEdit={() => setEditing(s)} onDelete={() => remove(s.id)} onTest={() => test(s.id)} />
        ))}
      </ul>
      {message && <p role="alert">{message}</p>}
    </section>
  );
}
