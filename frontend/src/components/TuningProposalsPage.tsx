// frontend/src/components/TuningProposalsPage.tsx
/**
 * "Tuning" view (ADR 014, step 8): the proposals to write PID parameters to the DCS. A list with
 * status chips and filters by loop and status, and a detail panel with the diff, confidence,
 * preview, KPI review and the Approve / Reject / Rollback actions. Polls every 5 s while
 * mounted; the interval is cleared on unmount. The page changes nothing by itself.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Translate } from "../findings";
import { fetchTuningProposals, type TuningProposal } from "../tuningApi";
import { errorText, expiryText, isOpen, loopsOf, matchesFilter, STATUS_GROUPS } from "../tuningRules";
import { ProposalStatusChip, TuningProposalDetail } from "./TuningProposalDetail";
import { TuningProposalActions } from "./TuningProposalActions";

/** How often the list is re-read, in milliseconds. */
export const POLL_INTERVAL_MS = 5000;
const CLOCK_INTERVAL_MS = 1000;

export interface TuningProposalsPageProps {
  t: Translate;
}

interface Polled {
  list: TuningProposal[] | null;
  error: string;
  refresh: () => Promise<void>;
  replace: (updated: TuningProposal) => void;
}

/** Loads the proposals now and every POLL_INTERVAL_MS; stops and ignores late answers on unmount. */
export function useTuningProposals(t: Translate): Polled {
  const [list, setList] = useState<TuningProposal[] | null>(null);
  const [error, setError] = useState("");
  const alive = useRef(true);
  const tRef = useRef(t);
  tRef.current = t;
  const refresh = useCallback(async () => {
    try {
      const next = await fetchTuningProposals();
      if (alive.current) {
        setList(next);
        setError("");
      }
    } catch (failure: unknown) {
      if (alive.current) setError(errorText(failure, tRef.current));
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [refresh]);
  const replace = useCallback((updated: TuningProposal) => {
    setList((old) => (old === null ? old : old.map((p) => (p.id === updated.id ? updated : p))));
  }, []);
  return { list, error, refresh, replace };
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

/** The proposals view. */
export function TuningProposalsPage({ t }: TuningProposalsPageProps) {
  const { list, error, refresh, replace } = useTuningProposals(t);
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
      {selected !== null && (
        <section>
          <TuningProposalDetail proposal={selected} nowMs={nowMs} t={t} />
          <TuningProposalActions proposal={selected} onChanged={onChanged} t={t} />
        </section>
      )}
    </div>
  );
}
