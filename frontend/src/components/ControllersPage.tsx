// frontend/src/components/ControllersPage.tsx
/**
 * Operator console of the APC core (Phase 2.5, step 7): the controllers of the site with their
 * state, last cycle, overruns, liveness and the explanation of the last move; one controller
 * opens in a detail panel. Not dataset-scoped. Polls every 5 s while mounted.
 * Viewers see everything and no buttons; ctl.operate adds On / Standby / Off and the variable controls.
 */

import { useCallback, useEffect, useState } from "react";
import { useCan } from "../AuthContext";
import {
  ControllersApiError,
  fetchController,
  fetchControllers,
  putControllerVariable,
  sendControllerCommand,
  type ControllerCommand,
  type ControllerDetail as Detail,
  type ControllerSummary,
  type VariableOverride,
} from "../controllersApi";
import type { Translate } from "../findings";
import { ControllerDetail } from "./ControllerDetail";
import { ControllerStateChip } from "./ControllerStateChip";
import { GatewayLivenessCell } from "./GatewayLivenessCell";
import { ageSeconds, clockText, isStale, reasonText } from "./controllersFormat";
import { StatusChip } from "./StatusChip";

/** How often the page re-reads the controllers, in milliseconds. */
const POLL_INTERVAL_MS = 5000;

export interface ControllersPageProps {
  t: Translate;
}

const problemsOf = (error: unknown): string[] =>
  error instanceof ControllersApiError ? error.problems : [error instanceof Error ? error.message : String(error)];

function LivenessCell({ row, t }: { row: ControllerSummary; t: Translate }) {
  const age = ageSeconds(row.liveness_utc, Date.now());
  if (age === null) return <StatusChip level="problem" label={t("controllers.liveness.never")} />;
  const level = isStale(row.liveness_utc, row.cycle_s, Date.now()) ? "problem" : "ok";
  return <StatusChip level={level} label={t("controllers.liveness.age", { seconds: age })} />;
}

interface RowProps {
  row: ControllerSummary;
  selected: boolean;
  onOpen: () => void;
  t: Translate;
}

function ControllerRow({ row, selected, onOpen, t }: RowProps) {
  const none = t("controllers.none");
  return (
    <tr data-testid={`controller-row-${row.id}`} aria-selected={selected}>
      <th scope="row">
        <button type="button" className="filter-chip" data-testid={`controller-open-${row.id}`} onClick={onOpen}>{row.id}</button>
      </th>
      <td><ControllerStateChip row={row} t={t} /></td>
      <td>{row.record_unreadable ? none : reasonText(t, row.reason)}</td>
      <td>{clockText(row.last_cycle_utc, none)}{row.last_duration_s !== null && <div className="hint">{row.last_duration_s} s</div>}</td>
      <td>{row.consecutive_overruns} / {row.overruns}</td>
      <td>
        <LivenessCell row={row} t={t} />
        <GatewayLivenessCell id={row.id} liveness={row.gateway_liveness} t={t} />
      </td>
      <td>
        {row.last_explanation || none}
        {row.state === "advisory" && (
          <div className="hint" data-testid={`controller-advice-${row.id}`}>
            {(row.last_advice ?? []).map((m) => `${m.variable_id} -> ${m.value}`).join("; ") || none}
          </div>
        )}
      </td>
    </tr>
  );
}

interface TableProps {
  rows: ControllerSummary[];
  selected: string | null;
  onOpen: (id: string) => void;
  t: Translate;
}

function ControllerTable({ rows, selected, onOpen, t }: TableProps) {
  return (
    <div className="table-scroll">
      <table className="loops-table" data-testid="controllers-list">
        <caption className="hint">{t("controllers.list")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("controllers.col.controller")}</th>
            <th scope="col">{t("controllers.col.state")}</th>
            <th scope="col">{t("controllers.col.reason")}</th>
            <th scope="col">{t("controllers.col.lastCycle")}</th>
            <th scope="col">{t("controllers.col.overruns")}</th>
            <th scope="col">{t("controllers.col.liveness")}</th>
            <th scope="col">{t("controllers.col.explanation")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <ControllerRow key={row.id} row={row} selected={row.id === selected} onOpen={() => onOpen(row.id)} t={t} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ControllersPage({ t }: ControllersPageProps) {
  const canOperate = useCan("ctl.operate").allowed;
  const canConfigure = useCan("config.edit").allowed;
  const [rows, setRows] = useState<ControllerSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [accepted, setAccepted] = useState<string | null>(null);

  const refresh = useCallback(() => {
    const failed = (error: unknown) => setProblems([t("controllers.refreshFailed"), ...problemsOf(error)]);
    fetchControllers().then(setRows).catch(failed);
    if (selected === null) return;
    fetchController(selected).then(setDetail).catch(failed);
  }, [selected, t]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  /** Keep write acceptance separate because a later read failure cannot undo the write. */
  const act = (action: Promise<unknown>, message: string) => {
    setAccepted(null);
    setProblems([]);
    return action.then(() => { setAccepted(message); refresh(); })
      .catch((error: unknown) => setProblems(problemsOf(error)));
  };
  const command = (one: ControllerCommand) => {
    if (selected !== null) void act(sendControllerCommand(selected, one), "controllers.commandAccepted");
  };
  const save = (variableId: string, override: VariableOverride) => {
    if (selected !== null) void act(putControllerVariable(selected, variableId, override).then(setDetail), "configEditor.saved");
  };
  const open = (id: string) => {
    setDetail(null);
    setSelected(id);
  };

  return (
    <div data-testid="controllers-page">
      <div className="banner">
        <h1>{t("controllers.title")}</h1>
        <p className="hint">{t("controllers.subtitle")}</p>
      </div>
      {accepted !== null && <p className="notice" role="status" data-testid="controllers-accepted">{t(accepted)}</p>}
      {problems.length > 0 && (
        <ul className="notice notice-warning" role="alert" data-testid="controllers-error">
          {problems.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
      {rows !== null && rows.length === 0 && <p className="hint">{t("controllers.empty")}</p>}
      {rows !== null && rows.length > 0 && <ControllerTable rows={rows} selected={selected} onOpen={open} t={t} />}
      {detail !== null && <ControllerDetail detail={detail} canOperate={canOperate} onCommand={command} onSave={save} canConfigure={canConfigure} onDetail={setDetail} t={t} />}
    </div>
  );
}
