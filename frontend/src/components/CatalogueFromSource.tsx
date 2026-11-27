// "Catalogue from a source" wizard (#209): pick a source, edit naming rules, preview, import.
// The source is browsed once; editing the rules re-tests the browsed names through /catalogue/naming/test.
import { useEffect, useState, type ReactElement } from "react";

import { ApiError } from "../api";
import {
  fetchNamingPresets,
  importCatalogue,
  previewCatalogue,
  testNamingRules,
  type CataloguePreview,
  type ImportCounts,
  type NamingResult,
  type NamingRule,
} from "../catalogueSourceApi";
import type { Translate } from "../findings";
import { listSources, type SiteSource } from "../sourcesApi";
import { CatalogueNamingView } from "./CatalogueNamingView";
import { CatalogueRulesEditor, draftToRule, type RuleDraft } from "./CatalogueRulesEditor";
import { DraftNotice } from "./DraftNotice";

export interface CatalogueFromSourceProps {
  t: Translate;
}

/** Names of the tags the rules matched: these start checked. */
function matchedNames(naming: NamingResult): Set<string> {
  return new Set(naming.matches.map((m) => m.tag));
}

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : String(error);
}

/** Sources and presets, loaded once; a failure becomes the error line. */
function useChoices(setError: (message: string) => void) {
  const [sources, setSources] = useState<SiteSource[]>([]);
  const [presets, setPresets] = useState<Record<string, NamingRule[]>>({});
  useEffect(() => {
    listSources().then((r) => setSources(r.sources)).catch((e) => setError(errorText(e)));
    fetchNamingPresets().then(setPresets).catch((e) => setError(errorText(e)));
  }, [setError]);
  return { sources, presets };
}

/** All wizard state and its three actions: preview (browse), retest (no browse) and import. */
function useWizard() {
  const [error, setError] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [rules, setRules] = useState<RuleDraft[]>([]);
  const [preview, setPreview] = useState<CataloguePreview | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [options, setOptions] = useState({ loops: true, equipment: true });
  const [added, setAdded] = useState<ImportCounts | null>(null);
  const pickSource = (id: string) => {
    setSourceId(id);
    setPreview(null);
    setAdded(null);
  };
  const apiRules = () => rules.map(draftToRule);
  const run = (job: () => Promise<void>) => {
    setError("");
    job().catch((e) => setError(errorText(e)));
  };
  const show = (next: CataloguePreview) => {
    setPreview(next);
    setChecked(matchedNames(next.naming));
    setAdded(null);
  };
  const browse = () => run(async () => show(await previewCatalogue(sourceId, apiRules())));
  const retest = () =>
    run(async () => {
      if (!preview) return;
      const naming = await testNamingRules(apiRules(), preview.items.map((i) => i.name));
      show({ ...preview, naming });
    });
  const doImport = () =>
    run(async () => {
      const tags = (preview?.items ?? []).filter((i) => checked.has(i.name));
      setAdded((await importCatalogue(sourceId, tags, apiRules(), options)).added);
    });
  return { error, setError, sourceId, pickSource, rules, setRules, preview, checked, setChecked, options, setOptions, added, browse, retest, doImport };
}

type Wizard = ReturnType<typeof useWizard>;

function ItemList({ t, wiz }: { t: Translate; wiz: Wizard }): ReactElement {
  const toggle = (name: string) => {
    const next = new Set(wiz.checked);
    if (!next.delete(name)) next.add(name);
    wiz.setChecked(next);
  };
  return (
    <ul aria-label={t("catalogueSource.items")}>
      {(wiz.preview?.items ?? []).map((item) => (
        <li key={item.name}>
          <label>
            <input type="checkbox" checked={wiz.checked.has(item.name)} onChange={() => toggle(item.name)} />
            {item.name}{item.unit ? ` [${item.unit}]` : ""}
          </label>
        </li>
      ))}
    </ul>
  );
}

function ImportStep({ t, wiz }: { t: Translate; wiz: Wizard }): ReactElement {
  const flag = (key: "loops" | "equipment", label: string) => (
    <label>
      <input type="checkbox" checked={wiz.options[key]}
        onChange={(e) => wiz.setOptions({ ...wiz.options, [key]: e.target.checked })} />
      {t(label)}
    </label>
  );
  return (
    <section aria-label={t("catalogueSource.stepImport")}>
      <h3>{t("catalogueSource.stepImport")}</h3>
      {flag("loops", "catalogueSource.createLoops")}
      {flag("equipment", "catalogueSource.createEquipment")}
      <button type="button" disabled={wiz.checked.size === 0} onClick={wiz.doImport}>
        {t("catalogueSource.import", { count: wiz.checked.size })}
      </button>
      {wiz.added && (
        <>
          <p role="status">{t("catalogueSource.added", { ...wiz.added })}</p>
          <DraftNotice t={t} />
        </>
      )}
    </section>
  );
}

function PreviewStep({ t, wiz }: { t: Translate; wiz: Wizard }): ReactElement | null {
  if (!wiz.preview) return null;
  return (
    <section aria-label={t("catalogueSource.stepPreview")}>
      <h3>{t("catalogueSource.stepPreview")}</h3>
      {wiz.preview.truncated && <p role="status">{t("catalogueSource.truncated")}</p>}
      <CatalogueNamingView t={t} result={wiz.preview.naming} />
      <ItemList t={t} wiz={wiz} />
      <ImportStep t={t} wiz={wiz} />
    </section>
  );
}

function RulesStep({ t, wiz, presets }: { t: Translate; wiz: Wizard; presets: Record<string, NamingRule[]> }): ReactElement {
  return (
    <section aria-label={t("catalogueSource.stepRules")}>
      <h3>{t("catalogueSource.stepRules")}</h3>
      <CatalogueRulesEditor t={t} presets={presets} rules={wiz.rules} onChange={wiz.setRules} />
      {wiz.preview ? (
        <>
          <button type="button" onClick={wiz.retest}>{t("catalogueSource.retest")}</button>
          <button type="button" onClick={wiz.browse}>{t("catalogueSource.browseAgain")}</button>
        </>
      ) : (
        <button type="button" onClick={wiz.browse}>{t("catalogueSource.preview")}</button>
      )}
    </section>
  );
}

/** The four-step wizard under Site > From source. */
export function CatalogueFromSource({ t }: CatalogueFromSourceProps): ReactElement {
  const wiz = useWizard();
  const { sources, presets } = useChoices(wiz.setError);
  return (
    <section aria-label={t("catalogueSource.title")}>
      <h2>{t("catalogueSource.title")}</h2>
      {wiz.error && <p role="alert">{wiz.error}</p>}
      <label>
        {t("catalogueSource.stepSource")}
        <select value={wiz.sourceId} onChange={(e) => wiz.pickSource(e.target.value)}>
          <option value="">{t("catalogueSource.pickSource")}</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
        </select>
      </label>
      {wiz.sourceId && <RulesStep t={t} wiz={wiz} presets={presets} />}
      <PreviewStep t={t} wiz={wiz} />
    </section>
  );
}
