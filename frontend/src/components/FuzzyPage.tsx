/**
 * Fuzzy Studio page: pick a system, then work in tabs (Variables, Rules, Replay, Backtest).
 *
 * The page owns the edited document and the what-if values; the backend recomputes the
 * inference (debounced) so the panels only have to draw the result.
 */

import { systemDescription } from "../fuzzyNames";
import { useState } from "react";
import type { FuzzyDocument } from "../fuzzy";
import type { Translate } from "../findings";
import { BacktestPanel } from "./BacktestPanel";
import { FuzzyTabList, FuzzyTabPanel, type FuzzyTab } from "./FuzzyTabs";
import { useFuzzyLibrary, useWhatIf, type LibraryState, type WhatIfState } from "./FuzzyState";
import { SystemBar } from "./FuzzySystemBar";
import { InferencePanel } from "./InferencePanel";
import { ReplayPanel } from "./ReplayPanel";
import { RulesEditor } from "./RulesEditor";
import { VariableEditor } from "./VariableEditor";
import { VersionsPanel } from "./VersionsPanel";

interface TabContentProps {
  tab: FuzzyTab;
  datasetId: string;
  document: FuzzyDocument;
  library: LibraryState;
  whatIf: WhatIfState;
  t: Translate;
}

/** Variables tab: input and output editors plus the what-if inference panel. */
function VariablesTab({ document, library, whatIf, t }: Omit<TabContentProps, "tab" | "datasetId">) {
  const degrees = whatIf.inference?.degrees;
  return (
    <>
      <VariableEditor document={document} kind="inputs" onChange={library.setDocument} values={whatIf.values} degrees={degrees} t={t} />
      <VariableEditor document={document} kind="outputs" onChange={library.setDocument} degrees={degrees} t={t} />
      <InferencePanel document={document} values={whatIf.values} onValues={whatIf.setValues} inference={whatIf.inference} t={t} />
    </>
  );
}

/** Replay tab: the replay panel, or a hint when no dataset is chosen. */
function ReplayTab({ datasetId, document, t }: { datasetId: string; document: FuzzyDocument; t: Translate }) {
  if (datasetId === "") return <p className="status">{t("fuzzy.dataset.none")}</p>;
  return <ReplayPanel key={document.name} datasetId={datasetId} document={document} t={t} />;
}

/** The content of the active tab. */
function TabContent({ tab, datasetId, document, library, whatIf, t }: TabContentProps) {
  if (tab === "variables") return <VariablesTab document={document} library={library} whatIf={whatIf} t={t} />;
  if (tab === "rules") {
    return <RulesEditor document={document} onChange={library.setDocument} firing={whatIf.inference?.firing} t={t} />;
  }
  if (tab === "replay") return <ReplayTab datasetId={datasetId} document={document} t={t} />;
  return <BacktestPanel key={document.name} datasetId={datasetId} document={document} t={t} />;
}

/** Error lines of the library load and of the what-if inference. */
function ErrorLines({ library, whatIf, t }: { library: LibraryState; whatIf: WhatIfState; t: Translate }) {
  return (
    <>
      {library.loadError !== null && <p className="status status-error">{t("trends.error", { reason: library.loadError })}</p>}
      {whatIf.error !== null && <p className="status status-error">{t("trends.error", { reason: whatIf.error })}</p>}
    </>
  );
}

interface FuzzyPageProps {
  datasetId: string;
  t: Translate;
}

/**
 * Fuzzy rule-base screen.
 *
 * @param datasetId Dataset used by the replay and backtest tabs; an empty string means none is chosen.
 * @param t Translation function for the current language.
 */
export function FuzzyPage({ datasetId, t }: FuzzyPageProps) {
  const library = useFuzzyLibrary(t);
  const whatIf = useWhatIf(library.document);
  const [tab, setTab] = useState<FuzzyTab>("variables");

  if (library.document === null) {
    return <p className="status">{t("trends.loading")}</p>;
  }

  return (
    <section>
      <header className="toolbar">
        <h2>{t("fuzzy.title")}</h2>
        <span className="badge">{t("fuzzy.advisory")}</span>
      </header>
      {library.document.description !== undefined && <p className="hint">{systemDescription(t, library.selectedId, library.document.description)}</p>}
      <SystemBar library={library} t={t} />
      <ErrorLines library={library} whatIf={whatIf} t={t} />
      <FuzzyTabList active={tab} onChange={setTab} t={t} />
      <FuzzyTabPanel tab={tab}>
        <TabContent tab={tab} datasetId={datasetId} document={library.document} library={library} whatIf={whatIf} t={t} />
      </FuzzyTabPanel>
      <VersionsPanel
        systemId={library.selectedId}
        document={library.document}
        onRestore={library.setDocument}
        refreshKey={library.saveCount}
        t={t}
      />
    </section>
  );
}
