// src/components/LoopsPage.tsx
//
// The loops view: the worklist overview, one loop's detail, and its tuning and benefit pages.
// Which of them is shown comes from the URL route (so reload and the back button work); the
// loop analysis is fetched here and its timing is reported up for the dataset context bar.

import { useEffect, useRef, useState } from "react";

import { fetchLoops, type LoopSummary } from "../api";
import type { Translate } from "../findings";
import { withLoop, type Route } from "../route";
import { BenefitPage } from "./BenefitPage";
import { LoopDetail } from "./LoopDetail";
import { LoopsOverview } from "./LoopsOverview";
import { TuningPage } from "./TuningPage";
import { ValveTestPage } from "./ValveTestPage";

/** Whether the loop list is being fetched, has arrived, or failed. */
type LoadStatus = "loading" | "ready" | "error";

/** When the last analysis finished and how long the request took. */
export interface AnalysisInfo {
  finishedAt: Date;
  tookMs: number;
}

/** What the loop list needs while it loads. */
interface LoopsState {
  loops: LoopSummary[];
  status: LoadStatus;
  errorReason: string;
  /** Fetches the loops again without showing the loading state (used after the loop data changed). */
  reload: () => void;
}

/**
 * Loads the loops of a dataset and reports where the request stands.
 *
 * Another dataset shows the loading state; a reload of the same dataset keeps the list on screen.
 * `onAnalysed` receives the timing of every finished request (null while a new dataset loads).
 */
function useLoops(datasetId: string, onAnalysed: (info: AnalysisInfo | null) => void): LoopsState {
  const [loops, setLoops] = useState<LoopSummary[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [reloadCount, setReloadCount] = useState(0);
  const report = useRef(onAnalysed);
  report.current = onAnalysed;

  useEffect(() => {
    // A late response from a previous dataset must not overwrite the current one.
    let isCancelled = false;
    const startedAt = performance.now();
    setFailure(null);

    fetchLoops(datasetId)
      .then((loadedLoops) => {
        if (isCancelled) return;
        setLoops(loadedLoops);
        setLoadedFor(datasetId);
        report.current({ finishedAt: new Date(), tookMs: performance.now() - startedAt });
      })
      .catch((error: unknown) => {
        if (isCancelled) return;
        setFailure(error instanceof Error ? error.message : String(error));
      });

    return () => {
      isCancelled = true;
    };
    // reloadCount is a trigger, not a value used inside the effect.
  }, [datasetId, reloadCount]);

  useEffect(() => () => report.current(null), [datasetId]);

  const status: LoadStatus = failure !== null ? "error" : loadedFor === datasetId ? "ready" : "loading";
  return { loops, status, errorReason: failure ?? "", reload: () => setReloadCount((count) => count + 1) };
}

/** One step of the breadcrumb; the last one has no action and marks the current page. */
interface Crumb {
  label: string;
  onSelect?: () => void;
}

/** "Loops > hpgr_press > Tuning report": where the user is and a way back up. */
function Breadcrumb({ crumbs, label }: { crumbs: Crumb[]; label: string }) {
  return (
    <nav className="breadcrumb" aria-label={label}>
      <ol>
        {crumbs.map((crumb, index) => (
          <li key={crumb.label} aria-current={index === crumbs.length - 1 ? "page" : undefined}>
            {crumb.onSelect ? (
              <button type="button" className="link-button" onClick={crumb.onSelect}>
                {crumb.label}
              </button>
            ) : (
              crumb.label
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Message shown when the URL names a loop that this dataset does not have. */
function LoopNotFound({ name, onBack, t }: { name: string; onBack: () => void; t: Translate }) {
  return (
    <div className="status status-error" role="alert">
      <p>{t("route.notFoundLoop", { name })}</p>
      <button type="button" className="filter-chip" onClick={onBack}>
        {t("route.backToLoops")}
      </button>
    </div>
  );
}

/** Props of the loops page: the dataset, the current route and how to change it. */
interface LoopsPageProps {
  datasetId: string;
  route: Route;
  navigate: (route: Route) => void;
  t: Translate;
  onAnalysed: (info: AnalysisInfo | null) => void;
}

/**
 * Page that lists the loops of a dataset, or shows one loop's detail, tuning or benefit page.
 *
 * Shows a loading or error message instead of the list when the request is still running or has
 * failed. The selected loop and page are part of the route, so the browser's back button and a
 * reload return to the same screen.
 */
export function LoopsPage({ datasetId, route, navigate, t, onAnalysed }: LoopsPageProps) {
  const { loops, status, errorReason, reload } = useLoops(datasetId, onAnalysed);

  if (status === "loading") {
    return (
      <p className="status" role="status">
        {t("loops.analysing")}
      </p>
    );
  }
  if (status === "error") {
    return <p className="status status-error">{t("trends.error", { reason: errorReason })}</p>;
  }

  const toList = () => navigate(withLoop(route, null));
  if (route.loop === null) {
    return (
      <>
        <h2>{t("loops.title")}</h2>
        <LoopsOverview loops={loops} t={t} onOpen={(name) => navigate(withLoop(route, name))} />
      </>
    );
  }

  const loop = loops.find((one) => one.name === route.loop);
  if (loop === undefined) return <LoopNotFound name={route.loop} onBack={toList} t={t} />;

  const toDetail = () => navigate(withLoop(route, loop.name, "detail"));
  const crumbs: Crumb[] = [{ label: t("loops.title"), onSelect: toList }];
  if (route.sub === "detail") {
    crumbs.push({ label: loop.name });
  } else {
    crumbs.push({ label: loop.name, onSelect: toDetail });
    const pageTitleKey = { tuning: "tuning.title", benefit: "benefit.title", valve: "valve.title" }[route.sub];
    crumbs.push({ label: t(pageTitleKey) });
  }

  return (
    <>
      <Breadcrumb crumbs={crumbs} label={t("nav.breadcrumb")} />
      {route.sub === "tuning" && (
        <TuningPage datasetId={datasetId} loopName={loop.name} loop={loop} t={t} onBack={toDetail} />
      )}
      {route.sub === "benefit" && (
        <BenefitPage datasetId={datasetId} loopName={loop.name} t={t} onBack={toDetail} />
      )}
      {route.sub === "valve" && <ValveTestPage datasetId={datasetId} loop={loop} t={t} onBack={toDetail} />}
      {route.sub === "detail" && (
        <LoopDetail
          datasetId={datasetId}
          loop={loop}
          t={t}
          onBack={toList}
          onOpenTuning={() => navigate(withLoop(route, loop.name, "tuning"))}
          onOpenBenefit={() => navigate(withLoop(route, loop.name, "benefit"))}
          onOpenValve={() => navigate(withLoop(route, loop.name, "valve"))}
          onOpenLoop={(name) => navigate(withLoop(route, name))}
          onKnowledgeSaved={reload}
        />
      )}
    </>
  );
}
