// frontend/src/components/ViewContent.tsx
// Renders the page of the current view with the data the app shell has loaded.

import type { ReactNode } from "react";
import type { DatasetSummary, LoopSummary, TagInfo } from "../api";
import { recordHours } from "../anomaly";
import type { Translate } from "../findings";
import { GatewayPage } from "../GatewayPage";
import type { Route } from "../route";
import { RuntimePage } from "../RuntimePage";
import { UsersPage } from "../UsersPage";
import { AdvisoryPage } from "./AdvisoryPage";
import { AnomalyPage } from "./AnomalyPage";
import { ControllersPage } from "./ControllersPage";
import { FuzzyPage } from "./FuzzyPage";
import { ImportPage } from "./ImportPage";
import { LoopsPage, type AnalysisInfo } from "./LoopsPage";
import { OnboardingPage } from "./OnboardingPage";
import { SitePage } from "./SitePage";
import { SoftSensorPage } from "./SoftSensorPage";
import { StepsPage } from "./StepsPage";
import { TrendsPage } from "./TrendsPage";
import { TuningProposalsPage } from "./TuningProposalsPage";

export interface ViewContentProps {
  route: Route;
  navigate: (route: Route, replace?: boolean) => void;
  dataset: DatasetSummary | undefined;
  datasetMissing: boolean;
  tags: TagInfo[];
  loops: LoopSummary[];
  selectedTags: string[];
  onAnalysed: (info: AnalysisInfo | null) => void;
  onDatasetCreated: () => void;
  t: Translate;
}

function datasetViews(p: ViewContentProps, id: string) {
  const hours = p.dataset ? recordHours(p.dataset.time_range.start_utc, p.dataset.time_range.end_utc) : null;
  const start = p.dataset ? p.dataset.time_range.start_utc : "";
  const views = {
    loops: id && <LoopsPage datasetId={id} route={p.route} navigate={p.navigate} t={p.t} onAnalysed={p.onAnalysed} />,
    advisory: <AdvisoryPage datasetId={id} t={p.t} />,
    anomalies: <AnomalyPage datasetId={id} recordHours={hours} t={p.t} />,
    softsensor: <SoftSensorPage datasetId={id} recordHours={hours} startUtc={start} t={p.t} />,
    steps: <StepsPage datasetId={id} loopNames={p.loops.map((loop) => loop.name)} initialLoop={p.route.loop} t={p.t} />,
    onboarding: <OnboardingPage datasetId={id} t={p.t} />,
    fuzzy: <FuzzyPage datasetId={id} t={p.t} />,
    trends: <TrendsPage datasetId={id} tags={p.tags} selectedTags={p.selectedTags} t={p.t} />,
  };
  return views as Record<string, ReactNode>;
}

/** The page for the route's view; dataset pages are hidden while the dataset is missing. */
export function ViewContent(props: ViewContentProps) {
  const { route, navigate, t } = props;
  const open = (id: string, loop: string) => navigate({ dataset: id, view: "loops", loop, sub: "tuning" });
  const global: Record<string, ReactNode> = {
    import: <ImportPage onCreated={props.onDatasetCreated} onOpen={open} t={t} />,
    catalogue: <SitePage t={t} />,
    runtime: <RuntimePage t={t} />,
    controllers: <ControllersPage t={t} />,
    gateway: <GatewayPage t={t} />,
    tuning: <TuningProposalsPage t={t} />,
    users: <UsersPage t={t} />,
  };
  return <>{global[route.view] ?? (props.datasetMissing ? null : datasetViews(props, route.dataset)[route.view])}</>;
}
