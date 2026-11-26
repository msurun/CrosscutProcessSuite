// Console start page joining existing read-only monitoring services.
// Each source settles independently so a denied or offline service cannot hide other tiles.
import { useEffect, useState, type ReactNode } from "react";
import { fetchRuntimeStatus } from "./api";
import { fetchControllers } from "./controllersApi";
import { fetchEquipmentAnomalies } from "./equipmentAnomalyApi";
import { fetchGatewayStatus } from "./gatewayApi";
import { fetchLiveLoops } from "./liveLoopsApi";
import type { Translate } from "./findings";
import { ControllerStateChip } from "./components/ControllerStateChip";
import { liveFindingText } from "./components/LiveLoops";
import { activeAnomalies, activeEquipmentAlarms, topLoopFindings, type OverviewSource } from "./overviewModel";

/** Refresh interval in milliseconds, matching the live loop worklist. */
const REFRESH_INTERVAL_MS = 30_000;
const LINKS = { loops: "#/d//loops", anomalies: "#/d//anomalies", controllers: "#/controllers",
  gateway: "#/d//gateway", runtime: "#/d//runtime" };

/** Read and periodically refresh one source, ignoring responses after unmount. */
function useOverviewSource<Value>(load: () => Promise<Value>): OverviewSource<Value> {
  const [source, setSource] = useState<OverviewSource<Value>>({ status: "loading" });
  useEffect(() => {
    let isMounted = true;
    const refresh = () => {
      void load().then((value) => { if (isMounted) setSource({ status: "ready", value }); })
        .catch(() => { if (isMounted) setSource({ status: "unavailable" }); });
    };
    refresh();
    const timer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => { isMounted = false; window.clearInterval(timer); };
  }, [load]);
  return source;
}

/** Render service state distinctly from a successful empty list. */
function SourceContent<Value>({ source, t, children }: {
  source: OverviewSource<Value>; t: Translate; children: (value: Value) => ReactNode;
}) {
  if (source.status !== "ready") return <p role="status">{t(`overview.${source.status}`)}</p>;
  return <>{children(source.value)}</>;
}

/** A named summary region with a permanent shortcut to its full view. */
function Tile({ name, href, t, children }: {
  name: string; href: string; t: Translate; children: ReactNode;
}) {
  return <section className="notice" data-testid={`overview-${name}`} aria-labelledby={`overview-${name}-title`}>
    <h3 id={`overview-${name}-title`}><a href={href}>{t(`overview.${name}`)}</a></h3>
    {children}
  </section>;
}

/** List equipment identities; the full view contains their event evidence. */
function EquipmentList({ rows, t }: { rows: ReturnType<typeof activeAnomalies>; t: Translate }) {
  if (rows.length === 0) return <p>{t("overview.empty")}</p>;
  return <ul>{rows.map((row) => <li key={row.equipment_id}>
    <a href={LINKS.anomalies}>{row.equipment_id}</a>
  </li>)}</ul>;
}

/** Show a read-only site overview using independently available existing endpoints. */
export function OverviewPage({ t }: { t: Translate }) {
  const loops = useOverviewSource(fetchLiveLoops);
  const equipment = useOverviewSource(fetchEquipmentAnomalies);
  return <div data-testid="overview-page" style={{ display: "grid", gap: 12, minWidth: 0, overflowWrap: "anywhere" }}>
    <div className="banner"><h2>{t("overview.title")}</h2><p>{t("overview.subtitle")}</p></div>
    <SiteTile t={t} />
    <WorklistTile loops={loops} t={t} />
    <OverviewFindings equipment={equipment} t={t} />
    <ControllersTile t={t} />
  </div>;
}

/** Show gateway and runtime health without requiring either service to answer first. */
function SiteTile({ t }: { t: Translate }) {
  const gateway = useOverviewSource(fetchGatewayStatus);
  const runtime = useOverviewSource(fetchRuntimeStatus);
  return <Tile name="site" href={LINKS.runtime} t={t}>
      <h4><a href={LINKS.gateway}>{t("overview.gateway")}</a></h4>
      <SourceContent source={gateway} t={t}>{(value) => <p>
        {t(`gateway.mode.${value.mode}`)} · <a href={LINKS.gateway}>{t("overview.pending", { count: value.pending })}</a>
      </p>}</SourceContent>
      <h4><a href={LINKS.runtime}>{t("overview.runtime")}</a></h4>
      <SourceContent source={runtime} t={t}>{(value) => <p>
        {value.service.running ? "● " : "■ "}{t(`runtime.service.${value.service.running ? "running" : "stopped"}`)}
        {value.service.updated_at_utc && <small> · {value.service.updated_at_utc}</small>}
      </p>}</SourceContent>
    </Tile>;
}

/** Reuse controller state badges so unreadable records remain explicitly unknown. */
function ControllersTile({ t }: { t: Translate }) {
  const controllers = useOverviewSource(fetchControllers);
  return <Tile name="controllers" href={LINKS.controllers} t={t}>
      <SourceContent source={controllers} t={t}>{(rows) => rows.length === 0 ? <p>{t("overview.empty")}</p> :
        <ul>{rows.map((row) => <li key={row.id}><a href={LINKS.controllers}>{row.id}</a>{" "}
          <ControllerStateChip row={row} t={t} /></li>)}</ul>}
      </SourceContent>
    </Tile>;
}

/** Keep the existing server worklist order in the top findings shortcut. */
function WorklistTile({ loops, t }: {
  loops: OverviewSource<Awaited<ReturnType<typeof fetchLiveLoops>>>;
  t: Translate;
}) {
  return <Tile name="worklist" href={LINKS.loops} t={t}>
      <SourceContent source={loops} t={t}>{(rows) => topLoopFindings(rows).length === 0 ?
        <p>{t("overview.empty")}</p> : <ul>{topLoopFindings(rows).map((loop) => <li key={loop.id}>
          <a href={LINKS.loops}>{loop.name}</a>{" · "}{liveFindingText(t, loop.findings[0].code, loop.kpi)}
          {" · "}{t(loop.fresh ? "overview.fresh" : "overview.stale")}
        </li>)}</ul>}
      </SourceContent>
    </Tile>;
}

/** Keep findings and alarms separate because shelving only suppresses alarm notifications. */
function OverviewFindings({ equipment, t }: {
  equipment: OverviewSource<Awaited<ReturnType<typeof fetchEquipmentAnomalies>>>; t: Translate;
}) {
  return <>
    <Tile name="alarms" href={LINKS.anomalies} t={t}>
      <p className="hint">{t("overview.alarmUnavailable")}</p>
      <SourceContent source={equipment} t={t}>{(rows) => <EquipmentList rows={activeEquipmentAlarms(rows)} t={t} />}</SourceContent>
    </Tile>
    <Tile name="anomalies" href={LINKS.anomalies} t={t}>
      <SourceContent source={equipment} t={t}>{(rows) => <EquipmentList rows={activeAnomalies(rows)} t={t} />}</SourceContent>
    </Tile>
  </>;
}

export default OverviewPage;
