// Runtime panel of a soft sensor: mode select with Apply, latest output with a status badge (text
// marker plus colour), used-downstream flag, last lab residual, failover events and the deploy gate.
// A refused mode change (HTTP 409) shows the exact server text in a role=alert region.
import { useCallback, useEffect, useState } from "react";
import type { Translate } from "../findings";
import {
  RUNTIME_MODES, canApplyMode, eventsNewestFirst, fetchSoftSensorRuntime, modeErrorText, setSoftSensorMode,
  statusClass, statusMarker, valueText, type RuntimeEvent, type RuntimeGate, type RuntimeLab, type RuntimeMode,
  type RuntimeOutput, type SoftSensorRuntime as RuntimeState,
} from "../softsensorRuntime";

const yesNo = (flag: boolean, t: Translate): string => t(flag ? "soft.rt.yes" : "soft.rt.no");

/** Runtime state of `sid`, the mode change and its error text. */
function useRuntime(sid: string) {
  const [runtime, setRuntime] = useState<RuntimeState | null>(null);
  const [selected, setSelected] = useState<RuntimeMode>("shadow");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const accept = (state: RuntimeState): void => { setRuntime(state); setSelected(state.mode); };

  useEffect(() => {
    let isCancelled = false;
    fetchSoftSensorRuntime(sid)
      .then((state) => !isCancelled && accept(state))
      .catch((failure: unknown) => !isCancelled && setError(modeErrorText(failure)));
    return () => { isCancelled = true; };
  }, [sid]);

  const apply = useCallback(async () => {
    setBusy(true);
    try {
      accept(await setSoftSensorMode(sid, selected));
      setError(null);
    } catch (failure: unknown) {
      setError(modeErrorText(failure));
    }
    setBusy(false);
  }, [sid, selected]);
  return { runtime, selected, setSelected, error, busy, apply };
}

interface ModeProps {
  runtime: RuntimeState;
  selected: RuntimeMode;
  onSelect: (mode: RuntimeMode) => void;
  busy: boolean;
  onApply: () => void;
  t: Translate;
}

/** Mode select and Apply button. */
function ModeControl({ runtime, selected, onSelect, busy, onApply, t }: ModeProps) {
  return (
    <div className="toolbar">
      <label className="field">
        <span className="field-label">{t("soft.rt.mode")}</span>
        <select className="field-input" value={selected} onChange={(e) => onSelect(e.target.value as RuntimeMode)}>
          {RUNTIME_MODES.map((m) => <option key={m} value={m}>{t(`soft.rt.mode.${m}`)}</option>)}
        </select>
      </label>
      <button type="button" className="filter-chip" disabled={!canApplyMode(runtime.mode, selected, busy)} onClick={onApply}>
        {t("soft.rt.apply")}
      </button>
      <span data-testid="soft-rt-current" className="hint">{t("soft.rt.current", { mode: t(`soft.rt.mode.${runtime.mode}`) })}</span>
    </div>
  );
}

/** Latest output: value, status badge, reason, downstream use. */
function OutputBlock({ output, t }: { output: RuntimeOutput | null; t: Translate }) {
  if (output === null) return <p className="hint" data-testid="soft-rt-no-output">{t("soft.rt.noOutput")}</p>;
  return (
    <div data-testid="soft-rt-output">
      <p>
        <strong data-testid="soft-rt-value">{valueText(output.value)}</strong>{" "}
        <span className={`status-chip ${statusClass(output.status)}`} data-testid="soft-rt-status">
          {statusMarker(output.status)} {t(`soft.rt.status.${output.status}`)}
        </span>
      </p>
      <p data-testid="soft-rt-reason">{t("soft.rt.reason", { reason: output.reason === "" ? "--" : output.reason })}</p>
      <p data-testid="soft-rt-downstream">{t("soft.rt.downstream", { answer: yesNo(output.used_downstream, t) })}</p>
    </div>
  );
}

/** Residual of the latest lab sample against the estimate. */
function LabBlock({ lab, t }: { lab: RuntimeLab | null; t: Translate }) {
  if (lab === null) return <p className="hint" data-testid="soft-rt-no-lab">{t("soft.rt.noLab")}</p>;
  const params = { lab: valueText(lab.lab), estimate: valueText(lab.estimate), residual: valueText(lab.residual), time: lab.sample_utc };
  return <p data-testid="soft-rt-lab">{t("soft.rt.lab", params)}</p>;
}

/** Failover events, newest first, or the empty state. */
function EventList({ events, t }: { events: readonly RuntimeEvent[]; t: Translate }) {
  if (events.length === 0) return <p className="hint" data-testid="soft-rt-no-events">{t("soft.rt.noEvents")}</p>;
  return (
    <ul data-testid="soft-rt-events">
      {eventsNewestFirst(events).map((e) => (
        <li key={`${e.t_utc}-${e.to}`}>
          {t("soft.rt.event", { time: e.t_utc, from: t(`soft.rt.source.${e.from}`), to: t(`soft.rt.source.${e.to}`), reason: e.reason })}
        </li>
      ))}
    </ul>
  );
}

/** The deploy gate: yes/no, skill and the reasons. */
function GateBlock({ gate, t }: { gate: RuntimeGate; t: Translate }) {
  return (
    <div data-testid="soft-rt-gate">
      <p>{t("soft.rt.gate", { deploy: yesNo(gate.deploy, t), skill: valueText(gate.skill, 2) })}</p>
      {gate.message !== "" && <p className="hint">{gate.message}</p>}
      {gate.reasons.length > 0 && <ul>{gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
    </div>
  );
}

/** The Runtime section of the soft sensor view. */
export function SoftSensorRuntime({ sid, t }: { sid: string; t: Translate }) {
  const { runtime, selected, setSelected, error, busy, apply } = useRuntime(sid);
  return (
    <section aria-label={t("soft.rt.title")} data-testid="soft-runtime">
      <h3>{t("soft.rt.title")}</h3>
      <p className="hint">{t("soft.rt.hint")}</p>
      {error !== null && <p className="status status-error" role="alert" data-testid="soft-rt-error">{error}</p>}
      {runtime !== null && (
        <>
          <ModeControl runtime={runtime} selected={selected} onSelect={setSelected} busy={busy} onApply={() => void apply()} t={t} />
          <OutputBlock output={runtime.output} t={t} />
          <LabBlock lab={runtime.last_lab} t={t} />
          <h4>{t("soft.rt.events")}</h4>
          <EventList events={runtime.events} t={t} />
          <h4>{t("soft.rt.gateTitle")}</h4>
          <GateBlock gate={runtime.gate} t={t} />
        </>
      )}
    </section>
  );
}
