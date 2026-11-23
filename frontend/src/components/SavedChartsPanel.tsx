// frontend/src/components/SavedChartsPanel.tsx
/**
 * Panel that lists saved trend charts, lets the user open, rename, duplicate,
 * delete, share/unshare and copy charts. It fetches data from the API and
 * updates after each mutation. All UI strings are obtained via the `t`
 * translation function under the `savedCharts` namespace.
 */

import { useCallback, useEffect, useState, FormEvent, ReactNode } from "react";

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

/** Format an ISO UTC timestamp as a local date‑time string. */
function formatDate(utc: string): string {
  return new Date(utc).toLocaleString();
}

/** Chart list state; reloads whenever `reloadToken` changes. */
function useChartList(reloadToken: number) {
  const [charts, setCharts] = useState<ChartSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  /** Load the list of charts from the server. */
  const fetchCharts = useCallback(async (): Promise<void> => {
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
  }, []);

  /** Re‑load charts after a mutation. */
  function refresh(): void {
    void fetchCharts();
  }

  // Load charts on mount and whenever the parent forces a reload.
  useEffect(() => {
    void fetchCharts();
  }, [fetchCharts, reloadToken]);

  return { charts, loading, error, refresh };
}

/** Rename-dialog state; `refresh` reloads the list after a successful rename. */
function useRenameDialog(refresh: () => void) {
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState<string>("");
  const [renameBusy, setRenameBusy] = useState<boolean>(false);

  /** Open the rename dialog for a chart. */
  function startRename(id: string, currentName: string): void {
    setRenameId(id);
    setRenameValue(currentName);
  }

  /** Close the rename dialog and clear its value. */
  function cancelRename(): void {
    setRenameId(null);
    setRenameValue("");
  }

  /** Save the renamed chart and close the dialog. */
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

  return {
    renameId, renameValue, setRenameValue, renameBusy,
    startRename, cancelRename, confirmRename,
  };
}

/** Delete-confirmation state; `refresh` reloads the list after a delete. */
function useDeleteDialog(refresh: () => void) {
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState<boolean>(false);

  /** Open the delete confirmation for a chart. */
  function startDelete(id: string): void {
    setDeleteId(id);
  }

  /** Close the delete confirmation. */
  function cancelDelete(): void {
    setDeleteId(null);
  }

  /** Delete the chart awaiting confirmation and reload the list. */
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

  return { deleteId, deleteBusy, startDelete, cancelDelete, confirmDelete };
}

/** Row actions (duplicate, share toggle, copy); each reloads the list via `refresh`. */
function createChartActions(refresh: () => void) {
  /** Copy a chart (used by both "duplicate" and "copy to mine") and reload. */
  async function copyAndRefresh(id: string): Promise<void> {
    try {
      await copyChart(id);
      refresh();
    } catch (e) {
      console.error(e);
    }
  }

  /** Flip the `shared` flag of a chart and reload the list. */
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

  return { duplicateChart: copyAndRefresh, copyToMine: copyAndRefresh, toggleShare };
}

/** Combine the chart list, both dialogs and the row actions for the panel. */
function useSavedCharts(reloadToken: number) {
  const list = useChartList(reloadToken);
  const rename = useRenameDialog(list.refresh);
  const del = useDeleteDialog(list.refresh);
  const actions = createChartActions(list.refresh);
  return { ...list, ...rename, ...del, ...actions };
}

type SavedChartsState = ReturnType<typeof useSavedCharts>;

interface ChartRowProps {
  chart: ChartSummary;
  isActive: boolean;
  t: Translate;
  onOpen: (id: string) => void;
  children: ReactNode;
}

/** One chart row: open button, updated stamp, then the row's action buttons. */
function ChartRow({ chart, isActive, t, onOpen, children }: ChartRowProps) {
  return (
    <li
      aria-current={isActive ? "true" : undefined}
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
      {children}
    </li>
  );
}

interface ChartSectionProps {
  title: string;
  children: ReactNode;
}

/** A titled section wrapping a list of chart rows. */
function ChartSection({ title, children }: ChartSectionProps) {
  return (
    <section>
      <h3>{title}</h3>
      <ul>{children}</ul>
    </section>
  );
}

interface RowActionsProps {
  chart: ChartSummary;
  t: Translate;
  state: SavedChartsState;
}

interface OwnChartActionsProps extends RowActionsProps {
  canShare: boolean;
}

/** Action buttons for one of the user's own charts. */
function OwnChartActions({ chart, t, state, canShare }: OwnChartActionsProps) {
  return (
    <>
      <button
        onClick={() => state.startRename(chart.id, chart.name)}
        aria-label={t("savedCharts.ariaRename", { name: chart.name })}
      >
        {t("savedCharts.rename")}
      </button>
      <button
        onClick={() => state.duplicateChart(chart.id)}
        aria-label={t("savedCharts.ariaDuplicate", { name: chart.name })}
      >
        {t("savedCharts.duplicate")}
      </button>
      <button
        onClick={() => state.startDelete(chart.id)}
        aria-label={t("savedCharts.ariaDelete", { name: chart.name })}
      >
        {t("savedCharts.delete")}
      </button>
      {canShare && (
        <button
          onClick={() => state.toggleShare(chart.id)}
          aria-label={t("savedCharts.ariaShare", { name: chart.name })}
        >
          {chart.shared ? t("savedCharts.unshare") : t("savedCharts.share")}
        </button>
      )}
    </>
  );
}

/** Action button for a chart shared by someone else: copy it to my charts. */
function SharedChartActions({ chart, t, state }: RowActionsProps) {
  return (
    <button
      onClick={() => state.copyToMine(chart.id)}
      aria-label={t("savedCharts.ariaCopy", { name: chart.name })}
    >
      {t("savedCharts.copyToMine")}
    </button>
  );
}

interface RenameDialogProps {
  t: Translate;
  state: SavedChartsState;
}

/** Modal that asks for a new chart name and saves it. */
function RenameDialog({ t, state }: RenameDialogProps) {
  return (
    <ModalDialog
      title={t("savedCharts.renameTitle")}
      onClose={state.cancelRename}
      busy={state.renameBusy}
    >
      <form onSubmit={state.confirmRename}>
        <label htmlFor="rename-input">{t("savedCharts.nameLabel")}</label>
        <input
          id="rename-input"
          type="text"
          value={state.renameValue}
          onChange={(e) => state.setRenameValue(e.target.value)}
        />
        <div style={{ marginTop: "0.5rem" }}>
          <button type="submit">{t("savedCharts.confirm")}</button>
          <button type="button" onClick={state.cancelRename}>
            {t("savedCharts.cancel")}
          </button>
        </div>
      </form>
    </ModalDialog>
  );
}

interface DeleteDialogProps {
  t: Translate;
  state: SavedChartsState;
}

/** Modal that asks the user to confirm deleting a chart. */
function DeleteDialog({ t, state }: DeleteDialogProps) {
  return (
    <ModalDialog
      title={t("savedCharts.deleteTitle")}
      onClose={state.cancelDelete}
      busy={state.deleteBusy}
    >
      <p>{t("savedCharts.deleteConfirm")}</p>
      <button onClick={state.confirmDelete}>{t("savedCharts.confirm")}</button>
      <button onClick={state.cancelDelete}>{t("savedCharts.cancel")}</button>
    </ModalDialog>
  );
}

interface ChartListsProps {
  state: SavedChartsState;
  t: Translate;
  canShare: boolean;
  activeId: string | null;
  onOpen: (id: string) => void;
}

/** The "My charts" and "Shared charts" sections. */
function ChartLists({ state, t, canShare, activeId, onOpen }: ChartListsProps) {
  const myCharts = state.charts.filter((c) => c.mine);
  const sharedCharts = state.charts.filter((c) => c.shared && !c.mine);
  return (
    <>
      <ChartSection title={t("savedCharts.myCharts")}>
        {myCharts.map((chart) => (
          <ChartRow
            key={chart.id}
            chart={chart}
            isActive={chart.id === activeId}
            t={t}
            onOpen={onOpen}
          >
            <OwnChartActions chart={chart} t={t} state={state} canShare={canShare} />
          </ChartRow>
        ))}
      </ChartSection>
      <ChartSection title={t("savedCharts.sharedCharts")}>
        {sharedCharts.map((chart) => (
          <ChartRow
            key={chart.id}
            chart={chart}
            isActive={chart.id === activeId}
            t={t}
            onOpen={onOpen}
          >
            <SharedChartActions chart={chart} t={t} state={state} />
          </ChartRow>
        ))}
      </ChartSection>
    </>
  );
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
  const state = useSavedCharts(reloadToken);
  const ready = !state.loading && !state.error;
  return (
    <div>
      <h2>{t("savedCharts.title")}</h2>

      {state.loading && <p>{t("savedCharts.loading")}</p>}

      {state.error && (
        <p>
          {t("savedCharts.error")}: {state.error}
        </p>
      )}

      {ready && state.charts.length === 0 && <p>{t("savedCharts.empty")}</p>}

      {ready && (
        <ChartLists
          state={state}
          t={t}
          canShare={canShare}
          activeId={activeId}
          onOpen={onOpen}
        />
      )}

      {state.renameId && <RenameDialog t={t} state={state} />}
      {state.deleteId && <DeleteDialog t={t} state={state} />}
    </div>
  );
}
