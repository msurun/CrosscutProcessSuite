// frontend/src/components/ViewContent.tsx
// Renders the page of the current view with the data the app shell has loaded.

import type { ReactNode } from "react";
import { useAuth } from "../AuthContext";
import { canOpenView } from "../navGroups";
import type { DatasetSummary, LoopSummary, TagInfo } from "../api";
import { recordHours } from "../anomaly";
import type { Translate } from "../findings";
import { OverviewPage } from "../OverviewPage";
import { GatewayPage } from "../GatewayPage";
import { withQueryParams, type Route } from "../route";
import { HealthPage } from "./HealthPage";
import { RuntimePage } from "../RuntimePage";
import { BackupPage } from "../BackupPage";
import { DependenciesPage } from "../DependenciesPage";
import { UsersPage } from "../UsersPage";
import { AdvisoryPage } from "./AdvisoryPage";
import { EquipmentAnomaliesPage } from "./EquipmentAnomaliesPage";
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
    loops: <LoopsPage datasetId={id} route={p.route} navigate={p.navigate} t={p.t} onAnalysed={p.onAnalysed} tags={p.tags} />,
    advisory: <AdvisoryPage datasetId={id} t={p.t} />,
    anomalies: <EquipmentAnomaliesPage datasetId={id} recordHours={hours} t={p.t} />,
    softsensor: <SoftSensorPage datasetId={id} recordHours={hours} startUtc={start} t={p.t} />,
    steps: <StepsPage datasetId={id} loopNames={p.loops.map((loop) => loop.name)} initialLoop={p.route.loop} t={p.t} />,
    onboarding: <OnboardingPage datasetId={id} t={p.t} />,
    fuzzy: <FuzzyPage datasetId={id} t={p.t} />,
    trends: <TrendsPage datasetId={id} dataset={p.dataset} tags={p.tags} selectedTags={p.selectedTags} t={p.t} chartId={p.route.query?.chart ?? null} onChartChange={(chart) => p.navigate(withQueryParams(p.route, { ...p.route.query, chart }), true)} />,
  };
  return views as Record<string, ReactNode>;
}

/** Shown instead of a page the session has no permission for, e.g. a bookmarked Site or Administration URL. */
export function NoAccess({ view, t }: { view: string; t: Translate }) {
  return (
    <div className="notice notice-warning" role="alert" data-testid="no-access">
      <h2>{t("access.denied.title")}</h2>
      <p>{t("access.denied.body", { view: t(`nav.${view}`) })}</p>
    </div>
  );
}

/** The page for the route's view; dataset pages are hidden while the dataset is missing. */
export function ViewContent(props: ViewContentProps) {
  const { route, navigate, t } = props;
  const { status, permissions } = useAuth();
  if (!canOpenView(route.view, status, permissions)) return <NoAccess view={route.view} t={t} />;
  const open = (id: string, loop: string) => navigate({ dataset: id, view: "loops", loop, sub: "tuning" });
  const global: Record<string, ReactNode> = {
    overview: <OverviewPage t={t} />,
    import: <ImportPage onCreated={props.onDatasetCreated} onOpen={open} t={t} />,
    catalogue: <SitePage t={t} />,
    runtime: <RuntimePage t={t} />,
    controllers: <ControllersPage t={t} />,
    gateway: <GatewayPage t={t} />,
    health: <HealthPage t={t} />,
    tuning: <TuningProposalsPage t={t} />,
    users: <UsersPage t={t} />,
    backup: <BackupPage t={t} />,
    dependencies: <DependenciesPage t={t} />,
  };
  return <>{global[route.view] ?? (props.datasetMissing ? null : datasetViews(props, route.dataset)[route.view])}</>;
}
