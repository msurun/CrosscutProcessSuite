// Typed client for the saved trend charts API (/api/trends/charts).
// The API owns id, owner, schema_version, created_utc and updated_utc; stored values always win.
// Reuses the request helpers of api.ts; errors surface as ApiError.

import { API_PREFIX, getJson, sendJson } from "./api";

/** Time window of a trend chart: the last N seconds (optionally live) or a fixed start and end. */
export type TrendWindow =
  | { kind: "relative"; last_s: number; live?: boolean; refresh_s?: number }
  | { kind: "absolute"; start_utc: string; end_utc: string };

/** One series of a trend chart. */
export interface TrendSeries {
  source: string;
  tag: string;
  label?: string;
  colour?: string;
  axis: string;
  style?: "line" | "step" | "points";
}

/** One y-axis of a trend chart. */
export interface TrendAxis {
  id: string;
  side: "left" | "right";
  pane?: number;
  unit?: string;
  min?: number | null;
  max?: number | null;
}

/** One saved trend chart as returned by the API. */
export interface TrendChart {
  schema_version: number;
  id: string;
  name: string;
  owner: string;
  shared: boolean;
  created_utc: string;
  updated_utc: string;
  series: TrendSeries[];
  axes: TrendAxis[];
  window: TrendWindow;
  aggregation?: "raw" | "mean" | "minmax";
}

/** A chart without the server-owned fields, as sent to create. */
export type TrendChartDraft = Omit<TrendChart, "schema_version" | "id" | "owner" | "created_utc" | "updated_utc">;

/** One chart as listed by GET /api/trends/charts. */
export interface ChartSummary {
  id: string;
  name: string;
  owner: string;
  shared: boolean;
  updated_utc: string;
  mine: boolean;
}

const CHARTS_URL = `${API_PREFIX}/trends/charts`;

/** Path of one chart, with the id encoded. */
function chartUrl(id: string): string {
  return `${CHARTS_URL}/${encodeURIComponent(id)}`;
}

/** List the caller's charts and the shared charts of the site. */
export async function listCharts(): Promise<{ charts: ChartSummary[] }> {
  return getJson<{ charts: ChartSummary[] }>(CHARTS_URL);
}

/** One chart the caller may see (404 otherwise, so private chart ids do not leak). */
export async function getChart(id: string): Promise<TrendChart> {
  return getJson<TrendChart>(chartUrl(id));
}

/** Save a new chart owned by the caller. */
export async function createChart(draft: TrendChartDraft): Promise<TrendChart> {
  return sendJson<TrendChart>("POST", CHARTS_URL, draft);
}

/** Replace a chart the caller owns. */
export async function saveChart(chart: TrendChart): Promise<TrendChart> {
  return sendJson<TrendChart>("PUT", chartUrl(chart.id), chart);
}

/** Delete a chart the caller owns. */
export async function deleteChart(id: string): Promise<{ deleted: string }> {
  return sendJson<{ deleted: string }>("DELETE", chartUrl(id), undefined);
}

/** Copy a visible chart into the copier's own unshared charts. */
export async function copyChart(id: string): Promise<TrendChart> {
  return sendJson<TrendChart>("POST", `${chartUrl(id)}/copy`, undefined);
}
