// frontend/src/components/SavedChartsPanel.tsx
/**
 * Panel that lists saved trend charts, lets the user open, rename, duplicate,
 * delete, share/unshare and copy charts. It fetches data from the API and
 * updates after each mutation. All UI strings are obtained via the `t`
 * translation function under the `savedCharts` namespace.
 */

import { useEffect, useState, FormEvent } from "react";

import { ModalDialog } from "./ModalDialog";
import type { Translate } from "../findings";

import type { ChartSummary, TrendChart } from "../trendChartsApi";
import {
  listCharts,
  getChart,
  saveChart,
  copyChart,
  deleteChart,
} from "../trendChartsApi";

import { ApiError } from "../api";

/** Props accepted by {@link SavedChartsPanel}. */
export interface SavedChartsPanelProps {
  /** Translation function (key → localized string). */
  t: Translate;
  /** Whether the current user may change a chart's `shared` flag. */
  canShare: boolean;
  /** ID of the chart currently shown elsewhere; that row is highlighted. */
  activeId: string | null;
  /** Callback invoked when the user wants to open a chart. */
  onOpen: (id: string) => void;
  /** Incremented by the parent to force a reload of the chart list. */
  reloadToken: number;
}

/**
 * Render a list of saved charts split into “My charts” and “Shared charts”.
 * Supports renaming, duplicating, deleting, sharing/unsharing and copying.
 */
export function SavedChartsPanel({
  t,
  canShare,
  activeId,
  onOpen,
  reloadToken,
}: SavedChartsPanelProps) {
  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  const [charts, setCharts] = useState<ChartSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Rename dialog state
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState<string>("");
  const [renameBusy, setRenameBusy] = useState<boolean>(false);

  // Delete‑confirmation dialog state
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState<boolean>(false);

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  /** Load the list of charts from the server. */
  async function fetchCharts(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const data = await listCharts();
      setCharts(data.charts);
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
      else setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  /** Re‑load charts after a mutation. */
  function refresh(): void {
    void fetchCharts();
  }

  /** Format an ISO UTC timestamp as a local date‑time string. */
  function formatDate(utc: string): string {
    return new Date(utc).toLocaleString();
  }

  // -------------------------------------------------------------------------
  // Effects
  // -------------------------------------------------------------------------

  // Load charts on mount and whenever the parent forces a reload.
  useEffect(() => {
    void fetchCharts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  // -------------------------------------------------------------------------
  // Rename dialog handling
  // -------------------------------------------------------------------------

  function startRename(id: string, currentName: string): void {
    setRenameId(id);
    setRenameValue(currentName);
  }

  function cancelRename(): void {
    setRenameId(null);
    setRenameValue("");
  }

  async function confirmRename(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!renameId) return;
    setRenameBusy(true);
    try {
      const chart: TrendChart = await getChart(renameId);
      const updated: TrendChart = { ...chart, name: renameValue };
      await saveChart(updated);
      cancelRename();
      refresh();
    } catch (e) {
      console.error(e);
    } finally {
      setRenameBusy(false);
    }
  }

  // -------------------------------------------------------------------------
  // Delete dialog handling
  // -------------------------------------------------------------------------

  function startDelete(id: string): void {
    setDeleteId(id);
  }

  function cancelDelete(): void {
    setDeleteId(null);
  }

  async function confirmDelete(): Promise<void> {
    if (!deleteId) return;
    setDeleteBusy(true);
    try {
      await deleteChart(deleteId);
      cancelDelete();
      refresh();
    } catch (e) {
      console.error(e);
    } finally {
      setDeleteBusy(false);
    }
  }

  // -------------------------------------------------------------------------
  // Action buttons (own charts)
  // -------------------------------------------------------------------------

  async function duplicateChart(id: string): Promise<void> {
    try {
      await copyChart(id);
      refresh();
    } catch (e) {
      console.error(e);
    }
  }

  async function toggleShare(id: string): Promise<void> {
    try {
      const chart: TrendChart = await getChart(id);
      const updated: TrendChart = { ...chart, shared: !chart.shared };
      await saveChart(updated);
      refresh();
    } catch (e) {
      console.error(e);
    }
  }

  // -------------------------------------------------------------------------
  // Action button (shared charts)
  // -------------------------------------------------------------------------

  async function copyToMine(id: string): Promise<void> {
    try {
      await copyChart(id);
      refresh();
    } catch (e) {
      console.error(e);
    }
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  const myCharts = charts.filter((c) => c.mine);
  const sharedCharts = charts.filter((c) => c.shared && !c.mine);

  return (
    <div>
      <h2>{t("savedCharts.title")}</h2>

      {loading && <p>{t("savedCharts.loading")}</p>}

      {error && (
        <p>
          {t("savedCharts.error")}: {error}
        </p>
      )}

      {!loading && !error && charts.length === 0 && (
        <p>{t("savedCharts.empty")}</p>
      )}

      {!loading && !error && (
        <>
          {/* My charts ------------------------------------------------------ */}
          <section>
            <h3>{t("savedCharts.myCharts")}</h3>
            <ul>
              {myCharts.map((chart) => (
                <li
                  key={chart.id}
                  aria-current={chart.id === activeId ? "true" : undefined}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    marginBottom: "0.25rem",
                  }}
                >
                  <button
                    onClick={() => onOpen(chart.id)}
                    aria-label={`${t("savedCharts.open")} ${chart.name}`}
                  >
                    {chart.name}
                  </button>
                  <span>
                    {t("savedCharts.updated")} {formatDate(chart.updated_utc)}
                  </span>
                  <button
                    onClick={() => startRename(chart.id, chart.name)}
                    aria-label={t("savedCharts.ariaRename", { name: chart.name })}
                  >
                    {t("savedCharts.rename")}
                  </button>
                  <button
                    onClick={() => duplicateChart(chart.id)}
                    aria-label={t("savedCharts.ariaDuplicate", {
                      name: chart.name,
                    })}
                  >
                    {t("savedCharts.duplicate")}
                  </button>
                  <button
                    onClick={() => startDelete(chart.id)}
                    aria-label={t("savedCharts.ariaDelete", { name: chart.name })}
                  >
                    {t("savedCharts.delete")}
                  </button>
                  {canShare && (
                    <button
                      onClick={() => toggleShare(chart.id)}
                      aria-label={t("savedCharts.ariaShare", {
                        name: chart.name,
                      })}
                    >
                      {chart.shared ? t("savedCharts.unshare") : t("savedCharts.share")}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>

          {/* Shared charts ---------------------------------------------------- */}
          <section>
            <h3>{t("savedCharts.sharedCharts")}</h3>
            <ul>
              {sharedCharts.map((chart) => (
                <li
                  key={chart.id}
                  aria-current={chart.id === activeId ? "true" : undefined}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    marginBottom: "0.25rem",
                  }}
                >
                  <button
                    onClick={() => onOpen(chart.id)}
                    aria-label={`${t("savedCharts.open")} ${chart.name}`}
                  >
                    {chart.name}
                  </button>
                  <span>
                    {t("savedCharts.updated")} {formatDate(chart.updated_utc)}
                  </span>
                  <button
                    onClick={() => copyToMine(chart.id)}
                    aria-label={t("savedCharts.ariaCopy", { name: chart.name })}
                  >
                    {t("savedCharts.copyToMine")}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      {/* Rename modal -------------------------------------------------------- */}
      {renameId && (
        <ModalDialog
          title={t("savedCharts.renameTitle")}
          onClose={cancelRename}
          busy={renameBusy}
        >
          <form onSubmit={confirmRename}>
            <label htmlFor="rename-input">{t("savedCharts.nameLabel")}</label>
            <input
              id="rename-input"
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
            />
            <div style={{ marginTop: "0.5rem" }}>
              <button type="submit">{t("savedCharts.confirm")}</button>
              <button type="button" onClick={cancelRename}>
                {t("savedCharts.cancel")}
              </button>
            </div>
          </form>
        </ModalDialog>
      )}

      {/* Delete confirmation modal ------------------------------------------- */}
      {deleteId && (
        <ModalDialog
          title={t("savedCharts.deleteTitle")}
          onClose={cancelDelete}
          busy={deleteBusy}
        >
          <p>{t("savedCharts.deleteConfirm")}</p>
          <button onClick={confirmDelete}>{t("savedCharts.confirm")}</button>
          <button onClick={cancelDelete}>{t("savedCharts.cancel")}</button>
        </ModalDialog>
      )}
    </div>
  );
}
