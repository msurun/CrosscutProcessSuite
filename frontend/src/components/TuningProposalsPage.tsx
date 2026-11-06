// frontend/src/components/TuningProposalsPage.tsx
/**
 * "Tuning" view (ADR 014, step 8): the proposals to write PID parameters to the DCS. A list with
 * status chips and filters by loop and status, and a detail panel with the diff, confidence,
 * preview, KPI review and the Approve / Reject / Rollback actions. Polls every 5 s while
 * mounted; the interval is cleared on unmount. The page changes nothing by itself.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Translate } from "../findings";
import { fetchTuningProposals, PAGE_SIZE, type TuningProposal } from "../tuningApi";
import { errorText, expiryText, isOpen, loopsOf, matchesFilter, STATUS_GROUPS } from "../tuningRules";
import { ProposalStatusChip, TuningProposalDetail } from "./TuningProposalDetail";
import { TuningProposalActions } from "./TuningProposalActions";

/** How often the list is re-read, in milliseconds. */
export const POLL_INTERVAL_MS = 5000;
const CLOCK_INTERVAL_MS = 1000;

export interface TuningProposalsPageProps {
  t: Translate;
}

interface Paged {
  list: TuningProposal[] | null;
  /** True when the last page read was full, so older proposals may exist. */
  hasMore: boolean;
  /** Text for the aria-live region after "Load more" ("" before the first use). */
  announce: string;
}

interface Polled extends Paged {
  error: string;
  refresh: () => Promise<void>;
  loadMore: () => Promise<void>;
  replace: (updated: TuningProposal) => void;
}

/** The records once, in the order of first appearance (pages can overlap while records arrive). */
function uniqueById(records: TuningProposal[]): TuningProposal[] {
  const seen = new Set<string>();
  return records.filter((p) => !seen.has(p.id) && Boolean(seen.add(p.id)));
}

const fetchPage = (index: number): Promise<TuningProposal[]> =>
  fetchTuningProposals({ limit: PAGE_SIZE, offset: index * PAGE_SIZE });

/** Calls `refresh` now and every POLL_INTERVAL_MS until unmount. */
function usePolling(refresh: () => Promise<void>, alive: { current: boolean }): void {
  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [refresh, alive]);
}

/** Loads the proposals now and every POLL_INTERVAL_MS (only the pages loaded so far); stops and
 * ignores late answers on unmount. The list is paginated: `loadMore` reads the next page. */
export function useTuningProposals(t: Translate): Polled {
  const [state, setState] = useState<Paged>({ list: null, hasMore: false, announce: "" });
  const [error, setError] = useState("");
  const [alive, pages, moreBusy] = [useRef(true), useRef(1), useRef(false)];
  const tRef = useRef(t);
  tRef.current = t;
  const fail = useCallback((failure: unknown) => {
    if (alive.current) setError(errorText(failure, tRef.current));
  }, []);
  const refresh = useCallback(async () => {
    const count = pages.current;
    try {
      const parts = await Promise.all(Array.from({ length: count }, (_, i) => fetchPage(i)));
      if (!alive.current || pages.current !== count) return; // unmounted, or "Load more" won the race
      const full = parts[count - 1].length >= PAGE_SIZE;
      setState((old) => ({ ...old, list: uniqueById(parts.flat()), hasMore: full }));
      setError("");
    } catch (failure: unknown) {
      fail(failure);
    }
  }, [fail]);
  const loadMore = useCallback(async () => {
    if (moreBusy.current) return;
    moreBusy.current = true;
    try {
      const page = await fetchPage(pages.current);
      if (!alive.current) return;
      pages.current += 1;
      setState((old) => appendPage(old, page, tRef.current));
      setError("");
    } catch (failure: unknown) {
      fail(failure);
    } finally {
      moreBusy.current = false;
    }
  }, [fail]);
  usePolling(refresh, alive);
  const replace = useCallback((updated: TuningProposal) => setState((old) => replaceIn(old, updated)), []);
  return { ...state, error, refresh, loadMore, replace };
}

/** The state with one record replaced by its newer version. */
function replaceIn(old: Paged, updated: TuningProposal): Paged {
  return { ...old, list: old.list && old.list.map((p) => (p.id === updated.id ? updated : p)) };
}

/** The state after "Load more": the page merged in, whether more may follow, the announcement. */
function appendPage(old: Paged, page: TuningProposal[], t: Translate): Paged {
  const before = old.list ?? [];
  const list = uniqueById([...before, ...page]);
  const announce = t("tuning.proposals.loadedMore", { added: list.length - before.length, shown: list.length });
  return { list, hasMore: page.length >= PAGE_SIZE, announce };
}

/** Milliseconds since the epoch, ticking every second while `active`. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), CLOCK_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

interface FilterState {
  loop: string;
  group: string;
}

function FilterSelect({
  label,
  value,
  testId,
  options,
  onChange,
  t,
}: {
  label: string;
  value: string;
  testId: string;
  options: { value: string; text: string }[];
  onChange: (value: string) => void;
  t: Translate;
}) {
  return (
    <label>
      {label}{" "}
      <select value={value} data-testid={testId} onChange={(event) => onChange(event.target.value)}>
        <option value="">{t("tuning.proposals.filter.all")}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.text}
          </option>
        ))}
      </select>
    </label>
  );
}

function Filters({
  loops,
  value,
  onChange,
  t,
}: {
  loops: string[];
  value: FilterState;
  onChange: (next: FilterState) => void;
  t: Translate;
}) {
  const loopOptions = loops.map((loop) => ({ value: loop, text: loop }));
  const groupOptions = STATUS_GROUPS.map((group) => ({ value: group, text: t(`tuning.proposals.status.${group}`) }));
  return (
    <div className="toolbar" style={{ flexWrap: "wrap", gap: 12 }}>
      <FilterSelect label={t("tuning.proposals.filter.loop")} value={value.loop} testId="tuning-filter-loop"
        options={loopOptions} onChange={(loop) => onChange({ ...value, loop })} t={t} />
      <FilterSelect label={t("tuning.proposals.filter.status")} value={value.group} testId="tuning-filter-status"
        options={groupOptions} onChange={(group) => onChange({ ...value, group })} t={t} />
    </div>
  );
}

function ProposalRow({
  proposal,
  selected,
  nowMs,
  onSelect,
  t,
}: {
  proposal: TuningProposal;
  selected: boolean;
  nowMs: number;
  onSelect: (id: string) => void;
  t: Translate;
}) {
  return (
    <tr data-testid={`tuning-row-${proposal.id}`}>
      <td>
        <button
          type="button"
          className="filter-chip"
          aria-pressed={selected}
          onClick={() => onSelect(proposal.id)}
        >
          {proposal.loop_id}
        </button>
      </td>
      <td>
        <ProposalStatusChip status={proposal.status} t={t} />
      </td>
      <td>{proposal.created_by}</td>
      <td>{proposal.created_at}</td>
      <td>{expiryText(proposal, nowMs, t)}</td>
    </tr>
  );
}

function ListHead({ t }: { t: Translate }) {
  return (
    <thead>
      <tr>
        <th>{t("tuning.proposals.col.loop")}</th>
        <th>{t("tuning.proposals.col.status")}</th>
        <th>{t("tuning.proposals.col.by")}</th>
        <th>{t("tuning.proposals.col.created")}</th>
        <th>{t("tuning.proposals.col.expiry")}</th>
      </tr>
    </thead>
  );
}

function ProposalTable({
  rows,
  selectedId,
  nowMs,
  onSelect,
  t,
}: {
  rows: TuningProposal[];
  selectedId: string | null;
  nowMs: number;
  onSelect: (id: string) => void;
  t: Translate;
}) {
  return (
    <div className="table-scroll">
      <table className="loops-table" data-testid="tuning-list">
        <ListHead t={t} />
        <tbody>
          {rows.map((proposal) => (
            <ProposalRow
              key={proposal.id}
              proposal={proposal}
              selected={proposal.id === selectedId}
              nowMs={nowMs}
              onSelect={onSelect}
              t={t}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Load error, loading text and the empty states of the list. */
function ListStatus({
  list,
  shown,
  error,
  t,
}: {
  list: TuningProposal[] | null;
  shown: number;
  error: string;
  t: Translate;
}) {
  return (
    <>
      {error !== "" && (
        <div className="notice notice-warning" role="alert" data-testid="tuning-error">
          {t("tuning.proposals.loadError", { reason: error })}
        </div>
      )}
      {list === null && error === "" && <p className="status">{t("tuning.proposals.loading")}</p>}
      {list !== null && shown === 0 && (
        <p className="hint" data-testid="tuning-empty">
          {t(list.length === 0 ? "tuning.proposals.empty" : "tuning.proposals.emptyFiltered")}
        </p>
      )}
    </>
  );
}

/** Count of the loaded proposals, the "Load more" button and its aria-live announcement. */
function MoreControls({
  shown,
  hasMore,
  announce,
  onMore,
  t,
}: {
  shown: number;
  hasMore: boolean;
  announce: string;
  onMore: () => void;
  t: Translate;
}) {
  return (
    <div className="toolbar" style={{ flexWrap: "wrap", gap: 12 }}>
      <span className="hint" data-testid="tuning-count">
        {t(hasMore ? "tuning.proposals.countMore" : "tuning.proposals.count", { shown })}
      </span>
      {hasMore && (
        <button type="button" data-testid="tuning-load-more" onClick={onMore}>
          {t("tuning.proposals.loadMore")}
        </button>
      )}
      <span className="hint" role="status" aria-live="polite" data-testid="tuning-announce">
        {announce}
      </span>
    </div>
  );
}

/** The proposals view. */
export function TuningProposalsPage({ t }: TuningProposalsPageProps) {
  const { list, error, hasMore, announce, refresh, loadMore, replace } = useTuningProposals(t);
  const [filter, setFilter] = useState<FilterState>({ loop: "", group: "" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const nowMs = useNow((list ?? []).some((p) => isOpen(p.status)));
  const rows = (list ?? []).filter((p) => matchesFilter(p, filter.loop, filter.group));
  const selected = (list ?? []).find((p) => p.id === selectedId) ?? null;
  const onChanged = (updated: TuningProposal): void => {
    replace(updated);
    void refresh();
  };

  return (
    <div data-testid="tuning-proposals-page" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="banner">
        <h2>{t("tuning.proposals.title")}</h2>
        <p className="hint">{t("tuning.proposals.subtitle")}</p>
      </div>
      <ListStatus list={list} shown={rows.length} error={error} t={t} />
      <Filters loops={loopsOf(list ?? [])} value={filter} onChange={setFilter} t={t} />
      {rows.length > 0 && (
        <ProposalTable rows={rows} selectedId={selectedId} nowMs={nowMs} onSelect={setSelectedId} t={t} />
      )}
      {list !== null && list.length > 0 && (
        <MoreControls shown={list.length} hasMore={hasMore} announce={announce} onMore={() => void loadMore()} t={t} />
      )}
      {selected !== null && (
        <section>
          <TuningProposalDetail proposal={selected} nowMs={nowMs} t={t} />
          <TuningProposalActions proposal={selected} onChanged={onChanged} onRefresh={() => void refresh()} t={t} />
        </section>
      )}
    </div>
  );
}
